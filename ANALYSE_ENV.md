# Analyse complète de la configuration .env

## ❌ PROBLÈMES CRITIQUES À CORRIGER

### 1. URL RPC malformée
Dans votre `RPC_ENDPOINTS`, il y a une URL malformée :
```
https://your-quicknode-endpoint.quiknode.pro/https://cosmopolitan-attentive-owl...
```
**Correction :**
```bash
RPC_ENDPOINTS=https://mainnet.helius-rpc.com/?api-key=6d85aa12-96df-4a2a-831c-d502ef7fc969,https://cosmopolitan-attentive-owl.solana-mainnet.quiknode.pro/c9080bcf53e4124594753c3181f563fddc845bb6/,https://api.mainnet-beta.solana.com
```

### 2. Variables manquantes importantes

#### Rapports Discord (IMPORTANT pour visibilité)
```bash
# Délai avant le premier rapport (0 = immédiat)
REPORT_INITIAL_DELAY_SECONDS=0

# Intervalle minimum entre rapports détaillés (600 = 10 min)
REPORT_MIN_INTERVAL_SECONDS=600

# Heartbeat Discord (900 = 15 min, 0 = désactivé)
HEARTBEAT_INTERVAL_SECONDS=900
```

#### Watchlist (IMPORTANT pour performance)
```bash
# Taille max watchlist (100 = recommandé)
WATCHLIST_MAX_SIZE=100

# TTL watchlist en secondes (3600 = 1h)
WATCHLIST_TTL_SEC=3600
```

#### Alertes (IMPORTANT pour fonctionnement)
```bash
# Taille batch alertes (10 = recommandé)
ALERT_BATCH_SIZE=10

# TTL état en secondes (3600 = 1h)
STATE_TTL_SECONDS=3600

# Max signatures en cache (50000 = recommandé)
MAX_SEEN_SIGNATURES=50000
```

#### DaaS (IMPORTANT si vous utilisez l'API)
```bash
# Mode DaaS activé
DAAS_MODE=true

# Afficher prompt upgrade dans Discord
INCLUDE_PAYWALL_PROMPT=true

# Port API (si vous utilisez l'API)
API_PORT=8002

# Host API
API_HOST=0.0.0.0

# Rate limits par tier
RATE_LIMIT_FREE=10
RATE_LIMIT_PRO=1000
RATE_LIMIT_ELITE=10000
```

## ⚠️ Variables optionnelles (bonnes valeurs par défaut)

### RPC avancé (circuit breaker)
```bash
# Circuit breaker (déjà bon par défaut)
RPC_CIRCUIT_BREAKER_FAILURES=3
RPC_CIRCUIT_BREAKER_PAUSE_SEC=5.0
RPC_RETRY_JITTER_BASE=0.5
RPC_RETRY_JITTER_MAX=0.2
```

### Logging
```bash
LOG_LEVEL=INFO
LOG_JSON_INDENT=0
LOG_MAX_BYTES=10000000
```

### Métriques
```bash
BALANCE_TOLERANCE_PCT=10.0
ALERT_DURATION_BUCKETS=0.5,1,2,5,10
```

### Stripe (si billing activé)
```bash
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
FAKE_CHECKOUT_ENABLED=true
```

## ✅ Variables présentes (correctes)

- COPY_TRADER_ENABLED ✓
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

## 📋 Configuration complète recommandée

Ajoutez ces sections à votre `.env` :

```bash
# ============================================
# RAPPORTS PÉRIODIQUES
# ============================================
REPORT_INITIAL_DELAY_SECONDS=0
REPORT_MIN_INTERVAL_SECONDS=600
HEARTBEAT_INTERVAL_SECONDS=900

# ============================================
# WATCHLIST
# ============================================
WATCHLIST_MAX_SIZE=100
WATCHLIST_TTL_SEC=3600

# ============================================
# ALERTES AVANCÉES
# ============================================
ALERT_BATCH_SIZE=10
STATE_TTL_SECONDS=3600
MAX_SEEN_SIGNATURES=50000

# ============================================
# DAAS / API
# ============================================
DAAS_MODE=true
INCLUDE_PAYWALL_PROMPT=true
API_PORT=8002
API_HOST=0.0.0.0
RATE_LIMIT_FREE=10
RATE_LIMIT_PRO=1000
RATE_LIMIT_ELITE=10000

# ============================================
# RPC AVANCÉ (Circuit Breaker)
# ============================================
RPC_CIRCUIT_BREAKER_FAILURES=3
RPC_CIRCUIT_BREAKER_PAUSE_SEC=5.0
RPC_RETRY_JITTER_BASE=0.5
RPC_RETRY_JITTER_MAX=0.2
```

## 🎯 Résumé

**Problèmes critiques :**
1. ❌ URL RPC malformée (à corriger)
2. ❌ Variables rapports Discord manquantes (REPORT_INITIAL_DELAY_SECONDS, REPORT_MIN_INTERVAL_SECONDS, HEARTBEAT_INTERVAL_SECONDS)
3. ❌ Variables watchlist manquantes (WATCHLIST_MAX_SIZE, WATCHLIST_TTL_SEC)
4. ❌ Variables alertes manquantes (ALERT_BATCH_SIZE, STATE_TTL_SECONDS, MAX_SEEN_SIGNATURES)
5. ❌ Variables DaaS manquantes (DAAS_MODE, INCLUDE_PAYWALL_PROMPT)

**Variables optionnelles :** Les valeurs par défaut sont bonnes, mais vous pouvez les ajouter pour un contrôle fin.

