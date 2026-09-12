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
- **Cuota diaria justa:** cada usuario recibe `DAILY_USER_LIMIT` (40 por defecto) respuestas completas de IA al día en todos los chats; reinicio automático cada 24 h (00:00 UTC), sin cron; admin ilimitado. `/limit` muestra el saldo.
- **El admin no necesita slash:** las órdenes en lenguaje natural se ejecutan directamente («leave group X», lista de grupos...) — sin adivinar, con verificación en vivo.
- **Seguridad de grupos:** entrar requiere aprobación del admin (botones en privado), lista en vivo desde Telegram, historial conservado al salir, y salidas siempre puntuales y verificadas.

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

## Herramientas

~**90 herramientas** en 6 familias (finanzas, web/red, media, ciencia, sistema/admin, GitHub) + memoria cloud. Matriz completa: [docs/architecture/tooling.md](docs/architecture/tooling.md)

---

## Seguridad

- El código del IA solo corre en E2B cloud; sin clave: DESACTIVADO, sin ejecución local.
- Secretos enmascarados como `[SECRET]`; admin solo por `ADMIN_ID` numérico.
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
```
Cada push lo verifica GitHub Actions (badge arriba).

---

## Licencia y contribuciones

Proyecto open-source: arquitectura de agentes limpia y escalable para la comunidad. Reportes y pull requests bienvenidos.
