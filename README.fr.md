# Prometheus — un bot Telegram ordinaire qui essaie d'être utile
> Un bot Telegram relié à un modèle de langage, avec quelques outils utiles (prix devises, or et crypto, météo, recherche web, musique, fichiers, calculs). Au lieu de deviner il va aux outils ; si un truc est cassé il le dit. Pas de miracles ici.

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

## 📖 Sommaire
- [Aperçu](#aperçu)
- [Démarrage rapide](#démarrage-rapide)
- [Architecture](#architecture)
- [Outils](#outils)
- [Sécurité](#sécurité)
- [Tests](#tests)
- [Licence et contributions](#licence-et-contributions)
- [📚 Docs complètes](docs/setup/keys.md)

---

## Aperçu

**Prometheus** est un bot Telegram open-source qui branche un modèle de langage sur des outils réels. L'idée est simple, et c'est tout ce qu'il fait :

- **Ne devine pas, va vérifier :** tout ce qui demande des données en direct (prix, météo, actus, état des sites) vient directement d'un outil, pas de la mémoire du modèle. Si un outil est en panne, le bot dit qu'il ne sait pas. Point.
- **Pas besoin de clé pour tout :** seuls le token Telegram, l'ID admin et une clé de modèle compatible OpenAI sont requis. Le reste (Tavily, Cloudflare, GitHub, Spotify, E2B) est optionnel — sans ça, ça marche quand même, avec des replis gratuits.
- **Dans les groupes, il ne s'en mêle pas :** il ne répond que si on s'adresse à lui (réponse, mention ou le mot « Prometheus »). Le reste est archivé en silence.
- **Pas d'exécution sur le serveur :** le code de l'IA ne tourne que dans le sandbox cloud E2B ; sans clé l'outil est DÉSACTIVÉ (pas de fallback local par design). Le shell destructif ne s'exécute jamais, même sur ordre de l'admin.
- **Pas que le persan :** langue détectée depuis le texte (pas seulement le réglage Telegram) — persan, anglais, russe, arabe, turc... ; les sorties d'outils sont traduites au besoin.
- **Quota quotidien équitable :** chaque utilisateur reçoit `DAILY_USER_LIMIT` (40 par défaut) réponses IA complètes par jour dans tous les chats ; reset auto toutes les 24 h (00:00 UTC), sans cron ; admin illimité et peut ajuster chaque quota (`/setquota`, `/resetquota`). `/limit` affiche le solde.
- **Pas de slash pour l'admin :** les ordres en langage naturel s'exécutent directement (« leave group X », liste des groupes, « set quota for X to 100 »...) — sans deviner, avec vérification en direct.
- **Sécurité des groupes :** entrée sur approbation admin (boutons en privé), liste en direct depuis Telegram, historique conservé au départ, sorties toujours ciblées et vérifiées.

---

## Démarrage rapide

Seules **3 variables** pour démarrer — le reste est optionnel :

```bash
git clone https://github.com/zaryamyn273-crypto/prometheusopenbot.git
cd prometheusopenbot
cp .env.example .env   # TELEGRAM_BOT_TOKEN, ADMIN_ID, ROUTER_API_KEY
pip install -r requirements.txt && python bot.py
# ou avec Docker : docker compose up -d --build
```

Guides complets des clés : [docs/setup/keys.md](docs/setup/keys.md) — déploiement : [Railway](docs/setup/railway.md) • [Docker](docs/setup/docker.md)

---

## Architecture

Pipeline : update Telegram → gatekeepers → archive D1 en fond → **triage Tier 0/1** (heure, blabla, cotations — sans IA) → agent ReAct Tier 2 (jusqu'à 8 rounds) → livraison traduite. Mémoire à 3 niveaux (RAM L1 → Cloudflare KV → D1 SQL/FTS5) ; modules d'outils chargés lazy, seulement si besoin. Probes : `GET /healthz`. Détails : [docs/architecture/overview.md](docs/architecture/overview.md)

---

## Outils

~**90 outils** en 6 familles (finance, web/réseau, média, science, système/admin, GitHub) + mémoire cloud. Matrice complète : [docs/architecture/tooling.md](docs/architecture/tooling.md)

---

## Sécurité

- Le code de l'IA ne tourne qu'en E2B cloud ; sans clé : DÉSACTIVÉ, pas d'exécution locale.
- Secrets masqués en `[SECRET]` ; admin uniquement via `ADMIN_ID` numérique.
- Anti-jailbreak en 3 couches : préscan déterministe, bloc d'immunité dans le prompt, portes admin.
- Garde SSRF : fetch limité aux hôtes publics ; lecteur de fichiers cantonné à `/tmp` ; HTML échappé.
- Modèle de menaces + divulgation responsable : [SECURITY.md](SECURITY.md)

---

## Tests

```bash
python tests/test_master.py       # audit intégral
python tests/test_i18n.py         # bilinguisme (offline)
python tests/test_e2b.py          # sandbox (offline sans clé)
python tests/run_test_battery.py  # stress multidimensionnel
python tests/test_leave_match.py    # sortie ciblée (offline)
python tests/test_daily_limit.py    # quota quotidien (offline)
python tests/test_intent_router.py  # ordres admin (offline)
python tests/test_detect_lang.py    # détection de langue (offline)
python tests/test_quota_override.py # quotas admin (offline)
python tests/test_adversarial.py    # anti-jailbreak/SSRF/portes (offline)
```
Chaque push est vérifié par GitHub Actions (badge ci-dessus).

---

## Licence et contributions

Projet open-source : architecture d'agents propre et scalable pour la communauté. Rapports et pull requests bienvenus.
