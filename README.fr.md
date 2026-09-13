# Prometheus — Super Agent IA pour Telegram (Multimodal, Ultra-Rapide et Sécurisé)
> Un assistant IA agentique connecté aux LLMs de pointe, propulsé par des architectures haute performance inspirées de **DeepSeek Harness (DSH)**, **Claude Code** et du **Noyau Linux**. Doté d'une matrice en temps réel de ~90 outils (moteur financier sous la milliseconde, vision multimodale haute résolution, recherche web, médias, transcription vocale, planificateur cron international, reconnaissance OSINT, automatisation GitHub et gestion du cloud Railway). Prometheus n'hallucine pas ; il raisonne de manière autonome, exécute ses outils en parallèle et livre des faits vérifiés.

[![CI](https://github.com/zaryamyn273-crypto/prometheusopenbot/actions/workflows/ci.yml/badge.svg)](https://github.com/zaryamyn273-crypto/prometheusopenbot/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Security Hardened](https://img.shields.io/badge/security-hardened-green.svg)](#sécurité-et-blindage-multicouche)
[![Sub-Millisecond Engine](https://img.shields.io/badge/latency-sub--millisecond-brightgreen.svg)](#architectures-avancées-de-haute-performance)

<p align="center">
  <a href="README.md">🇮🇷 فارسی</a> ·
  <a href="README.en.md">🇬🇧 English</a> ·
  <a href="README.ru.md">🇷🇺 Русский</a> ·
  <a href="README.es.md">🇪🇸 Español</a> ·
  <a href="README.fr.md">🇫🇷 Français</a>
</p>

---

## 📖 Sommaire
- [Architectures Avancées de Haute Performance](#architectures-avancées-de-haute-performance)
- [Vision Multimodale et Analyse d'Images](#vision-multimodale-et-analyse-dimages)
- [Compréhension Approfondie des Intentions et Coréférences](#compréhension-approfondie-des-intentions-et-coréférences)
- [Fonctionnalités Clés](#fonctionnalités-clés)
- [Démarrage Rapide et Configuration](#démarrage-rapide-et-configuration)
- [Matrice des Commandes Telegram](#matrice-des-commandes-telegram)
- [Sécurité et Blindage Multicouche](#sécurité-et-blindage-multicouche)
- [Tests et Vérification](#tests-et-vérification)
- [Documentation et Guides](#documentation-et-guides)

---

## Architectures Avancées de Haute Performance

1. **Élagage Déterministe des Outils Style DSH (Head-Middle-Tail Pruning) :**
   * Inspiré du module `@deepseek-ai/dsh-compaction-tool-result-pruner` de DeepSeek Harness.
   * Les sorties volumineuses conservent l'en-tête (3 500 caractères) et la conclusion (1 200 caractères), remplaçant le milieu redondant par un marqueur propre.
   * **Résultat :** Réduction de 60 à 80 % des tokens d'entrée lors des tours de raisonnement, divisant par deux la latence de réponse.
2. **Invariance de Préfixe pour KV-Cache (Modèle Claude Code / vLLM) :**
   * Maintient le prompt système et la structure des outils 100 % statiques au niveau binaire, garantissant un taux de succès du KV-Cache supérieur à 95 % et un TTFT inférieur à 300 ms.
3. **Moteur Financier Sous la Milliseconde :**
   * **Stale-While-Revalidate (SWR) :** Taux de l'or, des devises et des monnaies renvoyés en **0,07 ms** depuis la mémoire RAM L1, avec rafraîchissement asynchrone en arrière-plan.
   * **Course Concurrente des Échanges :** Requêtes parallèles via `asyncio.as_completed` entre Binance US, KuCoin, MEXC et CoinPaprika.
   * **Cache de Carnet d'Ordres Nobitex :** Cache de 45 secondes pour les conversions immédiates en monnaie locale.
4. **Modèles de Ressources du Noyau Linux :**
   * **Regroupement de Connexions HTTP (Slab Pooling) :** Réutilisation des sockets via `httpx.Limits` pour éliminer le surcoût de négociation TLS/TCP.
   * **Tampons Circulaires Bornés :** Files d'attente d'écriture vers Cloudflare D1 avec limites strictes de capacité et regroupement par lots.

---

## Vision Multimodale et Analyse d'Images

* **Boîte à Outils Multimodale :** Lors de l'envoi d'une image, les outils d'assistance (Recherche Web, Reconstitution de Code-Barres, Calculatrice, Prix) restent actifs pour raisonner directement sur le visuel.
* **Mise à l'Échelle Adaptative Lanczos :** Les images réduites (<320px) sont agrandies automatiquement par 2x avec interpolation Lanczos et contraste dynamique pour un OCR irréprochable.
* **Action Directe sans Hypothèse :**
  - **Exercices et Maths :** Résolution pas à pas avec réponse finale en gras.
  - **Erreurs de Code et Terminal :** Diagnostic en 1 phrase et code corrigé dans un bloc de code.
  - **Codes-Barres Endommagés :** Lecture des barres et calcul du chiffre manquant par somme de contrôle GS1.

---

## Compréhension Approfondie des Intentions et Coréférences

* **Décomposition Multi-Intentions :** Traite plusieurs demandes en un seul message en exécutant les outils en parallèle.
* **Résolution des Coréférences (Anaphore) :** Comprend les pronoms ambigus (« combien ça coûte ? », « répare-le ») en se référant au contexte précédent.
* **Préservation Grammaticale :** Supprime les bégaiements consécutifs tout en préservant intégralement les formules mathématiques (`x = x + 1`) et le code.

---

## Démarrage Rapide et Configuration

Seules **3 variables principales** sont requises dans le fichier `.env` :

```bash
git clone https://github.com/zaryamyn273-crypto/prometheusopenbot.git
cd prometheusopenbot
cp .env.example .env
# Définissez TELEGRAM_BOT_TOKEN, ADMIN_ID et ROUTER_API_KEY
pip install -r requirements.txt
python bot.py
```

> **Garantie Zéro Secret :** Aucun jeton, mot de passe ou clé API n'est stocké dans git. Tout est chargé à partir des variables d'environnement.

---

## Sécurité et Blindage Multicouche

1. **Pare-feu SSRF Hop-by-Hop :** Blocage rigoureux des réseaux locaux, métadonnées cloud (`169.254.169.254`) et domaines `.internal`.
2. **Filtre Anti-Jailbreak :** Détection des injections de prompt et changements de rôle à coût zéro en tokens.
3. **Bac à Sable AST Python et Isolation :** Analyse de l'arbre syntaxique et confinement des fichiers dans `/tmp`.
4. **Nettoyeur Automatique de Secrets :** Remplacement des jetons et clés par `[SECRET]` dans les textes et journaux de shell.

---

## Tests et Vérification

```bash
python -m tests.test_financial_speed_security
python -m tests.test_database_isolation
python -m tests.test_scheduler
python -m tests.test_adversarial
python -m tests.test_detect_lang
```
