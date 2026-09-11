# Прометей (Prometheus) — обычный Telegram-бот, который старается быть полезным
> Telegram-бот, подключённый к языковой модели, с набором полезных инструментов (курсы валют, золота и крипты, погода, поиск в интернете, музыка, файлы, расчёты). Вместо догадок идёт к инструментам; если что-то сломано — так и говорит. Чудес тут нет.

<p align="center">
  <a href="README.md">🇮🇷 فارسی</a> ·
  <a href="README.en.md">🇬🇧 English</a> ·
  <a href="README.ru.md">🇷🇺 Русский</a> ·
  <a href="README.es.md">🇪🇸 Español</a> ·
  <a href="README.fr.md">🇫🇷 Français</a>
</p>

---

## 📖 Содержание
- [Обзор](#обзор)
- [Структура проекта](#структура-проекта)
- [Как это работает](#как-это-работает)
- [Получение API-ключей](#получение-api-ключей)
  - [1. Токен Telegram-бота (TELEGRAM_BOT_TOKEN)](#1-токен-telegram-бота-telegram_bot_token)
  - [2. Числовой ID админа (ADMIN_ID)](#2-числовой-id-админа-admin_id)
  - [3. Ключ и адрес ИИ (ROUTER_API_KEY и ROUTER_BASE_URL)](#3-ключ-и-адрес-ии-router_api_key-и-router_base_url)
  - [4. Аккаунт Cloudflare, D1 и KV](#4-аккаунт-cloudflare-d1-и-kv)
  - [5. Ключ веб-поиска Tavily (TAVILY_API_KEY)](#5-ключ-веб-поиска-tavily-tavily_api_key)
  - [6. Ключ курсов AllRatesToday (ALLRATESTODAY_API_KEY)](#6-ключ-курсов-allratestoday-allratestoday_api_key)
  - [7. Токен GitHub (GITHUB_TOKEN)](#7-токен-github-github_token)
  - [8. Ключи Spotify (SPOTIFY_CLIENT_ID и SPOTIFY_CLIENT_SECRET)](#8-ключи-spotify-spotify_client_id-и-spotify_client_secret)
  - [9. Облачная песочница E2B (E2B_API_KEY)](#9-облачная-песочница-e2b-e2b_api_key)
  - [10. Куки YouTube (YT_COOKIES_FILE)](#10-куки-youtube-yt_cookies_file)
- [Переменные окружения](#переменные-окружения)
- [Пошаговая установка](#пошаговая-установка)
- [Деплой в облаке](#деплой-в-облаке)
- [Матрица инструментов](#матрица-инструментов)
- [Модель безопасности](#модель-безопасности)
- [Тестирование](#тестирование)
- [Лицензия и участие](#лицензия-и-участие)

---

## Обзор

**Прометей** — open-source Telegram-бот, который подключает языковую модель к реальным инструментам. Идея простая, и он просто её выполняет:

- **Не гадай — проверь:** всё, чему нужны живые данные (цены, погода, новости, статус сайтов), берётся напрямую из инструментов, а не из памяти модели. Если инструмент недоступен, бот так и говорит. Всё.
- **Ключ нужен не для всего:** обязательны только токен Telegram, ID админа и один OpenAI-совместимый ключ модели. Остальное (Tavily, Cloudflare, GitHub, Spotify, E2B) опционально — без них тоже работает, просто на бесплатных запасных вариантах.
- **В группах не лезет без спроса:** отвечает только при обращении (ответ на сообщение, упоминание или слово «Прометей»). Остальное тихо архивируется.
- **Код локально не выполняется:** Python сначала идёт в облачную песочницу E2B (если есть ключ), иначе — в изолированную локальную. Деструктивный shell не выполняется никогда, даже по приказу админа.
- **Не только персидский:** определяет язык Telegram каждого пользователя и отвечает на нём (английский, русский, испанский, французский...); выводы инструментов при необходимости переводятся.

---

## Структура проекта

Репозиторий организован раздельно, модульно и стандартно:

```text
prometheusopenbot/
├── bot.py                     # Точка входа: Telegram-сервер + запуск бота
├── requirements.txt           # Зависимости Python
├── .env.example               # Шаблон переменных окружения
├── nixpacks.toml / railway.json # Конфиг облачного деплоя (Railway / Nixpacks)
│
├── src/                       # Ядро
│   ├── core/                  # База данных, ИИ, HTTP-клиент и конфиг
│   │   ├── ai_service.py      # Единый LLM-сервис, промпты, зрение, инструменты
│   │   ├── config.py          # Загрузка env, политика безопасности, системный промпт
│   │   ├── database.py        # Многоуровневое облачное хранилище (Cloudflare D1 и KV)
│   │   ├── http.py            # Управление асинхронными HTTP-сессиями
│   │   ├── i18n.py            # Определение языка пользователя + двуязычные строки
│   │   └── security.py        # Проверка команд, rate limit, защита от вторжений
│   ├── tools/                 # ~90 точечных инструментов (лишнее удалено)
│   │   ├── admin/             # Управление группами и модерация
│   │   ├── database/          # Облачные запросы и взаимодействие
│   │   ├── dev/               # Dev-инструменты: GitHub, Reddit, StackOverflow
│   │   ├── files/             # Генерация/извлечение документов (PDF, Word, Excel, CSV)
│   │   ├── financial/         # Живые котировки крипты, золота, валют и форекса
│   │   ├── github/            # Работа с репозиториями и ишью GitHub
│   │   ├── internal/          # Оптимизаторы памяти, сжатие промпта, кэширование
│   │   ├── media/             # Загрузка музыки, метаданные, тексты песен, войсы
│   │   ├── scientific/        # Математика, статистика, конвертер единиц
│   │   ├── system/            # Телеметрия сервера, песочница E2B, безопасный shell админа
│   │   │   └── e2b_sandbox.py   # Опциональные облачные запуски E2B (локальный fallback)
│   │   ├── web_network/       # Живые поисковики (Tavily, Bing, Brave, Digikala)
│   │   └── registry.py        # Авторегистрация схем инструментов + диспетчер
│   ├── ui/                    # Внутричатовая админ-панель Telegram (кнопки)
│   └── utils/                 # Форматирование Telegram, чистка выводов, типографика
│
├── tests/                     # Тесты
│   ├── test_master.py         # Сквозная проверка системы и инструментов
│   ├── test_e2b.py            # Тест песочницы E2B (офлайн-путь без ключа)
│   ├── test_i18n.py           # Двуязычие, EN/FA-триггеры, fallback перевода
│   ├── run_test_battery.py    # Симуляция поведения бота, БД и стресс
│   ├── test_stress.py         # Устойчивость инструментов под нагрузкой
│   ├── run_rigorous_tests.py  # Проверка живых веб/сетевых инструментов
│   ├── test_financial_scientific_suite.py # Тесты финансов и математики
│   ├── test_media_files_runner.py        # Тесты документов/медиа/картинок
│   └── test_rigorous_battery.py          # Граничные случаи и странные вводы
│
└── assets/                    # Статика и персидские шрифты
```

---

## Как это работает

Бот работает на современном многослойном конвейере:

```text
┌─────────────────────────────────────────────────────────────┐
│                    Пользователь в Telegram                  │
└──────────────────────────────┬──────────────────────────────┘
                                │ (текст, войс, ответ, файл)
                                ▼
┌─────────────────────────────────────────────────────────────┐
│                 Telegram Dispatcher Engine                  │
│        (аутентификация, rate limit, анализ доступа)          │
└──────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────┐
│                   3-Tier Memory Architecture                │
│  • L1 Cache: сверхбыстрая локальная RAM для курсов/ответов  │
│  • Cloudflare KV: распределённая облачная key/value-память  │
│  • Cloudflare D1: SQL-база с полнотекстовым поиском FTS5    │
└──────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────┐
│             Autonomous LLM Multi-Step Reasoner              │
│     (многошаговое рассуждение + параллельные вызовы)        │
└──────────────────────────────┬──────────────────────────────┘
                                │ (Parallel Tool Execution)
                                ▼
┌─────────────────────────────────────────────────────────────┐
│                  Tool Matrix (~90 инструментов)             │
│  • Финансы (Binance, Nobitex, золото, монеты, Tether, FX)   │
│  • Веб и новости (Tavily AI, скраперы, Digikala, погода)     │
│  • Медиа и звук (музыка 320, Whisper STT, QR, Telegraph)    │
│  • Управление и система (песочница Python, логи, глобал-бан) │
└──────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────┐
│               Telegram HTML & Shield Formatter              │
│     (автомаскировка [SECRET] + стандартное оформление)      │
└──────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────┐
│                      Ответ в Telegram                       │
└─────────────────────────────────────────────────────────────┘
```

### 1. Параллельный вызов инструментов
Сообщение пользователя сначала разбирается на независимые намерения. Если в одном сообщении несколько просьб (например, цена биткоина, погода в Тегеране и точное время сразу), бот находит нужные инструменты и вызывает их параллельно.

### 2. Трёхуровневое хранилище
- **Уровень 1 (L1 In-Memory Cache):** очень быстрый RAM-кэш с TTL для живых данных (курсы валют/крипты).
- **Уровень 2 (Cloudflare Workers KV):** распределённая облачная key/value-память для сессий, долгого кэша и динамических настроек.
- **Уровень 3 (Cloudflare D1 SQL):** serverless реляционная БД с FTS5 для полной истории чатов, логов и управления участниками.

### 3. Изоляция команд админа
Чувствительные инструменты (выполнение Python, команды терминала, управление группами, глобал-бан) закрыты проверкой числового ID админа (`ADMIN_ID`). Обойти это промпт-инъекцией или самозванством нельзя.

---

## Получение API-ключей

Для полного функционала нужны несколько ключей. Часть **обязательна** (для первого запуска), часть **опциональна** (для боковых инструментов).

### 1. Токен Telegram-бота (TELEGRAM_BOT_TOKEN) — [обязательно 🔴]
- **Зачем:** личность бота для связи с серверами Telegram и приёма/отправки сообщений.
- **Как получить:**
  1. Откройте [@BotFather](https://t.me/BotFather) в Telegram.
  2. Отправьте `/newbot`.
  3. Выберите отображаемое имя, затем username (должен кончаться на `bot`).
  4. BotFather выдаст токен вида `1234567890:ABCdefGhIJKlmNoPQRsTUVwxyZ`.
  5. Для групп: выполните `/setprivacy` у BotFather, выберите бота и поставьте `Disable`, чтобы он читал сообщения групп.

### 2. Числовой ID админа (ADMIN_ID) — [обязательно 🔴]
- **Зачем:** личность владельца/суперадмина для панели, выполнения Python, банов и управления группами.
- **Как получить:**
  1. Откройте [@userinfobot](https://t.me/userinfobot) или [@JsonDumpBot](https://t.me/JsonDumpBot).
  2. Нажмите start — получите числовой ID (например, `123456789`).
  3. Положите его в `ADMIN_ID`.

### 3. Ключ и адрес ИИ (ROUTER_API_KEY и ROUTER_BASE_URL) — [обязательно 🔴]
- **Зачем:** мозг бота для рассуждений, понимания намерений и вызовов инструментов (Function Calling). Подходит любой провайдер, совместимый с **OpenAI API**:
- **Варианты:**
  - **Официальный OpenAI:**
    - [platform.openai.com](https://platform.openai.com/api-keys) → новый ключ (`sk-...`)
    - `ROUTER_BASE_URL=https://api.openai.com/v1`, `ROUTER_MODEL=gpt-4o-mini`
  - **OpenRouter (куча моделей в одном месте):**
    - [openrouter.ai](https://openrouter.ai/keys) → API key
    - `ROUTER_BASE_URL=https://openrouter.ai/api/v1`, любая модель (`google/gemini-flash-1.5`, `openai/gpt-4o-mini`)
  - **DeepSeek:**
    - [platform.deepseek.com](https://platform.deepseek.com/api_keys) → ключ, `ROUTER_BASE_URL=https://api.deepseek.com/v1`, `ROUTER_MODEL=deepseek-chat`
  - **Groq (очень быстрый):**
    - [console.groq.com](https://console.groq.com/keys) → бесплатный ключ, `ROUTER_BASE_URL=https://api.groq.com/openai/v1`, `ROUTER_MODEL=llama-3.3-70b-versatile`

### 4. Аккаунт Cloudflare, D1 и KV — [опционально 🟡]
- **Зачем:** вечная история чатов, полнотекстовый поиск по старым сообщениям, бан-листы, облачный кэш. Без этого бот работает на RAM (L1).
- **Как получить бесплатно:**
  1. Зарегистрируйтесь на [cloudflare.com](https://cloudflare.com).
  2. **Account ID:** откройте Workers & D1 в дашборде; 32-символьный ID — в правой колонке.
  3. **API Token:** *My Profile > API Tokens > Create Token*, шаблон *Edit Cloudflare Workers*.
  4. **База D1:** *Workers & Pages > D1 SQL Database*, создайте базу (например, `prometheus-db`), UUID — в `CLOUDFLARE_D1_ID`.
  5. **KV:** *Workers & Pages > KV*, создайте namespace (например, `prometheus-kv`), ID — в `CLOUDFLARE_KV_ID`.

### 5. Ключ веб-поиска Tavily (TAVILY_API_KEY) — [опционально ⚪]
- **Зачем:** быстрый ИИ-поиск для свежих новостей, сравнений версий, событий сегодняшнего дня.
- **Как получить бесплатно:**
  1. [tavily.com](https://tavily.com), регистрация (бесплатно: 1000 поисков/мес, без карты).
  2. Скопируйте ключ (начинается с `tvly-`) в `TAVILY_API_KEY`.

### 6. Ключ курсов AllRatesToday (ALLRATESTODAY_API_KEY) — [опционально ⚪]
- **Зачем:** прямые живые курсы фиата (USD, EUR, AED...) и цен золота/монет Ирана.
- **Как получить:**
  1. [allratestoday.com](https://allratestoday.com), регистрация, ключ `art_live_...`.
  2. *(Без него бот сам переключается на живые веб-скраперы.)*

### 7. Токен GitHub (GITHUB_TOKEN) — [опционально ⚪]
- **Зачем:** высокие лимиты для 12 GitHub-инструментов (поиск кода/коммитов/ишью/релизов).
- **Как получить бесплатно:**
  1. [github.com/settings/tokens](https://github.com/settings/tokens).
  2. *Generate new token (classic)*, галочка `public_repo`, токен `ghp_...` — в `GITHUB_TOKEN`.

### 8. Ключи Spotify (SPOTIFY_CLIENT_ID и SPOTIFY_CLIENT_SECRET) — [опционально ⚪]
- **Зачем:** официальные обложки и точные метаданные иностранных треков.
- **Как получить бесплатно:**
  1. [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard).
  2. Создайте приложение, скопируйте `Client ID` и `Client Secret`.
  3. *(Без них — iTunes API и метаданные по умолчанию.)*

### 9. Облачная песочница E2B (E2B_API_KEY) — [опционально ⚪]
- **Зачем:** изолированное выполнение Python/JavaScript/shell в облаке, ноль нагрузки на сервер. Без неё — локальная песочница.
- **Как получить бесплатно:**
  1. Регистрация на [e2b.dev](https://e2b.dev).
  2. Ключ из [дашборда E2B](https://e2b.dev/dashboard?tab=keys) (начинается с `e2b_`).
  3. Положите в `E2B_API_KEY`. (Опционально: `E2B_TEMPLATE` для своего шаблона, `E2B_TIMEOUT_SEC` для лимита времени.)

### 10. Куки YouTube (YT_COOKIES_FILE) — [опционально ⚪]
- **Зачем:** нужно, только если YouTube считает IP сервера ботом и загрузка музыки падает с `Sign in to confirm you're not a bot`. Иначе оставьте пустым.
- **Как получить:**
  1. Выгрузите Netscape-файл куки с youtube.com расширением браузера (например, Get cookies.txt).
  2. Положите файл рядом с ботом (на Railway: Volume) и укажите путь в `YT_COOKIES_FILE`.

---

## Переменные окружения

Создайте файл `.env` в корне проекта и заполните по гайду выше:

| Переменная | Тип | По умолчанию | Назначение |
| :--- | :---: | :---: | :--- |
| `TELEGRAM_BOT_TOKEN` | обязательно 🔴 | - | Токен бота от BotFather |
| `ADMIN_ID` | обязательно 🔴 | `0` | Числовой ID суперадмина в Telegram |
| `ROUTER_BASE_URL` | обязательно 🔴 | `https://api.openai.com/v1` | OpenAI-совместимый V1-эндпоинт |
| `ROUTER_API_KEY` | обязательно 🔴 | - | Ключ авторизации модели |
| `ROUTER_MODEL` | опционально ⚪ | `gpt-4o-mini` | Имя модели (`gpt-4o-mini`, `deepseek-chat`...) |
| `CLOUDFLARE_ACCOUNT_ID` | опционально ⚪ | `""` | 32-символьный ID аккаунта Cloudflare |
| `CLOUDFLARE_API_TOKEN` | опционально ⚪ | `""` | Токен Cloudflare с правами D1 + KV |
| `CLOUDFLARE_D1_ID` | опционально ⚪ | `""` | UUID базы D1 |
| `CLOUDFLARE_KV_ID` | опционально ⚪ | `""` | ID KV-неймспейса |
| `TAVILY_API_KEY` | опционально ⚪ | `""` | Ключ умного поиска Tavily AI |
| `ALLRATESTODAY_API_KEY` | опционально ⚪ | `""` | Ключ живых курсов золота/валют |
| `GITHUB_TOKEN` | опционально ⚪ | `""` | Персональный токен GitHub (лимиты) |
| `SPOTIFY_CLIENT_ID` | опционально ⚪ | `""` | Spotify Client ID |
| `SPOTIFY_CLIENT_SECRET` | опционально ⚪ | `""` | Spotify Client Secret |
| `E2B_API_KEY` | опционально ⚪ | `""` | Облачная песочница E2B (иначе: локально) |
| `E2B_TEMPLATE` | опционально ⚪ | `""` | Свой шаблон E2B (пусто = по умолчанию) |
| `E2B_TIMEOUT_SEC` | опционально ⚪ | `30` | Лимит выполнения E2B в секундах (5–120) |
| `YT_COOKIES_FILE` | опционально ⚪ | `""` | Файл куки YouTube (только если загрузки упираются в бот-чек) |
| `ENABLE_FINANCIAL_SYNC` | опционально ⚪ | `1` | Фоновый синк курсов (`0` = выкл, экономит KV-квоту) |

---

## Пошаговая установка

### 1. Клонирование исходников
```bash
git clone https://github.com/zaryamyn273-crypto/prometheusopenbot.git
cd prometheusopenbot
```

### 2. Виртуальное окружение Python
```bash
python3 -m venv venv
# Linux / macOS:
source venv/bin/activate
# Windows:
venv\Scripts\activate
```

### 3. Установка зависимостей
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Конфиг
```bash
cp .env.example .env
nano .env   # вставьте ключи из гайда выше
```

### 5. Запуск бота
```bash
python bot.py
```
После успешного соединения с Telegram бот выставит список команд и напечатает сообщение готовности в консоль.

---

## Деплой в облаке

### Railway:
1. Сделайте Fork или Push репозитория в свой GitHub.
2. Откройте дашборд [Railway.app](https://railway.app), **New Project > Deploy from GitHub repo**.
3. Выберите репозиторий.
4. Во вкладке **Variables** добавьте переменные из `.env`.
5. Благодаря `nixpacks.toml` + `railway.json` Railway сам настроит Python 3.12 и `ffmpeg` и запустит проект.

### Linux через Systemd:
Создайте сервис `/etc/systemd/system/prometheus.service`:
```ini
[Unit]
Description=Prometheus Telegram Super Agent
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/path/to/prometheusopenbot
ExecStart=/path/to/prometheusopenbot/venv/bin/python bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```
Включите и запустите:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now prometheus
```

---

## Матрица инструментов

~**90 зарегистрированных инструментов**, у каждого одна чёткая задача. Удалены за ненадобностью/дубли: `darkweb_search`, `internal_resilient_fallback_search`, `autonomous_system_health_check`, `bot_rate_guard`, `bot_output_compactor`, `bot_prompt_token_saver`, `bot_alias_resolver`, `bot_d1_remember`, `bot_d1_recall`.

1. **📊 Финансы (`src/tools/financial/`):**
   - Живые цены крипты с Binance и Nobitex (`get_price`, `get_crypto_overview`).
   - Живые цены золота/монет и спрэд (`get_gold_and_coin_price`).
   - Tether, USD, EUR, AED и кроссы форекса (`get_dollar_price`, `get_fiat_overview`, `get_global_forex_rates`).

2. **🌐 Веб и сеть (`src/tools/web_network/`):**
   - Умный веб-поиск: Tavily AI + комбинированные движки (`tavily_search`, `web_search`, `deep_search_and_read`).
   - Живые новости (`live_news`).
   - Товары/цены Digikala (`digikala_search`).
   - Сеть: `check_website_status`, `resolve_dns`, `check_ssl_certificate`, `get_ip_info`.
   - Погода с влажностью и ветром (`get_weather`).

3. **🎵 Медиа и звук (`src/tools/media/`):**
   - Поиск/загрузка музыки в оригинальном 320kbps с тегами и обложкой (`download_music_track`).
   - Тексты песен и timed `.lrc` (`get_song_lyrics`).
   - Войс/аудио в текст через Whisper (`transcribe_audio_tool`).
   - QR-коды (`generate_qr_code_tool`).
   - Публикация лонгридов через Telegraph Instant View (`publish_telegraph_article`).

4. **🔬 Наука и общее (`src/tools/scientific/`):**
   - Продвинутый калькулятор (`calculate_math_expression`).
   - Статистика (`statistics_summary`).
   - Официальное время/календарь (`get_current_datetime_info`).
   - Конвертер единиц и хэши (`convert_units`, `generate_hash_digest`, ...).

5. **🛡️ Система и админ (`src/tools/admin/` и `src/tools/system/`):**
   - Песочница Python для суперадмина (`execute_python_code`).
   - Изолированные облачные запуски через E2B (`e2b_run_code`, `e2b_run_command`); без ключа — локальный fallback.
   - Телеметрия сервера (`admin_system_diagnostics`).
   - Глобал-бан/мьют на D1 (`ban_user_tool`, `mute_user_tool`).
   - Управление группами и экстренный выход (`list_joined_groups_tool`, `leave_group_by_admin_tool`).

6. **🐙 GitHub (`src/tools/github/`):**
   - Поиск репозиториев/ишью/коммитов/релизов и анализ репозиториев.

---

## Модель безопасности

- **Автомаскировка секретов:** выводы инструментов и логи проходят фильтры известных ключей + regex; чувствительное заменяется на `[SECRET]`, токены не утекают в чаты.
- **Разделение ЛС и групп:** управляющие команды в личке — только для identity `ADMIN_ID`.
- **Защита от промпт-инъекций:** логика на Python + системный промпт устойчивы к подмене роли и джейлбрейкам.

---

## Тестирование

Перед деплоем — проверка модулей и инструментов:

```bash
# аудит реестра + офлайн-инструментов
python tests/test_master.py

# двуязычие + песочница (офлайн, без ключей)
python tests/test_i18n.py
python tests/test_e2b.py

# многомерная оценка + стресс
python tests/run_test_battery.py

# песочница E2B (без ключа/пакета живой прогон скипается)
python tests/test_e2b.py
```

---

## Лицензия и участие

Open-source проект: чистая масштабируемая агентная архитектура для сообщества. Баг-репорты и pull request'ы приветствуются.
