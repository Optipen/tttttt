"""Centralisation de la configuration dynamique du bot."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


def _env_bool(name: str, default: bool = False) -> bool:
    """Retourne un booléen à partir d'une variable d'environnement."""

    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: List[str] | None = None) -> List[str]:
    value = os.getenv(name)
    if value is None:
        return default[:] if default else []
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Paths:
    # [CLEANUP] : Chemins mis à jour pour la nouvelle structure
    data_file: Path = Path("data/wallets_complete_final.json")
    log_file: Path = Path("wallet_activity_log.json")  # Généré automatiquement
    dashboard_csv: Path = Path("wallet_dashboard_live.csv")  # Généré automatiquement
    report_md: Path = Path("wallet_report.md")  # Généré automatiquement
    state_db: Path = Path("wallet_monitor_state.db")  # Généré automatiquement
    fixtures_dir: Path = Path(os.getenv("FIXTURES_DIR", "tests/fixtures"))
    token_cache_db: Path = Path("token_price_cache.db")  # Généré automatiquement


@dataclass(frozen=True)
class RpcConfig:
    timeout_sec: float = float(os.getenv("RPC_TIMEOUT_SEC", "2.5"))
    max_retries: int = int(os.getenv("RPC_MAX_RETRIES", "3"))
    endpoints: List[str] = field(
        default_factory=lambda: _env_list("RPC_ENDPOINTS", ["https://api.mainnet-beta.solana.com"])
    )
    circuit_breaker_failures: int = int(os.getenv("RPC_CIRCUIT_BREAKER_FAILURES", "3"))
    circuit_breaker_pause_sec: float = float(os.getenv("RPC_CIRCUIT_BREAKER_PAUSE_SEC", "5.0"))
    jitter_base: float = float(os.getenv("RPC_RETRY_JITTER_BASE", "0.5"))
    jitter_max: float = float(os.getenv("RPC_RETRY_JITTER_MAX", "0.2"))


@dataclass(frozen=True)
class AlertingConfig:
    profit_threshold: float = float(os.getenv("PROFIT_ALERT_THRESHOLD", "2.0"))
    gain_filter: float = float(os.getenv("GAIN_FILTER", "5.0"))
    win_rate_filter: float = float(os.getenv("WIN_RATE_FILTER", "80.0"))
    cooldown_sec: int = int(os.getenv("ALERT_COOLDOWN_SEC", "300"))
    new_wallet_gain: float = float(os.getenv("NEW_WALLET_GAIN", "7.0"))
    new_wallet_min_trx: int = int(os.getenv("NEW_WALLET_MIN_TRX", "12"))
    watchlist_max_size: int = int(os.getenv("WATCHLIST_MAX_SIZE", "100"))
    watchlist_ttl_sec: int = int(os.getenv("WATCHLIST_TTL_SEC", str(3600)))
    alert_batch_size: int = int(os.getenv("ALERT_BATCH_SIZE", "10"))
    # [DAAS] DRY_RUN=True par défaut pour sécurité (mode données uniquement)
    dry_run: bool = _env_bool("DRY_RUN", True)
    state_ttl_seconds: int = int(os.getenv("STATE_TTL_SECONDS", "3600"))
    max_seen_signatures: int = int(os.getenv("MAX_SEEN_SIGNATURES", "50000"))
    include_paywall_prompt: bool = _env_bool("INCLUDE_PAYWALL_PROMPT", True)


@dataclass(frozen=True)
class MetricsConfig:
    prometheus_port: int = int(os.getenv("PROMETHEUS_PORT", "8000"))
    balance_tolerance_pct: float = float(os.getenv("BALANCE_TOLERANCE_PCT", "10.0"))
    alert_duration_summary_buckets: str = os.getenv("ALERT_DURATION_BUCKETS", "0.5,1,2,5,10")


@dataclass(frozen=True)
class LoopConfig:
    tx_refresh_seconds: int = int(os.getenv("TX_REFRESH_SECONDS", "60"))
    tx_lookback: int = int(os.getenv("TX_LOOKBACK", "20"))
    # Par défaut 600s (10 min) pour plus de visibilité, était 1800s (30 min)
    report_refresh_seconds: int = int(os.getenv("REPORT_REFRESH_SECONDS", "600"))
    max_concurrency: int = int(os.getenv("MAX_CONCURRENCY", "10"))


@dataclass(frozen=True)
class LoggingConfig:
    level: str = os.getenv("LOG_LEVEL", "INFO")
    json_indent: int | None = int(os.getenv("LOG_JSON_INDENT", "0")) or None


@dataclass(frozen=True)
class BillingConfig:
    stripe_secret_key: str = os.getenv("STRIPE_SECRET_KEY", "").strip()
    stripe_webhook_secret: str = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
    fake_checkout_enabled: bool = _env_bool("FAKE_CHECKOUT_ENABLED", True)
    api_keys_db: Path = Path("daas_api_keys.db")


@dataclass(frozen=True)
class ApiConfig:
    api_port: int = int(os.getenv("API_PORT", "8002"))
    api_host: str = os.getenv("API_HOST", "0.0.0.0")
    rate_limit_free: int = int(os.getenv("RATE_LIMIT_FREE", "10"))
    rate_limit_pro: int = int(os.getenv("RATE_LIMIT_PRO", "1000"))
    rate_limit_elite: int = int(os.getenv("RATE_LIMIT_ELITE", "10000"))


@dataclass(frozen=True)
class BotConfig:
    paths: Paths = Paths()
    rpc: RpcConfig = RpcConfig()
    alerting: AlertingConfig = AlertingConfig()
    metrics: MetricsConfig = MetricsConfig()
    loop: LoopConfig = LoopConfig()
    logging: LoggingConfig = LoggingConfig()
    billing: BillingConfig = BillingConfig()
    api: ApiConfig = ApiConfig()
    rpc_mode: str = os.getenv("RPC_MODE", "live").strip().lower()
    discord_webhook: str = os.getenv("DISCORD_WEBHOOK", "").strip()
    log_max_bytes: int = int(os.getenv("LOG_MAX_BYTES", str(10_000_000)))
    # [DAAS] Copy-trader désactivé par défaut (mode données uniquement)
    copy_trader_enabled: bool = _env_bool("COPY_TRADER_ENABLED", False)
    # [DAAS] Mode DaaS activé par défaut
    daas_mode: bool = _env_bool("DAAS_MODE", True)

    @property
    def rpc_endpoints(self) -> List[str]:
        endpoints = self.rpc.endpoints
        if not endpoints:
            return ["https://api.mainnet-beta.solana.com"]
        return endpoints


CONFIG = BotConfig()


def validate_data_file(path: Path) -> bool:
    """Valide le fichier wallets JSON; retourne False si invalide."""

    try:
        if not path.exists():
            return False
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return False
        data = json.loads(text)
        if "wallets" not in data:
            return False
        if not isinstance(data["wallets"], list):
            return False
        return True
    except Exception:
        return False
