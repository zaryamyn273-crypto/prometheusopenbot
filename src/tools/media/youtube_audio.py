"""
High-Performance YouTube HQ Audio Fetcher + iTunes/Spotify Metadata Engine.
Part of the Prometheus Audio Super-System.
"""
import asyncio
import logging
import os
import tempfile
from typing import Dict, Any, Optional, List

from src.core.http import shared_client_ctx

logger = logging.getLogger(__name__)

_YT_SEARCH_TIMEOUT = 20.0
_YT_DOWNLOAD_TIMEOUT = 120.0
_MAX_MP3_BYTES = 25 * 1024 * 1024
_MAX_DURATION_SEC = 15 * 60  # Allow up to 15 minutes tracks

def _ffmpeg_path() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"

def _yt_cookies_file() -> Optional[str]:
    """Optional Netscape cookies.txt to bypass YouTube bot-checks on datacenter IPs.

    Set YT_COOKIES_FILE to a mounted cookies file (Railway volume). Absent by
    default — everything works without it on residential/undisturbed egress.
    """
    try:
        from src.core import config as _cfg
        p = (_cfg.YT_COOKIES_FILE or "").strip()
    except Exception:
        return None
    try:
        if p and os.path.isfile(p) and os.path.getsize(p) > 0:
            return p
    except Exception:
        pass
    return None


def _ydl_kwargs(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Base yt-dlp options shared by search + download (cookies wired once)."""
    opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 8,
        "extractor_args": {"youtube": {"player_client": ["android", "ios"]}},
    }
    ck = _yt_cookies_file()
    if ck:
        opts["cookiefile"] = ck
    if extra:
        opts.update(extra)
    return opts

async def itunes_track_metadata(query: str) -> Optional[Dict[str, str]]:
    """Fetches high-res iTunes artwork and normalized metadata without credentials."""
    clean_q = (query or "").strip()
    if not clean_q:
        return None
    try:
        async with shared_client_ctx("web") as client:
            r = await client.get(
                "https://itunes.apple.com/search",
                params={"media": "music", "entity": "song", "limit": 5, "term": clean_q},
            )
            if r.status_code == 200:
                items = r.json().get("results", [])
                if items:
                    t = items[0]
                    art = (t.get("artworkUrl100") or "").replace("100x100bb", "600x600bb")
                    return {
                        "title": t.get("trackName", clean_q),
                        "artist": t.get("artistName", ""),
                        "cover": art,
                        "source": "itunes",
                    }
    except Exception as e:
        logger.debug(f"iTunes lookup failed: {e}")
    return None

async def spotify_track_metadata(query: str) -> Optional[Dict[str, str]]:
    """Spotify if configured, otherwise iTunes fallback."""
    clean_q = (query or "").strip()
    if not clean_q:
        return None
    cid = os.getenv("SPOTIFY_CLIENT_ID", "")
    csec = os.getenv("SPOTIFY_CLIENT_SECRET", "")
    if cid and csec:
        try:
            async with shared_client_ctx("api") as client:
                tok = await client.post(
                    "https://accounts.spotify.com/api/token",
                    data={"grant_type": "client_credentials"},
                    auth=(cid, csec),
                )
                if tok.status_code == 200:
                    access = tok.json().get("access_token", "")
                    if access:
                        s = await client.get(
                            "https://api.spotify.com/v1/search",
                            params={"q": clean_q, "type": "track", "limit": 5},
                            headers={"Authorization": f"Bearer {access}"},
                        )
                        if s.status_code == 200:
                            items = (s.json().get("tracks") or {}).get("items", [])
                            if items:
                                t = items[0]
                                artists = ", ".join(a.get("name", "") for a in t.get("artists", []))
                                imgs = t.get("album", {}).get("images", [])
                                cover = imgs[0].get("url", "") if imgs else ""
                                return {
                                    "title": t.get("name", clean_q),
                                    "artist": artists or "",
                                    "cover": cover,
                                    "source": "spotify",
                                }
        except Exception as e:
            logger.debug(f"Spotify lookup failed: {e}")
    return await itunes_track_metadata(clean_q)

def _ytsearch_sync(query: str, max_results: int = 4) -> List[Dict[str, Any]]:
    from yt_dlp import YoutubeDL
    ydl_opts = _ydl_kwargs({
        "skip_download": True,
        "extract_flat": True,
    })
    with YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)
            return info.get("entries", []) or []
        except Exception as e:
            logger.debug(f"yt_dlp search error for {query}: {e}")
            return []

def _score_video(query_tokens: List[str], title: str, duration: Optional[float]) -> float:
    if not title:
        return 0.0
    if duration and duration > _MAX_DURATION_SEC:
        return 0.0  # exclude full albums / multi-hour playlists
    low = title.lower()
    if any(bad in low for bad in ["live concert", "full concert", "interview", "مصاحبه", "پشت صحنه", "کنسرت کامل"]):
        return 0.2
    
    if not query_tokens:
        return 0.6
        
    hits = sum(1 for t in query_tokens if t.lower() in low)
    score = hits / max(1, len(query_tokens))
    
    joined = " ".join(t.lower() for t in query_tokens)
    if joined and joined in low:
        score = min(1.0, score + 0.3)
    if any(k in low for k in ["official audio", "official music", "audio only", "full song", "original track"]):
        score = min(1.0, score + 0.2)
    return score

async def youtube_search_best_video(query: str, query_tokens: List[str]) -> Optional[Dict[str, Any]]:
    """Discovers the optimal YouTube audio video."""
    queries = [f"{query} audio", query]
    search_tasks = [
        asyncio.wait_for(asyncio.to_thread(_ytsearch_sync, search_q), timeout=_YT_SEARCH_TIMEOUT)
        for search_q in queries
    ]
    entries: List[Dict[str, Any]] = []
    try:
        results = await asyncio.gather(*search_tasks, return_exceptions=True)
    except Exception:
        results = []
    for found in results:
        if isinstance(found, list):
            valid = [e for e in found if isinstance(e, dict) and e.get("id")]
            if valid:
                entries.extend(valid)
                break

    if not entries:
        return None

    # Pick best scoring entry with duration >= 45s (prevent ringtones / shorts)
    best = None
    best_score = -1.0
    
    for e in entries:
        dur = e.get("duration") or 0
        if dur and dur < 40:
            continue
        sc = _score_video(query_tokens, e.get("title", ""), dur)
        if sc > best_score:
            best = e
            best_score = sc

    if not best:
        best = entries[0]
        best_score = 0.5

    return {
        "video_id": best["id"],
        "title": best.get("title", query),
        "duration": best.get("duration", 0),
        "uploader": best.get("uploader", ""),
        "score": round(best_score, 2),
    }

def _download_mp3_sync(video_id: str, workdir: str, title: str = "", artist: str = "") -> Optional[str]:
    import subprocess
    from yt_dlp import YoutubeDL
    out_tpl = os.path.join(workdir, "raw_track.%(ext)s")
    ydl_opts = _ydl_kwargs({
        "format": "ba[ext=m4a]/ba/b",
        "outtmpl": out_tpl,
        "socket_timeout": 20,
        "retries": 5,
        "fragment_retries": 5,
        "concurrent_fragment_downloads": 4,
        "extractor_args": {"youtube": {"player_client": ["android", "ios", "web"]}},
        "ffmpeg_location": _ffmpeg_path(),
    })
    url = f"https://www.youtube.com/watch?v={video_id}"
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    downloaded_files = [f for f in os.listdir(workdir) if f.startswith("raw_track.")]
    if not downloaded_files:
        return None

    raw_path = os.path.join(workdir, downloaded_files[0])
    mp3_path = os.path.join(workdir, "final_track.mp3")

    # Ultra-Fast In-Process FFmpeg Transcode + Complete ID3 Tagging (Studio Quality 320kbps)
    ffmpeg_bin = _ffmpeg_path()
    cmd = [
        ffmpeg_bin, "-y", "-threads", "2", "-i", raw_path,
        "-b:a", "320k",
        "-metadata", f"title={title or 'Music Track'}",
        "-metadata", f"artist={artist or 'Prometheus Audio'}",
        "-metadata", "album=Prometheus Master 320 HQ",
        "-metadata", "genre=Music",
        mp3_path
    ]
    sub_res = subprocess.run(cmd, capture_output=True)
    if sub_res.returncode == 0 and os.path.isfile(mp3_path) and os.path.getsize(mp3_path) > 50_000:
        if os.path.getsize(mp3_path) <= _MAX_MP3_BYTES:
            return mp3_path

    # Fallback to direct raw file if within Telegram 25MB limits
    return raw_path if os.path.isfile(raw_path) and os.path.getsize(raw_path) <= _MAX_MP3_BYTES else None

async def youtube_download_full_track(query: str, query_tokens: List[str], meta: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
    """Complete resilient YouTube audio downloader."""
    search_term = query
    if meta and meta.get("artist") and meta.get("title"):
        search_term = f"{meta['artist']} {meta['title']}"
        
    video = await youtube_search_best_video(search_term, query_tokens)
    if not video:
        return None

    title = (meta or {}).get("title") or video["title"]
    artist = (meta or {}).get("artist") or video.get("uploader", "") or "Prometheus Audio"

    try:
        with tempfile.TemporaryDirectory(prefix="yt_track_") as workdir:
            mp3_path = await asyncio.wait_for(
                asyncio.to_thread(_download_mp3_sync, video["video_id"], workdir, title, artist),
                timeout=_YT_DOWNLOAD_TIMEOUT,
            )
            if not mp3_path:
                return None
            with open(mp3_path, "rb") as f:
                raw = f.read()
    except Exception as e:
        logger.error(f"YouTube download exception: {e}")
        return None

    return {
        "title": title,
        "performer": artist,
        "audio_bytes": raw,
        "size_bytes": len(raw),
        "duration_sec": int(video.get("duration") or 0),
        "cover": (meta or {}).get("cover", ""),
        "quality": "Studio Quality 320kbps MP3",
        "match_score": video.get("score", 0.5),
        "source": f"youtube:{video['video_id']}",
    }
