# Prometheus — un bot de Telegram normal que intenta ser útil
> Un bot de Telegram conectado a un modelo de lenguaje, con varias herramientas útiles (precios de divisas, oro y cripto, clima, búsqueda web, música, archivos, cálculos). En lugar de adivinar va a las herramientas; si algo está roto lo dice. Aquí no hay milagros.

[![CI](https://github.com/zaryamyn273-crypto/prometheusopenbot/actions/workflows/ci.yml/badge.svg)](https://github.com/zaryamyn273-crypto/prometheusopenbot/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)

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
- [Inicio rápido](#inicio-rápido)
- [Arquitectura](#arquitectura)
- [Herramientas](#herramientas)
- [Seguridad](#seguridad)
- [Pruebas](#pruebas)
- [Licencia y contribuciones](#licencia-y-contribuciones)
- [📚 Docs completas](docs/setup/keys.md)

---

## Descripción general

**Prometheus** es un bot open-source de Telegram que conecta un modelo de lenguaje a herramientas reales. La idea es simple, y eso es lo que hace:

- **No adivines, ve a mirar:** todo lo que necesita datos en vivo (precios, clima, noticias, estado de sitios) viene directo de una herramienta, no de la memoria del modelo. Si una herramienta falla, el bot dice que no lo sabe. Punto.
- **No necesitas clave para todo:** solo hacen falta el token de Telegram, el ID de admin y una clave de modelo compatible con OpenAI. Lo demás (Tavily, Cloudflare, GitHub, Spotify, E2B) es opcional — sin eso sigue funcionando, con alternativas gratuitas.
- **En grupos no se mete donde no le llaman:** solo responde cuando se le habla (respuesta, mención o la palabra «Prometheus»). Lo demás se archiva en silencio.
- **En el servidor no se ejecuta código:** el código del IA solo corre en el sandbox cloud de E2B; sin clave la herramienta está desactivada (sin fallback local por diseño). La shell destructiva nunca se ejecuta, ni siquiera por orden del admin.
- **No solo persa:** detecta el idioma del texto (no solo el ajuste de Telegram) y responde en él — persa, inglés, ruso, árabe, turco...; las salidas se traducen cuando hace falta.
- **Cuota diaria justa:** cada usuario recibe `DAILY_USER_LIMIT` (40 por defecto) respuestas completas de IA al día en todos los chats; reinicio automático cada 24 h (00:00 UTC), sin cron; admin ilimitado y puede ajustar la cuota de cada uno (`/setquota`, `/resetquota`). `/limit` muestra el saldo.
- **El admin no necesita slash:** las órdenes en lenguaje natural se ejecutan directamente («leave group X», lista de grupos, «set quota for X to 100»...) — sin adivinar, con verificación en vivo.
- **Seguridad de grupos:** entrar requiere aprobación del admin (botones en privado), lista en vivo desde Telegram, historial conservado al salir, y salidas siempre puntuales y verificadas.
- **Eliminación masiva de mensajes (`/purge`, `/del`):** borrado sincronizado de mensajes del bot por comandos o lenguaje natural («elimina tus últimos 10 mensajes») en Telegram, Cloudflare D1 y RAM.
- **Gestión Cloud de Railway (`/railway`):** monitorización de estado de contenedores, inspección de variables y redespliegues inmediatos sin claves en el repositorio.
- **OSINT profundo (`osint_person_dossier`):** recopilación paralela de huellas digitales en GitHub, Keybase, Telegram, Reddit, HackerNews y web.
- **Automatización de GitHub y empaquetado:** creación de repositorios, commits automáticos, generación de `PKGBUILD` (Arch Linux / AUR) y `CMakeLists.txt` (C++20).
- **Reconstrucción matemática de códigos de barras:** resolución de dígitos dañados (`??`) con Modulo-10/11 y tabla oficial de prefijos de países GS1.
- **Planificador de tareas y cron internacional:** tareas programadas persistentes en Cloudflare D1 con detección automática de zona horaria por idioma y ciudad.

---

## Inicio rápido

Solo **3 variables** para arrancar — lo demás es opcional:

```bash
git clone https://github.com/zaryamyn273-crypto/prometheusopenbot.git
cd prometheusopenbot
cp .env.example .env   # TELEGRAM_BOT_TOKEN, ADMIN_ID, ROUTER_API_KEY
pip install -r requirements.txt && python bot.py
# o con Docker: docker compose up -d --build
```

Guías completas de claves: [docs/setup/keys.md](docs/setup/keys.md) — despliegue: [Railway](docs/setup/railway.md) • [Docker](docs/setup/docker.md)

---

## Arquitectura

Pipeline: update de Telegram → gatekeepers → archivo en D1 en fondo → **triage Tier 0/1** (hora, charla, cotizaciones — sin IA) → agente ReAct Tier 2 (hasta 8 rondas) → entrega traducida. Memoria en 3 niveles (RAM L1 → Cloudflare KV → D1 SQL/FTS5); los módulos se cargan lazy, solo los necesarios. Probes: `GET /healthz`. Detalles: [docs/architecture/overview.md](docs/architecture/overview.md)

---

## Comandos de Telegram (Matriz Completa)

Prometheus cuenta con un catálogo exhaustivo de comandos. Para evitar interferencias con otros bots, **en los supergrupos los comandos requieren el sufijo `_prometheus` o mención directa al bot** (por ejemplo, `/help_prometheus` o `/del_prometheus 10`). En chats privados (PV), funcionan tanto los comandos estándar como los que llevan sufijo.

### 1. Comandos Principales y Generales
* **`/start`**
  - **Función:** Inicia la interacción, presenta las capacidades del bot y verifica los permisos del usuario.
  - **Permiso:** Público (todos los usuarios).
* **`/help`**
  - **Función:** Guía interactiva multilingüe con instrucciones de uso, herramientas conectadas y normas de grupo.
  - **Permiso:** Público.
* **`/tools` (o `/tools_prometheus`)**
  - **Función:** Muestra el catálogo categorizado de herramientas conectadas al modelo (búsqueda web, visión, finanzas, archivos, OSINT, etc.).
  - **Permiso:** Público.
* **`/clear` (o `/clear_prometheus`)**
  - **Función:** Reinicia la ventana de memoria en RAM del chat actual, iniciando una sesión limpia con cero contexto previo.
  - **Permiso:** Público.
* **`/id` o `/getid` (o `/id_prometheus`)**
  - **Función:** Extrae el identificador numérico (`user_id` / `chat_id`), nombre de usuario y metadatos del remitente o del mensaje respondido.
  - **Permiso:** Público.

### 2. Inteligencia en Vivo, Finanzas y Multimedia
* **`/search <consulta>`**
  - **Función:** Ejecuta una búsqueda competitiva ultrarrápida en la web (Tavily AI, Bing, DuckDuckGo) con fuentes contrastadas en menos de 1,2 s.
  - **Ejemplo:** `/search avances inteligencia artificial 2026`
  - **Permiso:** Público.
* **`/crypto [símbolo]`**
  - **Función:** Consulta precios en tiempo real de criptomonedas (BTC, ETH, USDT, TON, SOL) y variación porcentual en 24 horas.
  - **Ejemplo:** `/crypto btc` o `/crypto` (tabla de principales divisas).
  - **Permiso:** Público.
* **`/gold`**
  - **Función:** Muestra cotizaciones en vivo del oro (18K, lingotes), monedas soberanas y cotización internacional.
  - **Permiso:** Público.
* **`/weather <ciudad>`**
  - **Función:** Condiciones meteorológicas en directo, temperatura, humedad, viento y previsión de cualquier ciudad.
  - **Ejemplo:** `/weather Madrid` o `/weather Buenos Aires`
  - **Permiso:** Público.
* **`/calc <expresión matemática>`**
  - **Función:** Calculadora algebraica y científica de alta precisión (trigonometría, porcentajes, factoriales) sin errores de cálculo del LLM.
  - **Ejemplo:** `/calc (350 * 1.21) + sqrt(144)`
  - **Permiso:** Público.
* **`/music <canción / artista>`**
  - **Función:** Búsqueda y descarga directa de audio con calidad de estudio a 320 kbps y archivo de letra sincronizada (.lrc).
  - **Ejemplo:** `/music Queen Bohemian Rhapsody`
  - **Permiso:** Público.

### 3. Planificador Internacional y Cron
* **`/remind <tiempo> <mensaje>` (o `/schedule`)**
  - **Función:** Programa recordatorios, tareas o alertas cron con almacenamiento persistente en Cloudflare D1 (resistente a reinicios del servidor).
  - **Ejemplos:**
    - `/remind 15m Apagar el horno`
    - `/remind mañana a las 5 pm hora Madrid Reunión de equipo`
    - `/remind at 14:00 London time Sync call`
    - `/remind */30 * * * * Revisión periódica`
  - **Permiso:** Público.
* **`/schedules`**
  - **Función:** Muestra todas las tareas y recordatorios activos del chat actual con su ID y próxima hora de ejecución.
  - **Permiso:** Público.
* **`/cancel_schedule <id>`**
  - **Función:** Cancela y elimina una tarea programada mediante su ID numérico (`/cancel_schedule 3`).
  - **Permiso:** Público (propietario de la tarea o administrador).
* **`/timezone <ciudad>` (o `/tz`)**
  - **Función:** Consulta o establece la zona horaria del usuario (`/tz Europe/Madrid` o `/tz America/Mexico_City`).
  - **Permiso:** Público.

### 4. Limpieza y Borrado Masivo de Mensajes
* **`/del` (en respuesta a un mensaje)**
  - **Función:** Borra de inmediato el mensaje al que se responde.
  - **Permiso:** Master Admin y administradores del grupo.
* **`/purge <cantidad>` (o `/del <cantidad>`, `/clean <cantidad>`)**
  - **Función:** Borrado masivo de los últimos N mensajes enviados por el bot (de 1 a 100) sincronizado en Telegram, Cloudflare D1 y RAM, con aviso de confirmación que se autodestruye en 4 segundos.
  - **Ejemplo:** `/purge 10` (también se activa con órdenes en lenguaje natural del admin: «elimina tus últimos 10 mensajes»).
  - **Permiso:** Master Admin y administradores del grupo.

### 5. Gestión Cloud de Railway
* **`/railway status`**
  - **Función:** Estado en vivo de la infraestructura en Railway, servicios activos (`prometheusopenbot`, `9router`) y último estado de despliegue (SUCCESS / BUILDING / CRASHED).
  - **Permiso:** Solo Master Admin.
* **`/railway redeploy [servicio]`**
  - **Función:** Lanza un redespliegue y reconstrucción inmediata del contenedor en Railway basado en el último commit sin abrir el navegador.
  - **Ejemplo:** `/railway redeploy prometheusopenbot`
  - **Permiso:** Solo Master Admin.
* **`/railway vars [servicio]`**
  - **Función:** Inspección segura de variables de entorno con enmascaramiento automático de contraseñas y tokens.
  - **Permiso:** Solo Master Admin.

### 6. Shell Linux y Sandboxes en la Nube
* **`/sh <comando>` (o `/bash`)**
  - **Función:** Terminal shell del servidor con persistencia de directorio (`cd`), tiempo límite de 35 segundos, credenciales autenticadas y subida automática de archivos `.log` cuando la salida supera 3500 caracteres.
  - **Ejemplo:** `/sh df -h && uptime` o `/sh cd src && ls -la`
  - **Permiso:** Solo Master Admin (comandos destructivos bloqueados permanentemente).
* **`/e2b <código>`**
  - **Función:** Ejecución aislada de código Python o JavaScript en microcontenedores cloud E2B con cero riesgo de RCE local.
  - **Permiso:** Solo Master Admin.
* **`/e2bsh <comando>`**
  - **Función:** Ejecución de comandos shell en el entorno aislado de E2B.
  - **Permiso:** Solo Master Admin.
* **`/e2bstatus`**
  - **Función:** Informa del estado de conexión y validez del cliente E2B.
  - **Permiso:** Solo Master Admin.
* **`/set_e2b <clave>`**
  - **Función:** Establece o actualiza la clave API de E2B en la sesión de administración.
  - **Permiso:** Solo Master Admin.
* **`/set_github <token>`**
  - **Función:** Establece o actualiza el token personal de GitHub para creación de repositorios y commits.
  - **Permiso:** Solo Master Admin.

### 7. Administración de Usuarios y Cuotas
* **`/limit`**
  - **Función:** Consulta el consumo diario de respuestas de IA y solicitudes restantes (40 por defecto, reinicio a las 00:00 UTC).
  - **Permiso:** Público (el Master Admin no tiene límite).
* **`/setquota <id_usuario> <límite>`**
  - **Función:** Ajusta o amplía la cuota diaria de un usuario específico.
  - **Ejemplo:** `/setquota 123456789 100`
  - **Permiso:** Solo Master Admin.
* **`/resetquota <id_usuario>`**
  - **Función:** Restablece de inmediato el contador de un usuario a cero consumidos.
  - **Permiso:** Solo Master Admin.
* **`/ban <objetivo>`**
  - **Función:** Bloquea de forma permanente a un usuario en todas las capas del bot y D1 por ID, alias o respuesta.
  - **Permiso:** Solo Master Admin.
* **`/unban <objetivo>`**
  - **Función:** Desbloquea y restaura el acceso de un usuario.
  - **Permiso:** Solo Master Admin.
* **`/mute` y `/unmute`**
  - **Función:** Silencia o reactiva a un usuario en el grupo.
  - **Permiso:** Master Admin y administradores del grupo.
* **`/mutelist`**
  - **Función:** Lista de usuarios silenciados en el grupo.
  - **Permiso:** Master Admin y administradores del grupo.

### 8. Operaciones de Grupos y Red
* **`/admin` (o `/panel`)**
  - **Función:** Panel de control de administración con estadísticas en vivo de CPU, RAM, D1 y estado general.
  - **Permiso:** Solo Master Admin.
* **`/groups`**
  - **Función:** Lista completa de grupos a los que pertenece el bot, indicando si están aprobados (`active`) o en espera (`pending`).
  - **Permiso:** Solo Master Admin.
* **`/leave <id_grupo>`**
  - **Función:** Salida directa y limpia del bot de un grupo específico sin perder el historial almacenado.
  - **Permiso:** Solo Master Admin.
* **`/bangroup <id_grupo>`**
  - **Función:** Bloquea de forma permanente un grupo, expulsa al bot y prohíbe reincorporaciones.
  - **Permiso:** Solo Master Admin.
* **`/channels`**
  - **Función:** Muestra los canales conectados gestionados por el bot.
  - **Permiso:** Solo Master Admin.
* **`/net`**
  - **Función:** Comprueba la conectividad de red del servidor con APIs globales y servicios de IA.
  - **Permiso:** Solo Master Admin.
* **`/remember <clave> <valor>`**
  - **Función:** Guarda una regla, hecho o directiva inmutable en la memoria permanente del bot (`manage_admin_memory`).
  - **Permiso:** Solo Master Admin.
* **`/forget <clave>`**
  - **Función:** Elimina una directiva guardada de la memoria permanente.
  - **Permiso:** Solo Master Admin.

---

## Herramientas

~**90 herramientas** en 6 familias (finanzas, web/red, media, ciencia, sistema/admin, GitHub) + memoria cloud. Matriz completa: [docs/architecture/tooling.md](docs/architecture/tooling.md)

---

## Seguridad

- El código del IA solo corre en E2B cloud; sin clave: DESACTIVADO, sin ejecución local.
- Secretos enmascarados como `[SECRET]`; admin solo por `ADMIN_ID` numérico.
- Anti-jailbreak en 3 capas: preescaneo determinista, bloque de inmunidad en el prompt, puertas de admin.
- Guardia SSRF: fetch solo a hosts públicos; lector de archivos limitado a `/tmp`; HTML escapado.
- Modelo de amenazas + divulgación responsable: [SECURITY.md](SECURITY.md)

---

## Pruebas

```bash
python tests/test_master.py       # auditoría integral
python tests/test_i18n.py         # bilingüismo (offline)
python tests/test_e2b.py          # sandbox (offline sin clave)
python tests/run_test_battery.py  # estrés multidimensional
python tests/test_leave_match.py    # salida puntual (offline)
python tests/test_daily_limit.py    # cuota diaria (offline)
python tests/test_intent_router.py  # órdenes del admin (offline)
python tests/test_detect_lang.py    # detección de idioma (offline)
python tests/test_quota_override.py # cuotas de admin (offline)
python tests/test_adversarial.py    # anti-jailbreak/SSRF/puertas (offline)
```
Cada push lo verifica GitHub Actions (badge arriba).

---

## Licencia y contribuciones

Proyecto open-source: arquitectura de agentes limpia y escalable para la comunidad. Reportes y pull requests bienvenidos.
