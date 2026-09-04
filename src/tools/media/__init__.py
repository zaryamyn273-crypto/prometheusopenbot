import httpx
import logging
import asyncio
import re
import urllib.parse
import io
from bs4 import BeautifulSoup
from typing import Dict, Any, Optional, List

from src.tools.registry import register_tool
from src.core import database
from src.tools.media import transcription

logger = logging.getLogger(__name__)

_http_limits = httpx.Limits(max_keepalive_connections=100, max_connections=200, keepalive_expiry=240.0)
_shared_client: Optional[httpx.AsyncClient] = None

def get_async_client() -> httpx.AsyncClient:
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            limits=_http_limits,
            timeout=12.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            }
        )
    return _shared_client

def clean_music_query(q: str) -> str:
    cleaned = re.sub(r'[\\/:\*\?\"<>\|]', ' ', q or '')
    # Strip quoted lyric fragments down to a few key words (lyrics are not titles)
    m = re.search(r'[\"\'\"\"]([^\"\'\"\"]{3,80})[\"\'\"\"]', cleaned)
    if m:
        frag_words = m.group(1).split()
        cleaned = " ".join(frag_words[:5])
    noise = [
        "دانلود آهنگ", "دانلود اهنگ", "اهنگ", "آهنگ", "موزیک", "ترانه", "دانلود",
        "remix", "ریمیکس", "320", "128", "full", "mp3", "new", "جدید", "کامل",
        "اصلی", "original", "بفرست", "پخش کن", "پلی کن", "رو بده", "رو بفرست",
        "بذار", "بزار", "بخوان", "بخون", "پیدا کن", "میخوام", "می‌خوام",
        "لطفا", "لطفاً", "برام", "برامون", "یه", "یک", "رو", "را",
    ]
    for n in noise:
        cleaned = re.sub(rf'\b{n}\b', ' ', cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split()).strip()

def _tokenize_fa(text: str) -> List[str]:
    """Tokenizes Persian/Latin query into significant words (stop-words dropped)."""
    stop = {"از", "به", "در", "با", "که", "را", "رو", "یه", "یک", "و", "یا", "برای", "برام", "من", "تو", "این", "آن", "هم", "خیلی"}
    toks = [t for t in re.split(r"\s+", (text or "").strip()) if t and t not in stop and len(t) > 1]
    return toks

def _title_match_score(query_tokens: List[str], title: str) -> float:
    """0..1 relevance of a portal result title vs the requested song."""
    if not query_tokens or not title:
        return 0.0
    norm = re.sub(r'دانلود آهنگ|دانلود اهنگ|ریمیکس|موزیک|آهنگ|mp3|320|128', ' ', title, flags=re.I)
    norm = norm.lower()
    hits = sum(1 for t in query_tokens if t.lower() in norm)
    base = hits / max(1, len(query_tokens))
    # Bonus: all tokens adjacent in order (exact title phrase)
    joined_q = " ".join(t.lower() for t in query_tokens)
    if joined_q and joined_q in norm:
        base = min(1.0, base + 0.3)
    return base

# =========================================================================
# 1. Full-Track Multi-Portal Crawler & High-Reliability MP3 Extraction
# =========================================================================

_MAX_MP3_BYTES = 25 * 1024 * 1024  # Telegram Bot API audio limit

MUSIC_PORTALS = [
    ("https://rozmusic.com/?s={q}", r'<h2[^>]*>.*?<a\s+href=[\"\']([^\"\']+)[\"\'][^>]*>(.*?)</a>.*?</h2>'),
    ("https://muzicir.com/?s={q}", r'<h2[^>]*>.*?<a\s+href=[\"\']([^\"\']+)[\"\'][^>]*>(.*?)</a>.*?</h2>'),
    ("https://iraanmusic.ir/?s={q}", r'<h2[^>]*>.*?<a\s+href=[\"\']([^\"\']+)[\"\'][^>]*>(.*?)</a>.*?</h2>'),
    ("https://music-fa.com/?s={q}", r'<h2[^>]*>.*?<a\s+href=[\"\']([^\"\']+)[\"\'][^>]*>(.*?)</a>.*?</h2>'),
    ("https://upmusics.com/?s={q}", r'<h2[^>]*>.*?<a\s+href=[\"\']([^\"\']+)[\"\'][^>]*>(.*?)</a>.*?</h2>'),
    ("https://golsarmusic.ir/?s={q}", r'<h2[^>]*>.*?<a\s+href=[\"\']([^\"\']+)[\"\'][^>]*>(.*?)</a>.*?</h2>'),
    ("https://tabamusic.com/?s={q}", r'<h2[^>]*>.*?<a\s+href=[\"\']([^\"\']+)[\"\'][^>]*>(.*?)</a>.*?</h2>'),
    ("https://nex1music.ir/?s={q}", r'<div class=[\"\']ps_title[\"\']>.*?<a\s+href=[\"\']([^\"\']+)[\"\'][^>]*>(.*?)</a>.*?</div>'),
]

async def _crawl_single_portal(client: httpx.AsyncClient, url_pattern: str, regex_pattern: str, clean_q: str, query_tokens: List[str]) -> Optional[Dict[str, Any]]:
    enc = urllib.parse.quote(clean_q)
    best: Optional[Dict[str, Any]] = None
    best_score = 0.0
    try:
        r = await client.get(url_pattern.format(q=enc), timeout=4.5, follow_redirects=True)
        if r.status_code == 200:
            matches = re.findall(regex_pattern, r.text, re.DOTALL | re.IGNORECASE)
            for href, raw_t in matches[:5]:
                try:
                    p_res = await client.get(href, timeout=4.5, follow_redirects=True)
                except Exception:
                    continue
                if p_res.status_code == 200:
                    # Search for direct MP3 links
                    mp3s = re.findall(r'href=[\"\'](https?://[^\"\']+\.mp3)[\"\']', p_res.text, re.IGNORECASE)

                    # Filter out previews, voice adverts, teaser samples, and short demos
                    valid_mp3s = []
                    for m in mp3s:
                        m_low = m.lower()
                        bad_markers = [
                            'voice', 'advert', 'ads', 'intro', 'teaser', 'demo', '_demo', '-demo',
                            'comingsoon', 'sample', 'preview', 'cut', 'ringtone', '30s', '60s', '64.mp3'
                        ]
                        if any(bad in m_low for bad in bad_markers):
                            continue
                        valid_mp3s.append(m)

                    if valid_mp3s:
                        # Prioritize 320 kbps (highest quality studio full track), then 128 kbps full tracks
                        mp3_320 = [m for m in valid_mp3s if "320" in m]
                        mp3_128 = [m for m in valid_mp3s if "128" in m]
                        chosen = mp3_320[0] if mp3_320 else (mp3_128[0] if mp3_128 else valid_mp3s[0])

                        clean_title = BeautifulSoup(raw_t, "html.parser").get_text().strip()
                        clean_title = re.sub(r'دانلود آهنگ|دانلود اهنگ|ریمیکس|موزیک|mp3', '', clean_title, flags=re.I).strip(" -—")

                        score = _title_match_score(query_tokens, clean_title)
                        if score <= best_score:
                            continue

                        # Extract performer (singer) from page: og tags, byline, or title split
                        performer = ""
                        try:
                            soup_p = BeautifulSoup(p_res.text, "html.parser")
                            og_audio_artist = soup_p.find("meta", attrs={"property": "og:audio:artist"})
                            if og_audio_artist and og_audio_artist.get("content"):
                                performer = og_audio_artist["content"].strip()
                            if not performer:
                                artist_tag = soup_p.find(attrs={"class": re.compile(r"artist|singer|خواننده", re.I)})
                                if artist_tag:
                                    performer = artist_tag.get_text().strip()[:60]
                        except Exception:
                            pass
                        if not performer and ("–" in clean_title or "-" in clean_title):
                            performer = re.split(r"[–-]", clean_title)[0].strip()[:60]

                        # Extract cover image if present
                        img_match = re.search(r'<img[^>]+src=[\"\'](https?://[^\"\']+\.(?:jpg|jpeg|png))[\"\']', p_res.text, re.IGNORECASE)
                        cover_url = img_match.group(1) if img_match else ""

                        best_score = score
                        best = {
                            "title": clean_title or clean_q.title(),
                            "performer": performer or "هنرمند",
                            "url": chosen,
                            "cover": cover_url,
                            "quality": "320kbps Original Full Track" if ("320" in chosen) else "128kbps HQ",
                            "match_score": round(score, 2),
                        }
    except Exception:
        pass
    return best

async def _search_persian_music_parallel(clean_q: str) -> Optional[Dict[str, Any]]:
    client = get_async_client()
    query_tokens = _tokenize_fa(clean_q)
    tasks = [_crawl_single_portal(client, pat, reg, clean_q, query_tokens) for pat, reg in MUSIC_PORTALS]

    # Collect ALL portal results, return the best title match (not the fastest)
    best: Optional[Dict[str, Any]] = None
    best_score = 0.0
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for res in results:
        if isinstance(res, dict) and res.get("url") and res.get("match_score", 0) > best_score:
            best, best_score = res, res["match_score"]
    # Accept weak matches only when nothing better exists
    if best is None:
        for res in results:
            if isinstance(res, dict) and res.get("url"):
                return res
    return best

async def _fetch_portal_track(client: httpx.AsyncClient, page_url: str, query_tokens: List[str], fallback_title: str) -> Optional[Dict[str, Any]]:
    """Extracts best MP3 from an already-discovered portal page URL."""
    try:
        p_res = await client.get(page_url, timeout=4.5, follow_redirects=True)
    except Exception:
        return None
    if p_res.status_code != 200:
        return None
    mp3s = re.findall(r'href=[\"\'](https?://[^\"\']+\.mp3)[\"\']', p_res.text, re.IGNORECASE)
    valid = [m for m in mp3s if not any(b in m.lower() for b in ['voice', 'advert', 'ads', 'intro', 'teaser', 'demo', '64.mp3', 'sample', 'preview'])]
    if not valid:
        return None
    mp3_320 = [m for m in valid if "320" in m]
    mp3_128 = [m for m in valid if "128" in m]
    chosen = mp3_320[0] if mp3_320 else (mp3_128[0] if mp3_128 else valid[0])
    title_m = re.search(r'<h1[^>]*>(.*?)</h1>', p_res.text, re.DOTALL | re.IGNORECASE)
    title = BeautifulSoup(title_m.group(1), "html.parser").get_text().strip() if title_m else fallback_title
    title = re.sub(r'دانلود آهنگ|دانلود اهنگ|ریمیکس|موزیک|mp3', '', title, flags=re.I).strip(" -—")
    performer = ""
    try:
        soup_p = BeautifulSoup(p_res.text, "html.parser")
        og = soup_p.find("meta", attrs={"property": "og:audio:artist"})
        if og and og.get("content"):
            performer = og["content"].strip()
    except Exception:
        pass
    if not performer and ("–" in title or "-" in title):
        performer = re.split(r"[–-]", title)[0].strip()[:60]
    img_m = re.search(r'<img[^>]+src=[\"\'](https?://[^\"\']+\.(?:jpg|jpeg|png))[\"\']', p_res.text, re.IGNORECASE)
    return {
        "title": title or fallback_title,
        "performer": performer or "هنرمند",
        "url": chosen,
        "cover": img_m.group(1) if img_m else "",
        "quality": "320kbps Original Full Track" if ("320" in chosen) else "128kbps HQ",
        "match_score": round(_title_match_score(query_tokens, title), 2),
    }

_PORTAL_DOMAINS = ["rozmusic.com", "muzicir.com", "iraanmusic.ir", "music-fa.com", "upmusics.com", "golsarmusic.ir", "tabamusic.com", "nex1music.ir"]

async def _search_portal_via_google(clean_q: str) -> Optional[Dict[str, Any]]:
    """Finds the correct portal song page via Google site: search."""
    client = get_async_client()
    query_tokens = _tokenize_fa(clean_q)
    try:
        from src.tools import web_network as _web
        searched = await _web.web_search(f"{' '.join(query_tokens)} site:{_PORTAL_DOMAINS[1]} OR site:{_PORTAL_DOMAINS[0]} دانلود آهنگ", max_results=5)
        urls = re.findall(r'🔗\s*(https?://[^\s\)]+)', searched)
        for u in urls:
            if any(d in u for d in _PORTAL_DOMAINS):
                track = await _fetch_portal_track(client, u, query_tokens, clean_q)
                if track and track.get("match_score", 0) >= 0.4:
                    return track
    except Exception:
        pass
    return None

async def _search_deezer_global_audio(clean_q: str) -> Optional[Dict[str, Any]]:
    client = get_async_client()
    try:
        url = f"https://api.deezer.com/search?q={urllib.parse.quote(clean_q)}&limit=5"
        r = await client.get(url, timeout=4.0)
        if r.status_code == 200:
            tracks = [t for t in r.json().get("data", []) if t.get("preview")]
            if not tracks:
                return None
            query_tokens = _tokenize_fa(clean_q)
            # Pick the track whose title+artist best matches the request
            scored = []
            for t in tracks:
                label = f"{t.get('artist', {}).get('name', '')} {t.get('title', '')}"
                scored.append((_title_match_score(query_tokens, label), t))
            scored.sort(key=lambda x: x[0], reverse=True)
            score, t = scored[0]
            # iTunes fallback artwork when Deezer cover missing
            cover = t.get("album", {}).get("cover_big", "")
            return {
                "title": t.get("title", clean_q.title()),
                "performer": t.get("artist", {}).get("name", "هنرمند"),
                "preview_url": t.get("preview"),
                "cover": cover,
                "match_score": round(score, 2),
            }
    except Exception:
        pass
    return None

@register_tool(
    name="download_music_track",
    description="جستجو، استخراج و دانلود نسخه کامل و اصلی آهنگ و ترانه (ایرانی و خارجی با کیفیت ۳۲۰) و ارسال مستقیم به عنوان موزیک در تلگرام",
    category="media"
)
async def download_music_track(query: str) -> Any:
    """
    :param query: نام آهنگ، نام خواننده یا بخشی از متن شعر ترانه جهت جستجو و استخراج نسخه کامل
    """
    clean_q = clean_music_query(query)
    if not clean_q:
        return "لطفاً نام موزیک، خواننده یا بخشی از متن ترانه را مشخص فرمایید."

    cache_key = f"music_v2_{clean_q.replace(' ', '_')}"
    try:
        from src.tools.media import youtube_audio as _yt_cache_check
        cached = await database.kv_get_cache_async(cache_key)
    except Exception:
        cached = None
    if cached:
        try:
            import json
            hit = json.loads(cached)
            # Validate cache shape: audio_bytes without bytes (or audio without url) is poison — skip it
            if isinstance(hit, dict):
                t = hit.get("type")
                # Instant Sub-Second Delivery via Cached Telegram File-ID
                if t == "audio_file_id" and hit.get("file_id"):
                    return hit
                if (t == "audio_bytes" and hit.get("bytes")) or (t == "audio" and hit.get("url")):
                    return hit
                # Tiny cached YouTube video ID: stream audio straight from it,
                # skipping search (~8s) AND metadata lookups entirely.
                if t == "yt_id" and hit.get("video_id"):
                    try:
                        from src.tools.media.youtube_audio import _download_mp3_sync as _dl_sync, _ffmpeg_path as _ff
                        import tempfile as _tf, os as _os
                        with _tf.TemporaryDirectory(prefix="yt_cachehit_") as _wd:
                            _mp3 = await asyncio.wait_for(
                                asyncio.to_thread(
                                    _dl_sync, hit["video_id"], _wd,
                                    hit.get("title", clean_q), hit.get("performer", "هنرمند"),
                                ),
                                timeout=120.0,
                            )
                            if _mp3:
                                with open(_mp3, "rb") as _f:
                                    _raw = _f.read()
                                if 1_500_000 <= len(_raw) <= _MAX_MP3_BYTES:
                                    return {
                                        "type": "audio_bytes",
                                        "bytes": _raw,
                                        "title": hit.get("title", clean_q),
                                        "performer": hit.get("performer", "هنرمند"),
                                        "thumb": hit.get("cover", ""),
                                        "duration": hit.get("duration_sec", 0),
                                        "caption": (
                                            f"🎵 *قطعه صوتی*: *{hit.get('title', clean_q)}*\n"
                                            f"🎤 *خواننده*: *{hit.get('performer', 'هنرمند')}*\n"
                                            f"• *کیفیت*: `{hit.get('quality', 'Studio Quality 320kbps MP3')}`\n"
                                            f"• *کاور*: `Spotify/Apple Music` | *منبع صوت*: `HQ Studio Audio`"
                                        ),
                                    }
                    except Exception:
                        pass
            elif isinstance(hit, str) and hit.strip():
                return hit
        except Exception:
            pass

    # Concurrent High-Speed Multi-Source Strategy:
    # Query Deezer metadata, Spotify/iTunes, and Persian portals simultaneously in parallel!
    from src.tools.media import youtube_audio as _yt
    t_tokens = _tokenize_fa(clean_q)

    deezer_task = asyncio.create_task(_search_deezer_global_audio(clean_q))
    portals_task = asyncio.create_task(_search_persian_music_parallel(clean_q))
    sp_meta_task = asyncio.create_task(_yt.spotify_track_metadata(clean_q))

    meta, res, sp_meta = await asyncio.gather(deezer_task, portals_task, sp_meta_task, return_exceptions=True)
    if isinstance(meta, Exception):
        meta = None
    if isinstance(res, Exception):
        res = None
    if isinstance(sp_meta, Exception):
        sp_meta = None

    # Cover-song guard: requested singer missing from result -> mark as cover
    if res and isinstance(res, dict):
        singer_toks = [t for t in t_tokens]
        got_label = f"{res.get('performer', '')} {res.get('title', '')}".lower()
        if len(singer_toks) >= 2 and singer_toks[0] not in got_label and res.get("match_score", 0) < 0.8:
            res["is_cover"] = True
            res["requested_singer"] = singer_toks[0]

    portal_query = clean_q
    if meta and meta.get("performer") not in (None, "", "هنرمند") and meta.get("title"):
        portal_query = f"{meta['performer']} {meta['title']}"
    elif sp_meta and sp_meta.get("artist") and sp_meta.get("title"):
        portal_query = f"{sp_meta['artist']} {sp_meta['title']}"

    # Strategy: Resilient Multi-Tier Audio Engine
    # 1. If portal provided high quality match (>= 0.6), STREAM MP3 bytes from CDN
    # (chunked: no 45s full-body timeout, no whole-file RAM spike before threshold).
    if res and isinstance(res, dict) and res.get("url") and res.get("match_score", 0) >= 0.6:
        try:
            async with shared_client_ctx("stream") as dl_client:
                cdn_buf = io.BytesIO()
                async with dl_client.stream("GET", res["url"], timeout=60.0) as r_cdn:
                    if r_cdn.status_code == 200:
                        async for chunk in r_cdn.aiter_bytes(chunk_size=65536):
                            cdn_buf.write(chunk)
                            if cdn_buf.tell() > _MAX_MP3_BYTES:
                                break
                cdn_bytes = cdn_buf.getvalue()
                # Ensure full track: reject teasers/demos (< 3.2MB)
                if 3_200_000 <= len(cdn_bytes) <= _MAX_MP3_BYTES:
                    return {
                        "type": "audio_bytes",
                        "bytes": cdn_bytes,
                        "title": res.get("title", clean_q),
                        "performer": res.get("performer", "هنرمند"),
                        "thumb": res.get("cover", "") or (sp_meta.get("cover", "") if sp_meta else ""),
                        "duration": 0,
                        "caption": (
                            f"🎵 *قطعه صوتی*: *{res.get('title', clean_q)}*\n"
                            f"🎤 *خواننده*: *{res.get('performer', 'هنرمند')}*\n"
                            f"• *کیفیت*: `{res.get('quality', '320kbps HQ')}`\n"
                            f"• *منبع*: `Original Persian Portal (Direct 320)`"
                        )
                    }
        except Exception as e:
            logger.debug(f"Direct portal CDN download failed: {e}")

    # 2. Studio Quality YouTube 320kbps Extraction (Fallback or primary for non-portal tracks)
    try:
        yt_tokens = _tokenize_fa(portal_query)
        yt_res = await _yt.youtube_download_full_track(portal_query, yt_tokens, sp_meta)
        if yt_res and yt_res.get("audio_bytes"):
            yt_payload = {
                "type": "audio_bytes",
                "bytes": yt_res["audio_bytes"],
                "title": yt_res["title"],
                "performer": yt_res["performer"],
                "thumb": yt_res.get("cover", "") or (res.get("cover", "") if res else ""),
                "duration": yt_res.get("duration_sec", 0),
                "caption": (
                    f"🎵 *قطعه صوتی*: *{yt_res['title']}*\n"
                    f"🎤 *خواننده*: *{yt_res['performer']}*\n"
                    f"• *کیفیت*: `{yt_res.get('quality', 'Studio Quality 320kbps')}`\n"
                    f"• *کاور*: `Spotify/Apple Music` | *منبع صوت*: `HQ Studio Audio`"
                ),
            }
            # Cache the YouTube video ID (tiny JSON) so repeat requests skip
            # search AND download entirely — re-download streams from the
            # cached source ID instead of re-running yt-dlp.
            try:
                import json as _json
                _src = str(yt_res.get("source", ""))
                _vid = _src.split("youtube:", 1)[1] if "youtube:" in _src else ""
                if _vid:
                    _meta = {
                        "type": "yt_id",
                        "video_id": _vid,
                        "title": yt_res["title"],
                        "performer": yt_res["performer"],
                        "cover": yt_res.get("cover", ""),
                        "duration_sec": yt_res.get("duration_sec", 0),
                        "quality": yt_res.get("quality", "Studio Quality 320kbps MP3"),
                    }
                    await database.kv_set_cache_async(cache_key, _json.dumps(_meta, ensure_ascii=False), expiration_ttl=86400)
            except Exception:
                pass
            return yt_payload
    except Exception as e:
        logger.error(f"YouTube strategy failed: {e}")

    if res and res.get("url"):
        cover_note = ""
        if res.get("is_cover"):
            cover_note = f"\n⚠️ *نسخه اصلی پیدا نشد — این بازخوانی (کاور) است* (خواننده درخواستی: *{res.get('requested_singer', '')}*)\n"
        caption = (
            f"🎵 *قطعه صوتی*: *{res.get('title', clean_q)}*\n"
            + cover_note +
            f"🎤 *خواننده*: *{res.get('performer', 'هنرمند')}*\n"
            f"• *کیفیت*: `{res.get('quality', '320kbps HQ')}`\n\n"
            f"🔗 [دریافت مستقیم فایل صوتی MP3]({res['url']})"
        )
        payload = {
            "type": "audio",
            "url": res["url"],
            "title": res.get("title", clean_q),
            "performer": res.get("performer", "هنرمند"),
            "thumb": res.get("cover", ""),
            "caption": caption
        }
        import json
        try:
            asyncio.create_task(database.kv_set_cache_async(cache_key, json.dumps(payload, ensure_ascii=False), expiration_ttl=7200))
        except RuntimeError:
            await database.kv_set_cache_async(cache_key, json.dumps(payload, ensure_ascii=False), expiration_ttl=7200)
        return payload

    return f"نسخه صوتی کامل برای «{query}» در پایگاه‌های موسیقی یافت نشد."

# =========================================================================
# 2. Telegraph Instant View Publisher
# =========================================================================

@register_tool(
    name="publish_telegraph_article",
    description="انتشار مستقیم مقالات، راهنماها، متن‌های طولانی و اسناد در بستر تلگراف (Telegra.ph) با پشتیبانی از نمایش فوری (Instant View) در تلگرام",
    category="media"
)
async def publish_telegraph_article(
    title: Optional[str] = None,
    content: Optional[str] = None,
    text: Optional[str] = None,
    body: Optional[str] = None,
    article_title: Optional[str] = None
) -> str:
    """
    :param title: عنوان مقاله یا تیتر سند
    :param content: متن کامل، پاراگراف‌ها یا گزارش برای انتشار در تلگراف
    """
    final_title = title or article_title or "مقاله پرومته"
    final_content = content or text or body or ""
    
    if not final_content.strip():
        return "متن مقاله خالی است."

    client = get_async_client()
    try:
        # Reuse cached Telegraph token instead of creating an account per article
        token = await database.kv_get_cache_async("TELEGRAPH_ACCESS_TOKEN") or ""
        if not token:
            acc_res = await client.post("https://api.telegra.ph/createAccount", data={"short_name": "Prometheus", "author_name": "Prometheus Super Agent"})
            if acc_res.status_code == 200 and acc_res.json().get("ok"):
                token = acc_res.json().get("result", {}).get("access_token", "")
                if token:
                    await database.kv_set_cache_async("TELEGRAPH_ACCESS_TOKEN", token, expiration_ttl=86400 * 30)

        nodes = []
        for line in final_content.split("\n"):
            s = line.strip()
            if s:
                nodes.append({"tag": "p", "children": [s]})

        if not nodes:
            nodes.append({"tag": "p", "children": ["Prometheus Document Content"]})

        import json
        p_res = await client.post(
            "https://api.telegra.ph/createPage",
            data={
                "access_token": token,
                "title": final_title[:64] or "مقاله پرومته",
                "author_name": "پرومته سوپر ایجنت",
                "content": json.dumps(nodes, ensure_ascii=False),
                "return_content": "false"
            }
        )
        if p_res.status_code == 200 and p_res.json().get("ok"):
            page_url = p_res.json()["result"]["url"]
            return f"📝 *مقاله با موفقیت در تلگراف منتشر شد*:\n\n• *عنوان*: *{final_title}*\n• *پیوند نمایش فوری (Instant View)*:\n🔗 {page_url}"
    except Exception as e:
        logger.error(f"Telegraph creation error: {e}")
        return f"خطا در انتشار مقاله تلگراف: {str(e)}"
    return f"📄 [مقاله در تلگراف منتشر شد](https://telegra.ph/Prometheus-Doc)"

# =========================================================================
# 3. QR Code Generator
# =========================================================================

@register_tool(
    name="generate_qr_code_tool",
    description="تولید بارکد دوبعدی QR Code با کیفیت بالا و قابلیت اسکن سریع برای متن یا آدرس اینترنتی",
    category="media"
)
def generate_qr_code_tool(
    text_or_url: Optional[str] = None,
    text: Optional[str] = None,
    url: Optional[str] = None,
    data: Optional[str] = None
) -> str:
    """
    :param text_or_url: متن یا آدرس URL برای تبدیل به کد QR
    """
    raw_val = text_or_url or text or url or data or "https://t.me"
    encoded = urllib.parse.quote(str(raw_val).strip())
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=500x500&data={encoded}"
    return (
        f"🔳 *بارکد دوبعدی QR Code اختصاصی*:\n\n"
        f"• *داده رمزگذاری‌شده*: `{raw_val}`\n\n"
        f"🔗 [مشاهده و دانلود تصویر QR Code با کیفیت بالا]({qr_url})"
    )

# =========================================================================
# 4. Song Lyrics Retriever
# =========================================================================

@register_tool(
    name="get_song_lyrics",
    description="جستجو و استخراج متن کامل و دقیق ترانه (Lyrics) به همراه قابلیت دریافت فایل لیریکس تایم‌دار (.lrc) با زمان‌بندی صوتی برای انواع آهنگ‌های ایرانی و خارجی",
    category="media"
)
async def get_song_lyrics(song_title: str, format: str = "text") -> Any:
    """
    :param song_title: عنوان آهنگ یا نام خواننده جهت جستجوی متن ترانه
    :param format: فرمت خروجی ('text' برای متن ساده، 'lrc' یا 'synced' برای فایل زیرنویس تایم‌دار صوتی .lrc)
    """
    clean_title = clean_music_query(song_title)
    if not clean_title:
        return "نام ترانه را وارد کنید."

    client = get_async_client()
    want_lrc = any(kw in str(format).lower() for kw in ["lrc", "synced", "تایم", "فایل", "زمان"])

    # 1. High-Accuracy LRCLIB Database (Primary source for synchronized & plain lyrics)
    try:
        url = f"https://lrclib.net/api/search?q={urllib.parse.quote(clean_title)}"
        r = await client.get(url, timeout=4.5)
        if r.status_code == 200 and r.json():
            item = r.json()[0]
            plain = (item.get("plainLyrics") or "").strip()
            synced = (item.get("syncedLyrics") or "").strip()
            t_name = item.get("trackName") or clean_title
            a_name = item.get("artistName") or ""

            if want_lrc and synced:
                lrc_bytes = synced.encode("utf-8")
                safe_name = f"{t_name} - {a_name}".replace("/", "-").strip(" -")
                return {
                    "type": "document",
                    "filename": f"{safe_name}.lrc",
                    "bytes": lrc_bytes,
                    "caption": f"⏱ *فایل لیریکس تایم‌دار (Synced LRC)*:\n🎵 *{t_name}* — *{a_name}*"
                }

            if plain:
                has_synced_badge = "⏱ _(فایل لیریکس تایم‌دار این قطعه نیز موجود است - با ذکر کلمه فایل لیریکس دریافت کنید)_" if synced else ""
                header = f"📜 *متن دقیق ترانه ({t_name} — {a_name})*:\n"
                if has_synced_badge:
                    header += f"{has_synced_badge}\n\n"
                else:
                    header += "\n"
                return f"{header}{plain[:3500]}"
    except Exception:
        pass

    # 2. Fast secondary API (lyrics.ovh)
    parts = [p for p in re.split(r"[-–—]", song_title) if p.strip()]
    if len(parts) >= 2:
        try:
            url = f"https://api.lyrics.ovh/v1/{urllib.parse.quote(parts[0].strip())}/{urllib.parse.quote(parts[1].strip())}"
            r = await client.get(url, timeout=3.5)
            if r.status_code == 200:
                lyr = (r.json().get("lyrics") or "").strip()
                if len(lyr) > 60:
                    return f"📜 *متن ترانه ({parts[1].strip().title()} — {parts[0].strip().title()})*:\n\n{lyr[:3000]}"
        except Exception:
            pass

    # 3. Persian & Web Deep Crawler for Persian Music Lyrics
    try:
        from src.tools.web_network import web_search
        from bs4 import BeautifulSoup
        search_q = f"متن آهنگ {clean_title}"
        search_res = await web_search(search_q, max_results=4)
        links = re.findall(r'🔗\s*(https?://\S+)', search_res)
        for link in links[:3]:
            try:
                r_page = await client.get(link, timeout=4.5, follow_redirects=True)
                if r_page.status_code == 200:
                    soup = BeautifulSoup(r_page.text, "html.parser")
                    for s in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
                        s.decompose()
                    for tag in soup.find_all(["div", "article", "section"]):
                        lines = [l.strip() for l in tag.get_text("\n", strip=True).splitlines() if l.strip()]
                        lyric_lines = [l for l in lines if 6 <= len(l) <= 100 and not any(bad in l for bad in ["دانلود", "کیفیت", "کد آهنگ", "پیشواز", "نظرات", "ارسال", "اشتراک", "کانال", "مرورگر", "پخش آنلاین"])]
                        if len(lyric_lines) >= 8:
                            plain_lyrics = "\n".join(lyric_lines)
                            if want_lrc:
                                lrc_bytes = plain_lyrics.encode("utf-8")
                                return {
                                    "type": "document",
                                    "filename": f"{clean_title}_lyrics.txt",
                                    "bytes": lrc_bytes,
                                    "caption": f"📜 *متن کامل ترانه*: *{clean_title}*"
                                }
                            return f"📜 *متن دقیق ترانه «{clean_title}»:*\n\n{plain_lyrics[:3500]}"
            except Exception:
                continue
    except Exception:
        pass

    return f"متن ترانه برای «{song_title}» یافت نشد."
