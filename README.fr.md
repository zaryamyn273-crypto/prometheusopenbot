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
- **Suppression massive de messages (`/purge`, `/del`) :** nettoyage atomique et synchronisé des messages du bot par commande ou requête en langage naturel (« supprime tes 10 derniers messages ») dans Telegram, Cloudflare D1 et la RAM.
- **Gestion de l'infrastructure Railway (`/railway`) :** statut en direct des conteneurs, inspection sécurisée des variables et redéploiement immédiat sans stocker de clés dans le dépôt.
- **OSINT approfondi (`osint_person_dossier`) :** collecte parallèle d'empreinte numérique et dossier d'identité sur GitHub, Keybase, Telegram, Reddit, HackerNews et le web.
- **Automatisation GitHub et empaquetage :** création de dépôts, commits directs, génération de `PKGBUILD` (Arch Linux / AUR) et `CMakeLists.txt` (C++20).
- **Reconstruction mathématique de codes-barres :** résolution algébrique des chiffres endommagés (`??`) avec Modulo-10/11 et table officielle des préfixes nationaux GS1.
- **Planificateur de tâches et cron international :** exécution persistante dans Cloudflare D1 avec détection automatique du fuseau horaire selon la langue et la ville.

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

## Matrice Complète des Commandes Telegram (Telegram Commands)

Prometheus dispose d'un ensemble complet de commandes. Pour éviter les conflits avec d'autres bots, **dans les supergroupes les commandes requièrent le suffixe `_prometheus` ou une mention du bot** (par exemple `/help_prometheus` ou `/del_prometheus 10`). Dans les messages privés (PV), les commandes standards et celles avec suffixe fonctionnent indistinctement.

### 1. Commandes Principales et Générales
* **`/start`**
  - **Description :** Démarre l'interaction privée, présente les fonctionnalités et vérifie les permissions de l'utilisateur.
  - **Permission :** Public (tous les utilisateurs).
* **`/help`**
  - **Description :** Guide interactif multilingue expliquant le fonctionnement, les outils connectés et les règles dans les groupes.
  - **Permission :** Public.
* **`/tools` (ou `/tools_prometheus`)**
  - **Description :** Affiche le catalogue catégorisé des outils connectés au modèle (recherche web, vision, finance, fichiers, OSINT, etc.).
  - **Permission :** Public.
* **`/clear` (ou `/clear_prometheus`)**
  - **Description :** Réinitialise le contexte de discussion en mémoire RAM pour le chat actuel et commence une conversation vierge.
  - **Permission :** Public.
* **`/id` ou `/getid` (ou `/id_prometheus`)**
  - **Description :** Extrait l'identifiant numérique (`user_id` / `chat_id`), le nom d'utilisateur et les métadonnées de l'expéditeur ou du message cité.
  - **Permission :** Public.

### 2. Données en Direct, Finance et Multimédia
* **`/search <requête>`**
  - **Description :** Lance une recherche web spéculative ultra-rapide (Tavily AI, Bing, DuckDuckGo) avec des sources sourcées en moins de 1,2 s.
  - **Exemple :** `/search avancées intelligence artificielle 2026`
  - **Permission :** Public.
* **`/crypto [symbole]`**
  - **Description :** Cours en direct des cryptomonnaies (BTC, ETH, USDT, TON, SOL) et variation sur 24 heures.
  - **Exemple :** `/crypto btc` ou `/crypto` (pour la vue d'ensemble).
  - **Permission :** Public.
* **`/gold`**
  - **Description :** Tableau des cours de l'or (18K, lingots), pièces d'investissement et cours mondial spot.
  - **Permission :** Public.
* **`/weather <ville>`**
  - **Description :** Météo en direct, température, humidité, vent et prévisions pour toute ville du monde.
  - **Exemple :** `/weather Paris` ou `/weather Montréal`
  - **Permission :** Public.
* **`/calc <expression>`**
  - **Description :** Calculatrice algébrique et scientifique haute précision (trigonométrie, pourcentages, factorielles) sans erreurs de calcul du LLM.
  - **Exemple :** `/calc (250 * 1.20) + sqrt(144)`
  - **Permission :** Public.
* **`/music <titre / artiste>`**
  - **Description :** Recherche et téléchargement direct de musique en qualité studio 320 kbps avec fichier de paroles synchronisées (.lrc).
  - **Exemple :** `/music Daft Punk Get Lucky`
  - **Permission :** Public.

### 3. Planificateur International et Cron
* **`/remind <temps> <message>` (ou `/schedule`)**
  - **Description :** Planifie des rappels, tâches ou cron récurrents avec persistance complète dans Cloudflare D1 SQL (résilient aux redémarrages).
  - **Exemples :**
    - `/remind 15m Vérifier le four`
    - `/remind demain à 17h heure de Paris Réunion d'équipe`
    - `/remind at 14:00 London time Team sync`
    - `/remind */30 * * * * Vérification d'état`
  - **Permission :** Public.
* **`/schedules`**
  - **Description :** Affiche la liste des tâches actives planifiées pour le chat actuel avec leur ID et la prochaine heure d'exécution.
  - **Permission :** Public.
* **`/cancel_schedule <id>`**
  - **Description :** Annule et supprime une tâche planifiée à partir de son identifiant numérique (`/cancel_schedule 3`).
  - **Permission :** Public (créateur de la tâche ou administrateur).
* **`/timezone <ville>` (ou `/tz`)**
  - **Description :** Consulte ou définit le fuseau horaire de l'utilisateur (`/tz Europe/Paris` ou `/tz America/Montreal`).
  - **Permission :** Public.

### 4. Nettoyage et Suppression Massive de Messages
* **`/del` (en réponse à un message)**
  - **Description :** Supprime instantanément le message ciblé par la réponse.
  - **Permission :** Master Admin et administrateurs du groupe.
* **`/purge <nombre>` (ou `/del <nombre>`, `/clean <nombre>`)**
  - **Description :** Suppression groupée rapide des N derniers messages envoyés par le bot (de 1 à 100) synchronisée dans Telegram, Cloudflare D1 et la RAM, avec un message de confirmation qui s'autodétruit en 4 secondes.
  - **Exemple :** `/purge 10` (déclenchable aussi en langage naturel : « supprime tes 10 derniers messages »).
  - **Permission :** Master Admin et administrateurs du groupe.

### 5. Gestion Cloud de Railway
* **`/railway status`**
  - **Description :** État télémétrique en direct des conteneurs Railway, des services actifs (`prometheusopenbot`, `9router`) et statut du dernier déploiement (SUCCESS / BUILDING / CRASHED).
  - **Permission :** Uniquement Master Admin.
* **`/railway redeploy [service]`**
  - **Description :** Déclenche un redéploiement et une recompilation immédiate du conteneur sur Railway sans passer par le navigateur web.
  - **Exemple :** `/railway redeploy prometheusopenbot`
  - **Permission :** Uniquement Master Admin.
* **`/railway vars [service]`**
  - **Description :** Affiche les variables d'environnement du service avec masquage automatique et sécurisé de tous les secrets.
  - **Permission :** Uniquement Master Admin.

### 6. Terminal Linux et Sandboxes Cloud
* **`/sh <commande>` (ou `/bash`)**
  - **Description :** Shell serveur avec persistance du répertoire de travail (`cd`), délai d'expiration de 35 secondes, environnement pré-authentifié et envoi des logs volumineux (>3500 caractères) sous forme de fichier `.log`.
  - **Exemple :** `/sh df -h && uptime` ou `/sh cd src && ls -la`
  - **Permission :** Uniquement Master Admin (les commandes destructives sont bloquées en permanence).
* **`/e2b <code_source>`**
  - **Description :** Exécution isolée de code Python ou JavaScript dans des micro-conteneurs cloud E2B sans aucun risque pour le serveur.
  - **Permission :** Uniquement Master Admin.
* **`/e2bsh <commande>`**
  - **Description :** Exécute des commandes bash dans l'environnement sandbox distant E2B.
  - **Permission :** Uniquement Master Admin.
* **`/e2bstatus`**
  - **Description :** Rapporte l'état de connexion et la validité du client cloud E2B.
  - **Permission :** Uniquement Master Admin.
* **`/set_e2b <clé>`**
  - **Description :** Définit ou met à jour la clé API E2B dans la session administrateur.
  - **Permission :** Uniquement Master Admin.
* **`/set_github <token>`**
  - **Description :** Enregistre ou met à jour le token GitHub personnel pour la création de dépôts et les commits.
  - **Permission :** Uniquement Master Admin.

### 7. Administration des Utilisateurs et Quotas
* **`/limit`**
  - **Description :** Affiche la consommation quotidienne de requêtes IA et le solde restant (40 par défaut, réinitialisation à 00:00 UTC).
  - **Permission :** Public (le Master Admin dispose d'un quota illimité).
* **`/setquota <id_utilisateur> <limite>`**
  - **Description :** Personnalise le quota quotidien d'un utilisateur spécifique.
  - **Exemple :** `/setquota 123456789 100`
  - **Permission :** Uniquement Master Admin.
* **`/resetquota <id_utilisateur>`**
  - **Description :** Remet immédiatement à zéro le compteur de consommation d'un utilisateur.
  - **Permission :** Uniquement Master Admin.
* **`/ban <cible>`**
  - **Description :** Bannit définitivement un utilisateur sur toutes les couches du bot et D1 par identifiant, pseudonyme ou citation.
  - **Permission :** Uniquement Master Admin.
* **`/unban <cible>`**
  - **Description :** Débannit un utilisateur et rétablit ses accès.
  - **Permission :** Uniquement Master Admin.
* **`/mute` et `/unmute`**
  - **Description :** Réduit au silence ou réactive la parole d'un utilisateur dans le groupe.
  - **Permission :** Master Admin et administrateurs du groupe.
* **`/mutelist`**
  - **Description :** Liste des utilisateurs réduits au silence dans le groupe actuel.
  - **Permission :** Master Admin et administrateurs du groupe.

### 8. Opérations de Groupes et Réseau
* **`/admin` (ou `/panel`)**
  - **Description :** Panneau de contrôle administrateur affichant les métriques CPU, RAM, D1 et l'état des services.
  - **Permission :** Uniquement Master Admin.
* **`/groups`**
  - **Description :** Liste complète des groupes rejoints par le bot avec leur statut (`active` ou `pending`).
  - **Permission :** Uniquement Master Admin.
* **`/leave <id_groupe>`**
  - **Description :** Ordonne au bot de quitter proprement un groupe ciblé sans supprimer l'historique archivé.
  - **Permission :** Uniquement Master Admin.
* **`/bangroup <id_groupe>`**
  - **Description :** Bannit définitivement un groupe, force la sortie immédiate du bot et bloque toute réinvitation.
  - **Permission :** Uniquement Master Admin.
* **`/channels`**
  - **Description :** Liste les canaux publics ou connectés surveillés par le bot.
  - **Permission :** Uniquement Master Admin.
* **`/net`**
  - **Description :** Diagnostique la connectivité réseau du serveur et évalue les accès aux API globales.
  - **Permission :** Uniquement Master Admin.
* **`/remember <clé> <valeur>`**
  - **Description :** Enregistre une règle immuable, un fait ou une consigne permanente dans la mémoire du bot (`manage_admin_memory`).
  - **Permission :** Uniquement Master Admin.
* **`/forget <clé>`**
  - **Description :** Supprime une consigne enregistrée de la mémoire permanente.
  - **Permission :** Uniquement Master Admin.

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
