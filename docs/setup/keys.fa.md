# راهنمای جامع تهیه کلیدها و پیش‌نیازها

برای اجرا فقط **۳ متغیر** لازم است: `TELEGRAM_BOT_TOKEN`، `ADMIN_ID`، `ROUTER_API_KEY`. بقیه اختیاری‌اند و بدون آن‌ها هم ربات کار می‌کند.

## ۱. توکن ربات تلگرام (TELEGRAM_BOT_TOKEN) — [الزامی 🔴]
- **کاربرد:** شناسه اصلی ربات تلگرام برای اتصال به سرورهای تلگرام و دریافت/ارسال پیام‌ها.
- **نحوه تهیه:**
  1. در تلگرام وارد ربات رسمی [@BotFather](https://t.me/BotFather) شوید.
  2. دستور `/newbot` را ارسال کنید.
  3. یک نام نمایشی (Name) و سپس یک نام کاربری (Username که به `bot` ختم شود) انتخاب نمایید.
  4. بات‌فادر به شما یک توکن شبیه به این می‌دهد: `1234567890:ABCdefGhIJKlmNoPQRsTUVwxyZ`
  5. برای گروه‌ها، دستور `/setprivacy` را در BotFather زده، ربات خود را انتخاب کرده و آن را `Disable` کنید تا ربات بتواند پیام‌های گروه را جهت پاسخ‌دهی پردازش کند.

## ۲. شناسه عددی ادمین (ADMIN_ID) — [الزامی 🔴]
- **کاربرد:** تعیین هویت مالک و فرمانده ارشد ربات جهت دسترسی به پنل مدیریت، ابزار اجرای کد پایتون، مسدودسازی کاربران و مدیریت گروه‌ها.
- **نحوه تهیه:**
  1. در تلگرام وارد ربات [@userinfobot](https://t.me/userinfobot) یا [@JsonDumpBot](https://t.me/JsonDumpBot) شوید.
  2. پیام استارت را بزنید تا شناسه عددی خود را (یک عدد چند رقمی مثل `123456789`) دریافت کنید.
  3. این عدد را در متغیر `ADMIN_ID` قرار دهید.

## ۳. کلید و آدرس هوش مصنوعی (ROUTER_API_KEY & ROUTER_BASE_URL) — [الزامی 🔴]
- **کاربرد:** مغز متفکر ربات برای استدلال، درک نیت کاربر و فراخوانی ابزارها (Function Calling). این سیستم از استاندارد رسمی **OpenAI API** پشتیبانی می‌کند:
- **گزینه‌ها:**
  - **OpenAI رسمی:** [platform.openai.com](https://platform.openai.com/api-keys) → کلید `sk-...` → `ROUTER_BASE_URL=https://api.openai.com/v1` و `ROUTER_MODEL=gpt-4o-mini`
  - **OpenRouter:** [openrouter.ai](https://openrouter.ai/keys) → `ROUTER_BASE_URL=https://openrouter.ai/api/v1`
  - **DeepSeek:** [platform.deepseek.com](https://platform.deepseek.com/api_keys) → `ROUTER_BASE_URL=https://api.deepseek.com/v1` و `ROUTER_MODEL=deepseek-chat`
  - **Groq (رایگان و سریع):** [console.groq.com](https://console.groq.com/keys) → `ROUTER_BASE_URL=https://api.groq.com/openai/v1` و `ROUTER_MODEL=llama-3.3-70b-versatile`

## ۴. حساب و دیتابیس ابری کلودفلر (Cloudflare D1 & KV) — [اختیاری 🟡]
- **کاربرد:** نگهداری دائمی تاریخچه گفتگوها، جستجوی پیام‌های قبلی، لیست مسدودشده‌ها و کش ابری. بدون آن ربات روی رم (L1) کار می‌کند.
- **نحوه تهیه رایگان:**
  1. حساب در [cloudflare.com](https://cloudflare.com).
  2. **Account ID** (رشته ۳۲ کاراکتری، ستون راست داشبورد Workers & D1).
  3. **API Token:** با تمپلیت *Edit Cloudflare Workers* و دسترسی حداقلی (فقط D1 و KV همین دو منبع).
  4. دیتابیس D1 بسازید (مثلاً `prometheus-db`) → UUID در `CLOUDFLARE_D1_ID`.
  5. فضای KV بسازید (مثلاً `prometheus-kv`) → ID در `CLOUDFLARE_KV_ID`.

## ۵. کلید سرچ Tavily (TAVILY_API_KEY) — [اختیاری ⚪]
- ثبت نام در [tavily.com](https://tavily.com) (رایگان، بدون کارت) → کلید `tvly-...`.

## ۶. کلید AllRatesToday (ALLRATESTODAY_API_KEY) — [اختیاری ⚪]
- ثبت نام در [allratestoday.com](https://allratestoday.com) → کلید `art_live_...`. بدون آن، fallback خودکار به اسکرپرهای زنده.

## ۷. توکن گیت‌هاب (GITHUB_TOKEN) — [اختیاری ⚪]
- [github.com/settings/tokens](https://github.com/settings/tokens) → *Generate new token (classic)* با دسترسی `public_repo` (همین کافی است).

## ۸. کلیدهای اسپاتیفای — [اختیاری ⚪]
- [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) → ساخت App → `Client ID` و `Client Secret`. بدون آن از iTunes استفاده می‌شود.

## ۹. سندباکس ابری E2B (E2B_API_KEY) — [اختیاری ⚪]
- **کاربرد:** تنها جایی که کدهای نوشته‌شده توسط AI اجرا می‌شوند. بدون آن ابزار اجرای کد **غیرفعال** است (فال‌بک لوکال عمداً وجود ندارد — [SECURITY.md](../../SECURITY.md)).
- ثبت نام در [e2b.dev](https://e2b.dev) → کلید از [داشبورد](https://e2b.dev/dashboard?tab=keys) (`e2b_...`).

## ۱۰. کوکی یوتیوب (YT_COOKIES_FILE) — [اختیاری ⚪]
- فقط وقتی لازم است که یوتیوب IP سرور را بات تشخیص دهد (`Sign in to confirm you're not a bot`). خروجی Netscape افزونه Get cookies.txt را mount کنید و مسیرش را ست کنید.

## جدول متغیرها

| نام متغیر | نوع | پیش‌فرض | کاربرد |
| :--- | :---: | :---: | :--- |
| `TELEGRAM_BOT_TOKEN` | الزامی 🔴 | - | توکن ربات از BotFather |
| `ADMIN_ID` | الزامی 🔴 | - | شناسه عددی ادمین ارشد |
| `ROUTER_BASE_URL` | الزامی 🔴 | `https://api.openai.com/v1` | اندپوینت سازگار با OpenAI V1 |
| `ROUTER_API_KEY` | الزامی 🔴 | - | کلید مدل هوش مصنوعی |
| `ROUTER_MODEL` | اختیاری ⚪ | `gpt-4o-mini` | نام مدل |
| `DAILY_USER_LIMIT` | اختیاری ⚪ | `40` | پاسخ کامل AI روزانه هر کاربر (ریست خودکار UTC؛ ادمین نامحدود) |
| `CLOUDFLARE_ACCOUNT_ID` | اختیاری ⚪ | `""` | آیدی ۳۲ کاراکتری اکانت |
| `CLOUDFLARE_API_TOKEN` | اختیاری ⚪ | `""` | توکن با دسترسی D1 و KV |
| `CLOUDFLARE_D1_ID` | اختیاری ⚪ | `""` | UUID دیتابیس D1 |
| `CLOUDFLARE_KV_ID` | اختیاری ⚪ | `""` | آیدی فضای KV |
| `TAVILY_API_KEY` | اختیاری ⚪ | `""` | کلید سرچ Tavily |
| `TAVILY_API_KEYS` | اختیاری ⚪ | `""` | کلیدهای اضافه با کاما (چرخشی) |
| `ALLRATESTODAY_API_KEY` | اختیاری ⚪ | `""` | کلید نرخ طلا و ارز |
| `GITHUB_TOKEN` | اختیاری ⚪ | `""` | توکن گیت‌هاب |
| `SPOTIFY_CLIENT_ID` | اختیاری ⚪ | `""` | شناسه اسپاتیفای |
| `SPOTIFY_CLIENT_SECRET` | اختیاری ⚪ | `""` | سکرت اسپاتیفای |
| `E2B_API_KEY` | اختیاری ⚪ | `""` | سندباکس E2B (بدون آن: اجرای کد غیرفعال) |
| `E2B_TEMPLATE` | اختیاری ⚪ | `""` | تمپلیت سفارشی (خالی = پیش‌فرض) |
| `E2B_TIMEOUT_SEC` | اختیاری ⚪ | `30` | سقف اجرا (۵ تا ۱۲۰ ثانیه) |
| `YT_COOKIES_FILE` | اختیاری ⚪ | `""` | فایل کوکی یوتیوب |
| `ENABLE_FINANCIAL_SYNC` | اختیاری ⚪ | `1` | سینک پس‌زمینه قیمت‌ها (`0` = خاموش) |
| `FINANCIAL_SYNC_INTERVAL_SEC` | اختیاری ⚪ | `900` | فاصله سینک (حداقل ۳۰۰ ثانیه) |
| `PORT` | اختیاری ⚪ | `8080` | پورت پروب سلامت `/healthz` |
