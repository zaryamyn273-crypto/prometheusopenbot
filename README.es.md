# Prometheus — un bot de Telegram normal que intenta ser útil
> Un bot de Telegram conectado a un modelo de lenguaje, con varias herramientas útiles (precios de divisas, oro y cripto, clima, búsqueda web, música, archivos, cálculos). En lugar de adivinar va a las herramientas; si algo está roto lo dice. Aquí no hay milagros.

<p align="center">
  <a href="README.md">🇮🇷 فارسی</a> ·
  <a href="README.en.md">🇬🇧 English</a> ·
  <a href="README.ru.md">🇷🇺 Русский</a> ·
  <a href="README.es.md">🇪🇸 Español</a> ·
  <a href="README.fr.md">🇫🇷 Français</a>
</p>

---

## 📖 Índice
- [Descripción general](#descripción-general)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Cómo funciona](#cómo-funciona)
- [Obtención de claves API](#obtención-de-claves-api)
  - [1. Token del bot de Telegram (TELEGRAM_BOT_TOKEN)](#1-token-del-bot-de-telegram-telegram_bot_token)
  - [2. ID numérico de admin (ADMIN_ID)](#2-id-numérico-de-admin-admin_id)
  - [3. Clave y endpoint de IA (ROUTER_API_KEY y ROUTER_BASE_URL)](#3-clave-y-endpoint-de-ia-router_api_key-y-router_base_url)
  - [4. Cuenta de Cloudflare, D1 y KV](#4-cuenta-de-cloudflare-d1-y-kv)
  - [5. Clave de búsqueda Tavily (TAVILY_API_KEY)](#5-clave-de-búsqueda-tavily-tavily_api_key)
  - [6. Clave de AllRatesToday (ALLRATESTODAY_API_KEY)](#6-clave-de-allratestoday-allratestoday_api_key)
  - [7. Token de GitHub (GITHUB_TOKEN)](#7-token-de-github-github_token)
  - [8. Claves de Spotify (SPOTIFY_CLIENT_ID y SPOTIFY_CLIENT_SECRET)](#8-claves-de-spotify-spotify_client_id-y-spotify_client_secret)
  - [9. Sandbox en la nube E2B (E2B_API_KEY)](#9-sandbox-en-la-nube-e2b-e2b_api_key)
- [Variables de entorno](#variables-de-entorno)
- [Instalación paso a paso](#instalación-paso-a-paso)
- [Despliegue en la nube](#despliegue-en-la-nube)
- [Matriz de herramientas](#matriz-de-herramientas)
- [Modelo de seguridad](#modelo-de-seguridad)
- [Pruebas](#pruebas)
- [Licencia y contribuciones](#licencia-y-contribuciones)

---

## Descripción general

**Prometheus** es un bot open-source de Telegram que conecta un modelo de lenguaje a herramientas reales. La idea es simple, y eso es lo que hace:

- **No adivines, ve a mirar:** todo lo que necesita datos en vivo (precios, clima, noticias, estado de sitios) viene directo de una herramienta, no de la memoria del modelo. Si una herramienta falla, el bot dice que no lo sabe. Punto.
- **No necesitas clave para todo:** solo hacen falta el token de Telegram, el ID de admin y una clave de modelo compatible con OpenAI. Lo demás (Tavily, Cloudflare, GitHub, Spotify, E2B) es opcional — sin eso sigue funcionando, con alternativas gratuitas.
- **En grupos no se mete donde no le llaman:** solo responde cuando se le habla (respuesta, mención o la palabra «Prometheus»). Lo demás se archiva en silencio.
- **No ejecuta código en local:** Python va primero al sandbox en la nube de E2B (si hay clave), si no a un sandbox local aislado. La shell destructiva nunca se ejecuta, ni siquiera por orden del admin.

---

## Estructura del proyecto

El repo está organizado de forma separada, modular y estándar:

```text
prometheusopenbot/
├── bot.py                     # Entrada principal: servidor Telegram + arranque del bot
├── requirements.txt           # Dependencias Python
├── .env.example               # Plantilla de variables de entorno
├── nixpacks.toml / railway.json # Config de despliegue cloud (Railway / Nixpacks)
│
├── src/                       # Paquete principal
│   ├── core/                  # Base de datos, IA, cliente HTTP y config
│   │   ├── ai_service.py      # Servicio LLM unificado, prompts, visión, herramientas
│   │   ├── config.py          # Carga de env, política de seguridad, system prompt
│   │   ├── database.py        # Almacén cloud multinivel (Cloudflare D1 y KV)
│   │   ├── http.py            # Gestión de sesiones HTTP asíncronas
│   │   └── security.py        # Validación de comandos, rate limits, anti-intrusión
│   ├── tools/                 # ~90 herramientas enfocadas (sobrantes eliminadas)
│   │   ├── admin/             # Gobernanza de grupos y moderación
│   │   ├── database/          # Consultas e interacción cloud
│   │   ├── dev/               # Dev: GitHub, Reddit, StackOverflow
│   │   ├── files/             # Generar/extraer docs (PDF, Word, Excel, CSV)
│   │   ├── financial/         # Cotizaciones live: cripto, oro, fiat y forex
│   │   ├── github/            # Repos/issues/commits de GitHub
│   │   ├── internal/          # Optimizadores de memoria, compresión de prompt, caché
│   │   ├── media/             # Descarga de música, metadatos, letras, voz
│   │   ├── scientific/        # Mates, estadística, conversor de unidades
│   │   ├── system/            # Telemetría, sandbox E2B, shell segura de admin
│   │   ├── web_network/       # Buscadores live (Tavily, Bing, Brave, Digikala)
│   │   └── registry.py        # Autoregistro de schemas + dispatcher
│   ├── ui/                    # Panel de admin in-app (botones inline)
│   └── utils/                 # Formato Telegram, limpieza de salidas, tipografía
│
├── tests/                     # Suites de pruebas
│   ├── test_master.py         # Validación integral del sistema
│   ├── run_test_battery.py    # Simulación de bot, BD y estrés
│   ├── test_stress.py         # Estabilidad bajo carga pesada
│   ├── run_rigorous_tests.py  # Evaluación de herramientas web/red live
│   ├── test_financial_scientific_suite.py # Tests financieros y mates
│   ├── test_media_files_runner.py        # Tests de docs/media/imagen
│   └── test_rigorous_battery.py          # Casos borde y entradas raras
│
└── assets/                    # Estáticos y fuentes persas
```

---

## Cómo funciona

El bot corre sobre un pipeline moderno de varias capas:

```text
┌─────────────────────────────────────────────────────────────┐
│                    Usuario en Telegram                      │
└──────────────────────────────┬──────────────────────────────┘
                                │ (texto, voz, respuesta, archivo)
                                ▼
┌─────────────────────────────────────────────────────────────┐
│                 Telegram Dispatcher Engine                  │
│        (auth, rate limiting, análisis de acceso)             │
└──────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────┐
│                   3-Tier Memory Architecture                │
│  • L1 Cache: RAM local ultrarrápida para precios/respuestas │
│  • Cloudflare KV: memoria cloud distribuida clave/valor     │
│  • Cloudflare D1: SQL con búsqueda de texto FTS5            │
└──────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────┐
│             Autonomous LLM Multi-Step Reasoner              │
│     (razonamiento multipaso + Function Calls en paralelo)   │
└──────────────────────────────┬──────────────────────────────┘
                                │ (Parallel Tool Execution)
                                ▼
┌─────────────────────────────────────────────────────────────┐
│                 Tool Matrix (~90 herramientas)              │
│  • Finanzas (Binance, Nobitex, oro, monedas, Tether, forex) │
│  • Web y noticias (Tavily AI, scrapers, Digikala, clima)     │
│  • Media y audio (música 320, Whisper STT, QR, Telegraph)    │
│  • Ops y sistema (sandbox Python, logs, ban global)         │
└──────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────┐
│               Telegram HTML & Shield Formatter              │
│     (máscara auto [SECRET] + formato estándar)              │
└──────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────┐
│                    Respuesta a Telegram                     │
└─────────────────────────────────────────────────────────────┘
```

### 1. Llamadas paralelas a herramientas
El mensaje se analiza primero y se divide en intenciones independientes. Si hay varias peticiones en un mensaje (p. ej. precio de Bitcoin, clima de Teherán y hora oficial a la vez), el bot identifica las herramientas y las llama en paralelo.

### 2. Almacenamiento en 3 niveles
- **Nivel 1 (L1 In-Memory Cache):** caché RAM rapidísima con TTL para datos live (tipos de cambio, cripto).
- **Nivel 2 (Cloudflare Workers KV):** memoria cloud distribuida clave/valor para sesiones, caché larga y ajustes dinámicos.
- **Nivel 3 (Cloudflare D1 SQL):** BD relacional serverless con FTS5 para historial completo, logs y miembros.

### 3. Aislamiento de comandos de admin
Las herramientas sensibles (ejecutar Python, terminal, gestión de grupos, ban global) exigen el ID numérico de admin (`ADMIN_ID`). Nadie llega por prompt injection ni suplantación.

---

## Obtención de claves API

Para funciones completas necesitas algunas claves. Unas son **obligatorias** (primer arranque), otras **opcionales** (herramientas laterales).

### 1. Token del bot de Telegram (TELEGRAM_BOT_TOKEN) — [obligatorio 🔴]
- **Uso:** identidad del bot para conectar a Telegram y enviar/recibir mensajes.
- **Cómo conseguirlo:**
  1. Abre [@BotFather](https://t.me/BotFather) en Telegram.
  2. Envía `/newbot`.
  3. Elige nombre visible y luego username (debe terminar en `bot`).
  4. BotFather te da un token tipo `1234567890:ABCdefGhIJKlmNoPQRsTUVwxyZ`.
  5. Para grupos: ejecuta `/setprivacy` en BotFather, elige tu bot y ponlo en `Disable` para que lea mensajes de grupo.

### 2. ID numérico de admin (ADMIN_ID) — [obligatorio 🔴]
- **Uso:** identidad del dueño/super-admin para panel, ejecución Python, baneos y grupos.
- **Cómo conseguirlo:**
  1. Abre [@userinfobot](https://t.me/userinfobot) o [@JsonDumpBot](https://t.me/JsonDumpBot).
  2. Dale a start y recibe tu ID numérico (p. ej. `123456789`).
  3. Ponlo en `ADMIN_ID`.

### 3. Clave y endpoint de IA (ROUTER_API_KEY y ROUTER_BASE_URL) — [obligatorio 🔴]
- **Uso:** el cerebro: razonamiento, intenciones y tool calls. Vale cualquier proveedor compatible con **OpenAI API**:
- **Opciones:**
  - **OpenAI oficial:**
    - [platform.openai.com](https://platform.openai.com/api-keys) → nueva clave (`sk-...`)
    - `ROUTER_BASE_URL=https://api.openai.com/v1`, `ROUTER_MODEL=gpt-4o-mini`
  - **OpenRouter (muchos modelos en un sitio):**
    - [openrouter.ai](https://openrouter.ai/keys) → API key
    - `ROUTER_BASE_URL=https://openrouter.ai/api/v1`, cualquier modelo (`google/gemini-flash-1.5`, `openai/gpt-4o-mini`)
  - **DeepSeek:**
    - [platform.deepseek.com](https://platform.deepseek.com/api_keys) → clave, `ROUTER_BASE_URL=https://api.deepseek.com/v1`, `ROUTER_MODEL=deepseek-chat`
  - **Groq (rapidísimo):**
    - [console.groq.com](https://console.groq.com/keys) → clave gratis, `ROUTER_BASE_URL=https://api.groq.com/openai/v1`, `ROUTER_MODEL=llama-3.3-70b-versatile`

### 4. Cuenta de Cloudflare, D1 y KV — [opcional 🟡]
- **Uso:** historial permanente, búsqueda full-text de mensajes viejos, baneados, caché cloud. Sin esto tira de RAM (L1).
- **Cómo conseguirlo gratis:**
  1. Cuenta en [cloudflare.com](https://cloudflare.com).
  2. **Account ID:** abre Workers & D1 en el panel; el ID de 32 caracteres está a la derecha.
  3. **API Token:** *My Profile > API Tokens > Create Token*, plantilla *Edit Cloudflare Workers*.
  4. **Base D1:** *Workers & Pages > D1 SQL Database*, crea una (p. ej. `prometheus-db`), UUID a `CLOUDFLARE_D1_ID`.
  5. **KV:** *Workers & Pages > KV*, crea un namespace (p. ej. `prometheus-kv`), ID a `CLOUDFLARE_KV_ID`.

### 5. Clave de búsqueda Tavily (TAVILY_API_KEY) — [opcional ⚪]
- **Uso:** buscador IA rápido para noticias live, comparar versiones, eventos del día.
- **Cómo conseguirla gratis:**
  1. [tavily.com](https://tavily.com), registro (gratis: 1000 búsquedas/mes, sin tarjeta).
  2. Copia tu clave (empieza por `tvly-`) en `TAVILY_API_KEY`.

### 6. Clave de AllRatesToday (ALLRATESTODAY_API_KEY) — [opcional ⚪]
- **Uso:** tipos fiat directos (USD, EUR, AED...) y oro/monedas de Irán.
- **Cómo conseguirla:**
  1. [allratestoday.com](https://allratestoday.com), registro, clave `art_live_...`.
  2. *(Sin ella el bot usa scrapers web automáticamente.)*

### 7. Token de GitHub (GITHUB_TOKEN) — [opcional ⚪]
- **Uso:** límites altos para las 12 herramientas GitHub (código/commits/issues/releases).
- **Cómo conseguirlo gratis:**
  1. [github.com/settings/tokens](https://github.com/settings/tokens).
  2. *Generate new token (classic)*, marca `public_repo`, token `ghp_...` en `GITHUB_TOKEN`.

### 8. Claves de Spotify (SPOTIFY_CLIENT_ID y SPOTIFY_CLIENT_SECRET) — [opcional ⚪]
- **Uso:** portadas oficiales y metadatos exactos de temas extranjeros.
- **Cómo conseguirlas gratis:**
  1. [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard).
  2. Crea una app, copia `Client ID` y `Client Secret`.
  3. *(Sin ellas: iTunes API + metadatos por defecto.)*

### 9. Sandbox en la nube E2B (E2B_API_KEY) — [opcional ⚪]
- **Uso:** ejecutar Python/JavaScript/shell aislado en la nube, cero carga en tu servidor. Sin ella: sandbox local.
- **Cómo conseguirla gratis:**
  1. Registro en [e2b.dev](https://e2b.dev).
  2. Clave del [panel E2B](https://e2b.dev/dashboard?tab=keys) (empieza por `e2b_`).
  3. Ponla en `E2B_API_KEY`. (Opcional: `E2B_TEMPLATE` para plantilla propia, `E2B_TIMEOUT_SEC` para el tope.)

---

## Variables de entorno

Crea un `.env` en la raíz y rellénalo según la guía:

| Variable | Tipo | Defecto | Uso |
| :--- | :---: | :---: | :--- |
| `TELEGRAM_BOT_TOKEN` | obligatoria 🔴 | - | Token del bot, de BotFather |
| `ADMIN_ID` | obligatoria 🔴 | `0` | ID numérico del super-admin en Telegram |
| `ROUTER_BASE_URL` | obligatoria 🔴 | `https://api.openai.com/v1` | Endpoint V1 compatible OpenAI |
| `ROUTER_API_KEY` | obligatoria 🔴 | - | Clave del modelo IA |
| `ROUTER_MODEL` | opcional ⚪ | `gpt-4o-mini` | Modelo (`gpt-4o-mini`, `deepseek-chat`...) |
| `CLOUDFLARE_ACCOUNT_ID` | opcional ⚪ | `""` | Account ID de 32 caracteres |
| `CLOUDFLARE_API_TOKEN` | opcional ⚪ | `""` | Token Cloudflare con permiso D1 + KV |
| `CLOUDFLARE_D1_ID` | opcional ⚪ | `""` | UUID de la base D1 |
| `CLOUDFLARE_KV_ID` | opcional ⚪ | `""` | ID del namespace KV |
| `TAVILY_API_KEY` | opcional ⚪ | `""` | Clave de búsqueda Tavily AI |
| `ALLRATESTODAY_API_KEY` | opcional ⚪ | `""` | Clave de oro/fiat live |
| `GITHUB_TOKEN` | opcional ⚪ | `""` | Token personal GitHub (límites) |
| `SPOTIFY_CLIENT_ID` | opcional ⚪ | `""` | Spotify Client ID |
| `SPOTIFY_CLIENT_SECRET` | opcional ⚪ | `""` | Spotify Client Secret |
| `E2B_API_KEY` | opcional ⚪ | `""` | Sandbox cloud E2B (si no: local) |
| `E2B_TIMEOUT_SEC` | opcional ⚪ | `30` | Tope E2B en segundos (5–120) |
| `ENABLE_FINANCIAL_SYNC` | opcional ⚪ | `1` | Sync de precios en fondo (`0` = off, ahorra cuota KV) |

---

## Instalación paso a paso

### 1. Clonar el código
```bash
git clone https://github.com/zaryamyn273-crypto/prometheusopenbot.git
cd prometheusopenbot
```

### 2. Entorno virtual Python
```bash
python3 -m venv venv
# Linux / macOS:
source venv/bin/activate
# Windows:
venv\Scripts\activate
```

### 3. Instalar dependencias
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Config
```bash
cp .env.example .env
nano .env   # pega las claves de la guía
```

### 5. Ejecutar el bot
```bash
python bot.py
```
Tras conectar a Telegram el bot fija sus comandos e imprime el listo en consola.

---

## Despliegue en la nube

### Railway:
1. Fork o push del repo a tu GitHub.
2. Abre el panel [Railway.app](https://railway.app), **New Project > Deploy from GitHub repo**.
3. Elige tu repo.
4. En **Variables** añade las del `.env`.
5. Gracias a `nixpacks.toml` + `railway.json`, Railway configura Python 3.12 y `ffmpeg` solo y arranca.

### Linux con Systemd:
Crea `/etc/systemd/system/prometheus.service`:
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
Activa e inicia:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now prometheus
```

---

## Matriz de herramientas

~**90 herramientas registradas**, cada una con un trabajo claro. Eliminadas por muertas/duplicadas/teatro: `darkweb_search`, `internal_resilient_fallback_search`, `autonomous_system_health_check`, `bot_rate_guard`, `bot_output_compactor`, `bot_prompt_token_saver`, `bot_alias_resolver`, `bot_d1_remember`, `bot_d1_recall`.

1. **📊 Finanzas (`src/tools/financial/`):**
   - Cripto live de Binance y Nobitex (`get_price`, `get_crypto_overview`).
   - Oro/monedas live y prima (`get_gold_and_coin_price`).
   - Tether, USD, EUR, AED y cruces forex (`get_dollar_price`, `get_fiat_overview`, `get_global_forex_rates`).

2. **🌐 Web y red (`src/tools/web_network/`):**
   - Búsqueda lista: Tavily AI + motores (`tavily_search`, `web_search`, `deep_search_and_read`).
   - Noticias live (`live_news`).
   - Productos/precios Digikala (`digikala_search`).
   - Red: `check_website_status`, `resolve_dns`, `check_ssl_certificate`, `get_ip_info`.
   - Clima con humedad y viento (`get_weather`).

3. **🎵 Media y audio (`src/tools/media/`):**
   - Música en 320kbps original con tags y portada (`download_music_track`).
   - Letras y `.lrc` sincronizados (`get_song_lyrics`).
   - Voz/audio a texto con Whisper (`transcribe_audio_tool`).
   - QR (`generate_qr_code_tool`).
   - Artículos largos vía Telegraph Instant View (`publish_telegraph_article`).

4. **🔬 Ciencia y general (`src/tools/scientific/`):**
   - Calculadora avanzada (`calculate_math_expression`).
   - Estadística (`statistics_summary`).
   - Hora/calendario oficial (`get_current_datetime_info`).
   - Conversor de unidades y hashes (`convert_units`, `generate_hash_digest`, ...).

5. **🛡️ Sistema y admin (`src/tools/admin/` y `src/tools/system/`):**
   - Python en sandbox para el super-admin (`execute_python_code`).
   - Ejecución cloud aislada con E2B (`e2b_run_code`, `e2b_run_command`); sin clave: local.
   - Telemetría (`admin_system_diagnostics`).
   - Ban/mute global en D1 (`ban_user_tool`, `mute_user_tool`).
   - Grupos y salida de emergencia (`list_joined_groups_tool`, `leave_group_by_admin_tool`).

6. **🐙 GitHub (`src/tools/github/`):**
   - Buscar repos/issues/commits/releases y análisis.

---

## Modelo de seguridad

- **Máscara auto de secretos:** salidas y logs pasan filtros de claves + regex; lo sensible se vuelve `[SECRET]`, los tokens no llegan a los chats.
- **PV vs grupos:** los comandos de gestión en privado son solo para la identidad `ADMIN_ID`.
- **Anti prompt-injection:** lógica en Python + system prompt contra cambio de rol y jailbreaks.

---

## Pruebas

Antes de desplegar, chequeo de módulos y herramientas:

```bash
# auditoría de registro + herramientas offline
python tests/test_master.py

# evaluación multi + estrés
python tests/run_test_battery.py

# sandbox E2B (sin clave/paquete salta el live)
python tests/test_e2b.py
```

---

## Licencia y contribuciones

Proyecto open-source: arquitectura de agentes limpia y escalable para la comunidad. Reportes y pull requests bienvenidos.
