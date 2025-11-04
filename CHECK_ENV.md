# Vérification de la configuration .env

## ⚠️ PROBLÈMES DÉTECTÉS

### 1. URL RPC malformée
Dans votre `RPC_ENDPOINTS`, il y a une URL malformée :
```
https://your-quicknode-endpoint.quiknode.pro/https://cosmopolitan-attentive-owl...
```
Il y a deux URLs collées. Corrigez en :
```
RPC_ENDPOINTS=https://mainnet.helius-rpc.com/?api-key=6d85aa12-96df-4a2a-831c-d502ef7fc969,https://cosmopolitan-attentive-owl.solana-mainnet.quiknode.pro/c9080bcf53e4124594753c3181f563fddc845bb6/,https://api.mainnet-beta.solana.com
```

### 2. Variables manquantes (optionnelles mais recommandées)

#### Rapports Discord
```bash
# Délai avant le premier rapport (0 = immédiat)
REPORT_INITIAL_DELAY_SECONDS=0

# Intervalle minimum entre rapports détaillés (600 = 10 min)
REPORT_MIN_INTERVAL_SECONDS=600

# Heartbeat Discord (900 = 15 min, 0 = désactivé)
HEARTBEAT_INTERVAL_SECONDS=900
```

#### RPC avancé (circuit breaker)
```bash
# Nombre d'échecs avant circuit breaker
RPC_CIRCUIT_BREAKER_FAILURES=3

# Pause circuit breaker (secondes)
RPC_CIRCUIT_BREAKER_PAUSE_SEC=5.0

# Jitter pour retry (améliore la distribution)
RPC_RETRY_JITTER_BASE=0.5
RPC_RETRY_JITTER_MAX=0.2
```

#### Watchlist
```bash
# Taille max watchlist
WATCHLIST_MAX_SIZE=100

# TTL watchlist (secondes)
WATCHLIST_TTL_SEC=3600
```

#### Alertes
```bash
# Taille batch alertes
ALERT_BATCH_SIZE=10

# TTL état (signatures vues)
STATE_TTL_SECONDS=3600

# Max signatures en cache
MAX_SEEN_SIGNATURES=50000

# Afficher prompt upgrade dans Discord
INCLUDE_PAYWALL_PROMPT=true
```

#### DaaS/API (si vous utilisez l'API)
```bash
# Mode DaaS
DAAS_MODE=true

# API Port
API_PORT=8002

# API Host
API_HOST=0.0.0.0

# Rate limits par tier
RATE_LIMIT_FREE=10
RATE_LIMIT_PRO=1000
RATE_LIMIT_ELITE=10000

# Stripe (si billing activé)
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
FAKE_CHECKOUT_ENABLED=true
```

#### Logging (optionnel)
```bash
# Niveau de log
LOG_LEVEL=INFO

# Indentation JSON logs
LOG_JSON_INDENT=0

# Taille max logs
LOG_MAX_BYTES=10000000
```

#### Métriques (optionnel)
```bash
# Tolérance balance (%)
BALANCE_TOLERANCE_PCT=10.0

# Buckets durée alertes
ALERT_DURATION_BUCKETS=0.5,1,2,5,10
```

## ✅ Variables présentes (correctes)

- COPY_TRADER_ENABLED ✓
- RPC_ENDPOINTS ✓ (à corriger)
- RPC_MODE ✓
- FIXTURES_DIR ✓
- PROFIT_ALERT_THRESHOLD ✓
- TX_LOOKBACK ✓
- TX_REFRESH_SECONDS ✓
- REPORT_REFRESH_SECONDS ✓
- GAIN_FILTER ✓
- WIN_RATE_FILTER ✓
- NEW_WALLET_GAIN ✓
- NEW_WALLET_MIN_TRX ✓
- ALERT_COOLDOWN_SEC ✓
- DRY_RUN ✓
- DISCORD_WEBHOOK ✓
- MAX_CONCURRENCY ✓
- RPC_TIMEOUT_SEC ✓
- RPC_MAX_RETRIES ✓
- PROMETHEUS_PORT ✓
- BIRDEYE_API_KEY ✓
- DEBUG_FORCE_ALERT ✓
- DEBUG_FORCE_ALERT_WALLET ✓
- DEBUG_FORCE_ALERT_PROFIT ✓

## 📝 Configuration minimale recommandée

Pour un fonctionnement optimal, ajoutez au minimum :

```bash
# Rapports Discord
REPORT_INITIAL_DELAY_SECONDS=0
REPORT_MIN_INTERVAL_SECONDS=600
HEARTBEAT_INTERVAL_SECONDS=900

# Watchlist
WATCHLIST_MAX_SIZE=100
WATCHLIST_TTL_SEC=3600

# Alertes
ALERT_BATCH_SIZE=10
STATE_TTL_SECONDS=3600
MAX_SEEN_SIGNATURES=50000

# DaaS
DAAS_MODE=true
INCLUDE_PAYWALL_PROMPT=true
```

Les autres variables ont des valeurs par défaut raisonnables et ne sont nécessaires que pour un réglage fin.

