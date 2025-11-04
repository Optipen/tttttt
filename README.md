# Wallet Monitor Bot - Data-as-a-Service (DaaS)

Service Data-as-a-Service (DaaS) vendant des signaux de trading en temps réel pour Solana via API REST et webhooks Discord. Surveillance de wallets en temps réel avec calcul de profit enrichi et alertes différenciées par tier (Free/Pro/Elite).

## Structure du projet

```
trading/
├── src/                    # Code source principal
│   ├── __init__.py
│   ├── wallet_monitor.py   # Bot principal
│   ├── profit_estimator.py # Module calcul PnL
│   ├── config.py           # Configuration centralisée
│   ├── copy_trader.py      # Module copy-trading (optionnel)
│   ├── api_auth.py         # Authentification API
│   ├── api_service.py      # Service API REST
│   ├── billing.py          # Module billing DaaS
│   └── rate_limiter.py    # Rate limiting par tier
├── tests/                  # Tests unitaires et d'intégration
│   ├── conftest.py
│   ├── fixtures/           # Fixtures pour tests
│   │   ├── signatures/
│   │   └── transactions/
│   └── test_*.py
├── config/                 # Configuration
│   ├── docker-compose.yml
│   ├── Dockerfile
│   ├── env.template
│   └── infra/
│       ├── prometheus/
│       │   ├── prometheus.yml
│       │   └── alert.rules.yml
│       └── grafana/
│           └── dashboard.json
├── scripts/                # Scripts utilitaires
│   ├── analyze_metrics.ps1
│   ├── clean.sh
│   └── monitor_metrics.ps1
├── data/                   # Données initiales
│   └── wallets_complete_final.json
├── .github/
│   └── workflows/
│       └── ci.yml
├── requirements.txt
└── pyproject.toml
```

## Installation

### Prérequis

- Python 3.11+
- Docker & Docker Compose (optionnel)

### Installation locale

```bash
# Cloner le dépôt
git clone <repo-url>
cd trading

# Installer les dépendances
pip install -r requirements.txt

# Copier le template d'environnement
cp config/env.template .env

# Éditer .env avec vos paramètres
# Notamment : RPC_ENDPOINTS, DISCORD_WEBHOOK, etc.
```

### Installation Docker

```bash
# Créer .env depuis le template
cp config/env.template config/.env

# Lancer avec Docker Compose
cd config
docker compose up -d --build
```

## Configuration

### Variables d'environnement principales

**DaaS**:
| Variable | Description | Défaut |
|----------|-------------|--------|
| `DAAS_MODE` | Mode DaaS activé | `true` |
| `DRY_RUN` | Mode lecture seule (pas d'envoi) | `true` |
| `COPY_TRADER_ENABLED` | Active copy-trader (⚠️ désactivé par défaut) | `false` |
| `INCLUDE_PAYWALL_PROMPT` | Afficher CTA Upgrade dans Discord | `true` |

**RPC & APIs**:
| Variable | Description | Défaut |
|----------|-------------|--------|
| `RPC_ENDPOINTS` | Endpoints RPC Solana (virgule) | `api.mainnet-beta.solana.com` |
| `RPC_MODE` | Mode: `live` ou `fixtures` | `live` |
| `DISCORD_WEBHOOK` | URL webhook Discord | `` |
| `BIRDEYE_API_KEY` | Clé API Birdeye (optionnel) | `` |

**API & Billing**:
| Variable | Description | Défaut |
|----------|-------------|--------|
| `API_PORT` | Port serveur API | `8002` |
| `API_HOST` | Host serveur API | `0.0.0.0` |
| `RATE_LIMIT_FREE` | Limite appels/jour free | `10` |
| `RATE_LIMIT_PRO` | Limite appels/jour pro | `1000` |
| `RATE_LIMIT_ELITE` | Limite appels/jour elite | `10000` |
| `STRIPE_SECRET_KEY` | Clé secrète Stripe | `` |
| `STRIPE_WEBHOOK_SECRET` | Secret webhook Stripe | `` |
| `FAKE_CHECKOUT_ENABLED` | Activer fake checkout (MVP) | `true` |

**Alerting**:
| Variable | Description | Défaut |
|----------|-------------|--------|
| `PROFIT_ALERT_THRESHOLD` | Seuil profit pour alerte (SOL) | `2.0` |
| `GAIN_FILTER` | Filtre gain minimum wallets | `5.0` |
| `WIN_RATE_FILTER` | Filtre win rate minimum wallets | `80.0` |
| `WATCHLIST_MAX_SIZE` | Taille max watchlist | `100` |

Voir `config/env.template` pour la liste complète.

## Utilisation

### Mode local

```bash
# Lancer le service DaaS (DRY_RUN=True par défaut)
python -m src.wallet_monitor

# Avec variables d'env personnalisées
RPC_MODE=fixtures DISCORD_WEBHOOK=https://discord.com/api/webhooks/... python -m src.wallet_monitor
```

### Fake Checkout (MVP)

Pour tester le système de billing sans Stripe réel :

```bash
# Créer une API key via fake checkout
curl -X POST http://localhost:8002/api/v1/billing/fake-checkout \
  -H "Content-Type: application/json" \
  -d '{"tier": "pro", "email": "test@example.com"}'

# Utiliser l'API key retournée pour appels API
curl -H "x-api-key: <api_key>" http://localhost:8002/api/v1/signals
```

### Mode Docker

```bash
cd config
docker compose up -d

# Voir les logs
docker logs wallet-monitor -f

# Arrêter
docker compose down
```

## Tests

```bash
# Tous les tests
pytest tests/ -v

# Tests avec coverage
pytest --cov=src --cov-report=html

# Tests spécifiques
pytest tests/test_profit_estimator_improvements.py -v
```

## Observabilité

### Métriques Prometheus

- Port : `8000` (configurable via `PROMETHEUS_PORT`)
- Endpoint : `http://localhost:8000/metrics`

### Métriques principales

**Existant**:
- `wallet_app_up` : État de l'application (1 = up)
- `wallet_watchlist_size` : Taille de la watchlist
- `wallet_alerts_total{wallet}` : Nombre d'alertes par wallet
- `wallet_last_profit_sol{wallet}` : Dernier profit détecté
- `wallet_rpc_latency_seconds{method}` : Latence RPC par méthode
- `wallet_rpc_error_count{endpoint}` : Erreurs RPC par endpoint
- `wallet_cache_size{cache}` : Taille des caches
- `wallet_alert_duration_seconds` : Durée de traitement d'une alerte

**DaaS** (nouvelles):
- `signals_sent_total{tier}` : Nombre de signaux envoyés par tier
- `api_calls_total{endpoint,tier}` : Appels API par endpoint et tier
- `active_subscriptions_total{tier}` : Abonnements actifs par tier
- `stripe_webhooks_processed_total{event}` : Webhooks Stripe traités
- `disclaimer_shown_total{output_type}` : Disclaimers affichés

### Healthcheck

- Port : `8001`
- Endpoint : `http://localhost:8001/healthz`
- Réponse : JSON avec métriques (`status`, `loop_ts`, `watchlist_size`, `last_profit`, `dry_run`, `daas_mode`)

### API Service

- Port : `8002` (configurable via `API_PORT`)
- Endpoint : `http://localhost:8002/api/v1/*`
- Authentification : Header `x-api-key` requis

### Grafana

- Port : `3000`
- Dashboard : `config/infra/grafana/dashboard.json`

### Prometheus

- Port : `9090`
- Config : `config/infra/prometheus/prometheus.yml`
- Règles : `config/infra/prometheus/alert.rules.yml`

## Fonctionnalités

### Surveillance en temps réel

- Scan async de wallets Solana
- Détection de transactions rentables
- Calcul PnL avec support multi-hop et tokens
- Normalisation WSOL → SOL natif

### Alertes

- Discord webhook (optionnel)
- Filtrage par cooldown et idempotence
- Métriques Prometheus
- Rapport initial Discord pour valider la configuration (`REPORT_INITIAL_DELAY_SECONDS`)
- Heartbeat visuel configurable sur Discord (`HEARTBEAT_INTERVAL_SECONDS`)
- Rapports détaillés périodiques envoyés/archivés (`REPORT_MIN_INTERVAL_SECONDS`, `REPORT_REFRESH_SECONDS`)

### Copy-trading (optionnel)

- Simulation de positions basée sur les alertes
- Gestion de portefeuille fictif
- Détection de ventes pour fermer positions

### Performance

- Parallélisme async avec backpressure
- Circuit-breaker RPC avec rotation automatique
- Gestion LRU de la watchlist
- Garbage collector d'état avec TTL

## Développement

### Pre-commit

```bash
# Installer pre-commit hooks
pre-commit install

# Exécuter manuellement
pre-commit run --all-files
```

### CI/CD

Le workflow GitHub Actions exécute automatiquement :
- Lint (ruff, mypy, black, isort)
- Tests (pytest avec coverage)
- Build Docker

### Structure du code

- `src/wallet_monitor.py` : Boucle principale async, scan wallets, alerting
- `src/profit_estimator.py` : Calcul PnL avec tokens multi-hop
- `src/config.py` : Configuration centralisée
- `src/copy_trader.py` : Module copy-trading fictif

## Fichiers générés (non versionnés)

Les fichiers suivants sont générés automatiquement et ne doivent pas être versionnés :

- **Bases de données runtime** : `*.db`, `*_state.db`
  - `wallet_monitor_state.db` : Persistance état (SQLite)
  - `token_price_cache.db` : Cache prix tokens (SQLite)
  - `copy_trader.db` : Base copy-trading (SQLite)
- **Caches/tests** : `__pycache__/`, `.pytest_cache/`, `htmlcov/`
- **Logs** : `*.log`, `wallet_activity_log.json`
- **Rapports** : `wallet_dashboard_live.csv`, `wallet_report.md`

Utilisez `scripts/clean.sh` pour un ménage rapide.

## Support

Pour toute question ou problème, ouvrir une issue sur le dépôt.

---

**Version** : 1.0.0  
**Licence** : Voir fichier LICENSE



