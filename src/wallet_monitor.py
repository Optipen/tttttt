#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Radar on-chain temps réel pour Solana."""

import asyncio
import atexit
import datetime as dt
import json
import logging
import math
import os
import random
import signal
import sqlite3
import statistics
import sys
import time
from collections import Counter as CollCounter
from collections import OrderedDict, defaultdict, deque
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

import aiohttp
import pandas as pd
from prometheus_client import Counter, Gauge, Histogram, Summary, start_http_server
from solana.exceptions import SolanaRpcException
from solana.rpc.api import Client
from solders.pubkey import Pubkey

from .config import CONFIG, _env_bool, validate_data_file

# Import profit estimator enrichi
# [CLEANUP] : Imports relatifs pour la nouvelle structure
from .profit_estimator import TokenPriceCache, estimate_profit_enriched

# [FIX_AUDIT_1] : Centralisation de la configuration via module CONFIG

# Configuration depuis CONFIG (après import)
FIXTURES_DIR = CONFIG.paths.fixtures_dir
RPC_TIMEOUT_SEC = CONFIG.rpc.timeout_sec
RPC_MAX_RETRIES = CONFIG.rpc.max_retries
RPC_CIRCUIT_BREAKER_FAILURES = CONFIG.rpc.circuit_breaker_failures
RPC_CIRCUIT_BREAKER_PAUSE_SEC = CONFIG.rpc.circuit_breaker_pause_sec
RETRY_JITTER_BASE = CONFIG.rpc.jitter_base
RETRY_JITTER_MAX = CONFIG.rpc.jitter_max
DRY_RUN = CONFIG.alerting.dry_run
ALERT_BATCH_SIZE = CONFIG.alerting.alert_batch_size

# Import copy-trader fictif
# [CLEANUP] : Import relatif pour la nouvelle structure
try:
    from .copy_trader import (
        close_position,
        get_open_positions,
        get_portfolio_summary,
        init_copy_trader,
        on_alert,
    )

    # [DAAS] Copy-trader désactivé par défaut (mode données uniquement)
    COPY_TRADER_ENABLED = CONFIG.copy_trader_enabled and not CONFIG.alerting.dry_run
except ImportError:
    COPY_TRADER_ENABLED = False

    def on_alert(*args, **kwargs):
        return None

    def init_copy_trader():
        return None

    def get_open_positions(*args, **kwargs):
        return []

    def close_position(*args, **kwargs):
        return None

    def get_portfolio_summary():
        return {}


# [FIX_AUDIT_2] : Logging structuré JSON
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": dt.datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if isinstance(record.args, dict):
            payload.update(record.args)
        for key, value in record.__dict__.items():
            if key in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "process",
                "processName",
                "stack_info",
            }:
                continue
            payload[key] = value
        return json.dumps(payload)


def setup_logging() -> logging.Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("wallet_monitor")
    logger.setLevel(CONFIG.logging.level.upper())
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.propagate = False
    return logger


LOGGER = setup_logging()

# [DAAS] Copy-trader désactivé par défaut (mode données uniquement)
if COPY_TRADER_ENABLED:
    LOGGER.warning(
        "⚠️ WARNING: Copy-trader activé - mode simulation uniquement", extra={"dry_run": DRY_RUN}
    )

# ------------------ Configuration & constantes ------------------

DATA_FILE = CONFIG.paths.data_file
LOG_FILE = CONFIG.paths.log_file
DASHBOARD_CSV = CONFIG.paths.dashboard_csv
REPORT_MD = CONFIG.paths.report_md
STATE_DB = CONFIG.paths.state_db
TOKEN_CACHE_DB = CONFIG.paths.token_cache_db

RPC_MODE = CONFIG.rpc_mode
RPC_ENDPOINTS = CONFIG.rpc_endpoints
TX_REFRESH_SECONDS = CONFIG.loop.tx_refresh_seconds
REPORT_REFRESH_SECONDS = CONFIG.loop.report_refresh_seconds
REPORT_INITIAL_DELAY_SECONDS = CONFIG.loop.report_initial_delay_seconds
REPORT_MIN_INTERVAL_SECONDS = CONFIG.loop.report_min_interval_seconds
HEARTBEAT_INTERVAL_SECONDS = CONFIG.loop.heartbeat_interval_seconds
TX_LOOKBACK = CONFIG.loop.tx_lookback
MAX_CONCURRENCY = CONFIG.loop.max_concurrency
PROFIT_ALERT_THRESHOLD = CONFIG.alerting.profit_threshold
GAIN_FILTER = CONFIG.alerting.gain_filter
WIN_RATE_FILTER = CONFIG.alerting.win_rate_filter
NEW_WALLET_GAIN = CONFIG.alerting.new_wallet_gain
NEW_WALLET_MIN_TRX = CONFIG.alerting.new_wallet_min_trx
ALERT_COOLDOWN_SEC = CONFIG.alerting.cooldown_sec
WATCHLIST_MAX_SIZE = CONFIG.alerting.watchlist_max_size
STATE_TTL_SECONDS = CONFIG.alerting.state_ttl_seconds
MAX_SEEN_SIGNATURES = CONFIG.alerting.max_seen_signatures
PROMETHEUS_PORT = CONFIG.metrics.prometheus_port
BALANCE_TOLERANCE_PCT = CONFIG.metrics.balance_tolerance_pct
LOG_MAX_BYTES = CONFIG.log_max_bytes
DISCORD_WEBHOOK = CONFIG.discord_webhook

WSOL_MINT = "So11111111111111111111111111111111111111112"

PROGRAM_MAP = {
    # AMMs / Aggregateurs
    "JUP4Fb2cqiRUcaTHdrPC8h2gK4G8cCxfXk8XQf2Zx1i": "Jupiter",
    "rvk5K9sH1t7h8GmHh5w7bqgTt3m1oJ2qkNoRayDiUM": "Raydium",
    "9xQeWvG816bUx9EPfDdC1WJ4VqV6g5Gz5X5H5Q5tLCH": "OpenBook",
    "orcaEKTdNdXBgaAwyQUpfCw9W7jfvAbzGt9xa1sG9W": "Orca",
    # NFTs / Marketplaces
    "tensorFLkNft111111111111111111111111111111": "Tensor",
    "MEisE1HzehtrDpAAT8PnLHjpSSkRYakotTuJRPjTpo8": "MagicEden",
    # Systèmes à ignorer
    "ComputeBudget111111111111111111111111111111": "System",
    "SysvarRent111111111111111111111111111111111": "System",
}

NFT_DEX = {"Tensor", "MagicEden", "Blur"}
AMM_DEX = {"Jupiter", "Raydium", "OpenBook", "Orca"}


class RpcManager:
    """RpcManager synchrone (legacy, gardé pour compatibilité)."""

    def __init__(self, endpoints: List[str]) -> None:
        self.endpoints = endpoints or ["https://api.mainnet-beta.solana.com"]
        self.index = 0
        self.client = Client(self.endpoints[self.index])
        self.circuit_state: Dict[str, Dict[str, float]] = defaultdict(
            lambda: {"failures": 0, "opened_at": 0.0, "state": "closed"}
        )

    def _current_endpoint(self) -> str:
        return self.endpoints[self.index]

    def _rotate(self) -> None:
        if len(self.endpoints) <= 1:
            return
        self.index = (self.index + 1) % len(self.endpoints)
        endpoint = self._current_endpoint()
        LOGGER.warning("rpc endpoint rotated", extra={"endpoint": endpoint})
        self.client = Client(endpoint)

    def _allow_request(self, endpoint: str) -> bool:
        state = self.circuit_state[endpoint]
        if state["state"] == "open":
            if time.time() - state["opened_at"] >= RPC_CIRCUIT_BREAKER_PAUSE_SEC:
                state["state"] = "half-open"
                return True
            return False
        return True

    def _record_failure(self, endpoint: str, code: str) -> None:
        state = self.circuit_state[endpoint]
        state["failures"] += 1
        record_rpc_error(endpoint, code)
        if state["failures"] >= RPC_CIRCUIT_BREAKER_FAILURES:
            state["state"] = "open"
            state["opened_at"] = time.time()
            LOGGER.warning("rpc circuit opened", extra={"endpoint": endpoint, "code": code})
            self._rotate()

    def _record_success(self, endpoint: str) -> None:
        state = self.circuit_state[endpoint]
        if state["failures"] or state["state"] != "closed":
            LOGGER.info("rpc circuit reset", extra={"endpoint": endpoint})
        state.update({"failures": 0, "opened_at": 0.0, "state": "closed"})

    def call(self, method: str, *args, **kwargs):
        if RPC_MODE == "fixtures":
            try:
                if method == "get_signatures_for_address":
                    wallet_pk = str(args[0]) if args else ""
                    path = FIXTURES_DIR / "signatures" / f"{wallet_pk}.json"
                    if path.exists():
                        with open(path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        return {"result": data}
                    return {"result": []}
                if method == "get_transaction":
                    sig = str(args[0])
                    path = FIXTURES_DIR / "transactions" / f"{sig}.json"
                    if path.exists():
                        with open(path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        return {"result": data}
                    return None
            except Exception as exc:
                LOGGER.warning("fixture load failure", extra={"error": str(exc)})
                return None

        with observe_latency(RPC_LATENCY, method=method):
            for attempt in range(RPC_MAX_RETRIES):
                endpoint = self._current_endpoint()
                if not self._allow_request(endpoint):
                    time.sleep(RPC_CIRCUIT_BREAKER_PAUSE_SEC)
                    self._rotate()
                    continue
                try:
                    fn = getattr(self.client, method)
                    result = fn(*args, **kwargs)
                    self._record_success(endpoint)
                    return result
                except SolanaRpcException as exc:
                    RPC_ERRORS.labels(endpoint=endpoint[:50], code="RPCException").inc()
                    LOGGER.warning(
                        "rpc call error",
                        extra={"endpoint": endpoint, "method": method, "error": str(exc)},
                    )
                    self._record_failure(endpoint, "RPCException")
                    return None
                except Exception as exc:
                    code = type(exc).__name__
                    RPC_ERRORS.labels(endpoint=endpoint[:50], code=code).inc()
                    LOGGER.warning(
                        "rpc call retry",
                        extra={
                            "endpoint": endpoint,
                            "method": method,
                            "error": code,
                            "attempt": attempt,
                        },
                    )
                    self._record_failure(endpoint, code)
                    time.sleep(compute_retry_delay(attempt))
            return None


class AsyncRpcManager:
    """RpcManager async avec aiohttp pour scan parallèle."""

    def __init__(
        self, endpoints: List[str], session: Optional[aiohttp.ClientSession] = None
    ) -> None:
        self.endpoints = endpoints or ["https://api.mainnet-beta.solana.com"]
        self.index = 0
        self.session = session
        self.failures = 0
        self._own_session = session is None
        self.circuit_state: Dict[str, Dict[str, float]] = defaultdict(
            lambda: {"failures": 0, "opened_at": 0.0, "state": "closed"}
        )

    async def __aenter__(self):
        if self._own_session:
            timeout = aiohttp.ClientTimeout(total=RPC_TIMEOUT_SEC)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._own_session and self.session:
            await self.session.close()

    def _current_endpoint(self) -> str:
        return self.endpoints[self.index]

    def _rotate(self) -> None:
        if len(self.endpoints) <= 1:
            return
        self.index = (self.index + 1) % len(self.endpoints)
        LOGGER.warning("rpc endpoint rotated", extra={"endpoint": self._current_endpoint()})

    def _allow_request(self, endpoint: str) -> bool:
        state = self.circuit_state[endpoint]
        if state["state"] == "open":
            if time.time() - state["opened_at"] >= RPC_CIRCUIT_BREAKER_PAUSE_SEC:
                state["state"] = "half-open"
                return True
            return False
        return True

    def _record_failure(self, endpoint: str, code: str) -> None:
        state = self.circuit_state[endpoint]
        state["failures"] += 1
        record_rpc_error(endpoint, code)
        if state["failures"] >= RPC_CIRCUIT_BREAKER_FAILURES:
            state["state"] = "open"
            state["opened_at"] = time.time()
            LOGGER.warning("rpc circuit opened", extra={"endpoint": endpoint, "code": code})
            self._rotate()

    def _record_success(self, endpoint: str) -> None:
        state = self.circuit_state[endpoint]
        if state["failures"] or state["state"] != "closed":
            LOGGER.info("rpc circuit reset", extra={"endpoint": endpoint})
        state.update({"failures": 0, "opened_at": 0.0, "state": "closed"})

    async def _call_jsonrpc(
        self, method: str, params: list, timeout: float = RPC_TIMEOUT_SEC
    ) -> Optional[dict]:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        }

        if RPC_MODE == "fixtures":
            try:
                if method == "getSignaturesForAddress":
                    wallet_pk = str(params[0]) if params else ""
                    path = FIXTURES_DIR / "signatures" / f"{wallet_pk}.json"
                    if path.exists():
                        with open(path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        return {"result": data}
                    return {"result": []}
                if method == "getTransaction":
                    sig = str(params[0])
                    path = FIXTURES_DIR / "transactions" / f"{sig}.json"
                    if path.exists():
                        with open(path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        return {"result": data}
                    return None
            except Exception as exc:
                LOGGER.warning("fixture load failure", extra={"error": str(exc)})
                return None

        if not self.session:
            raise RuntimeError("AsyncRpcManager session non initialisée")

        start_time = time.time()
        for attempt in range(RPC_MAX_RETRIES):
            endpoint = self._current_endpoint()
            if not self._allow_request(endpoint):
                await asyncio.sleep(RPC_CIRCUIT_BREAKER_PAUSE_SEC)
                self._rotate()
                continue
            try:
                async with self.session.post(endpoint, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if "error" in data:
                            error = data["error"]
                            RPC_ERRORS.labels(endpoint=endpoint[:50], code="RPCException").inc()
                            LOGGER.warning(
                                "rpc json error",
                                extra={"endpoint": endpoint, "method": method, "error": error},
                            )
                            self._record_failure(endpoint, "RPCException")
                            return None
                        self._record_success(endpoint)
                        return data
                    code = f"HTTP{resp.status}"
                    RPC_ERRORS.labels(endpoint=endpoint[:50], code=code).inc()
                    LOGGER.warning(
                        "rpc http error",
                        extra={"endpoint": endpoint, "method": method, "status": resp.status},
                    )
                    self._record_failure(endpoint, code)
            except asyncio.TimeoutError:
                RPC_ERRORS.labels(endpoint=endpoint[:50], code="Timeout").inc()
                LOGGER.warning(
                    "rpc timeout",
                    extra={"endpoint": endpoint, "method": method, "attempt": attempt},
                )
                self._record_failure(endpoint, "Timeout")
            except Exception as exc:
                code = type(exc).__name__
                RPC_ERRORS.labels(endpoint=endpoint[:50], code=code).inc()
                LOGGER.warning(
                    "rpc exception",
                    extra={
                        "endpoint": endpoint,
                        "method": method,
                        "error": code,
                        "attempt": attempt,
                    },
                )
                self._record_failure(endpoint, code)

            delay = compute_retry_delay(attempt)
            await asyncio.sleep(delay)
            self.failures += 1
            if time.time() - start_time >= timeout:
                break

        return None

    async def get_signatures_for_address(
        self, wallet: str, limit: int = TX_LOOKBACK
    ) -> Optional[dict]:
        with observe_latency(RPC_LATENCY, method="get_signatures_for_address"):
            try:
                pubkey = Pubkey.from_string(wallet)
                params = [str(pubkey), {"limit": limit}]
                return await self._call_jsonrpc("getSignaturesForAddress", params)
            except ValueError:
                return None

    async def get_transaction(
        self, signature: str, commitment: str = "finalized"
    ) -> Optional[dict]:
        with observe_latency(RPC_LATENCY, method="get_transaction"):
            params = [
                signature,
                {
                    "encoding": "json",
                    "maxSupportedTransactionVersion": 0,
                    "commitment": commitment,
                },
            ]
            return await self._call_jsonrpc("getTransaction", params)


_last_alert_at: Dict[str, float] = {}
_seen_signatures: OrderedDict[str, float] = OrderedDict()
_last_sig_by_wallet: Dict[str, str] = {}
_profit_history: Dict[str, Deque[float]] = {}
_watchlist_usage: OrderedDict[str, float] = OrderedDict()
_rpc_error_counts: Dict[str, int] = defaultdict(int)
# Statistiques pour le rapport détaillé
_blocked_alerts: List[Dict[str, Any]] = []  # Alertes bloquées avec raisons
_scan_stats: Dict[str, Any] = {
    "total_scans": 0,
    "successful_scans": 0,
    "failed_scans": 0,
    "transactions_detected": 0,
    "rpc_calls": 0,
    "rpc_errors": 0,
    "start_time": time.time(),
}


# ------------------ Persistance d'état (sqlite) ------------------


def init_state_db() -> None:
    """Initialise la DB sqlite pour la persistance d'état."""
    conn = sqlite3.connect(STATE_DB)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS seen_signatures (
            signature TEXT PRIMARY KEY,
            timestamp REAL NOT NULL
        )
    """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(seen_signatures)")}
    if "timestamp" not in columns:
        conn.execute("ALTER TABLE seen_signatures ADD COLUMN timestamp REAL NOT NULL DEFAULT 0")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS last_signatures (
            wallet TEXT PRIMARY KEY,
            signature TEXT NOT NULL
        )
    """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS last_alerts (
            wallet TEXT PRIMARY KEY,
            timestamp REAL NOT NULL
        )
    """
    )
    conn.commit()
    conn.close()


def load_state() -> None:
    """Charge l'état depuis sqlite."""
    global _last_alert_at, _seen_signatures, _last_sig_by_wallet
    if not STATE_DB.exists():
        return
    try:
        conn = sqlite3.connect(STATE_DB)
        # Charger last_sig_by_wallet
        for row in conn.execute("SELECT wallet, signature FROM last_signatures"):
            _last_sig_by_wallet[row[0]] = row[1]
        cutoff = time.time() - STATE_TTL_SECONDS
        _seen_signatures.clear()
        for signature, timestamp in conn.execute(
            "SELECT signature, timestamp FROM seen_signatures ORDER BY timestamp DESC"
        ):
            if timestamp < cutoff:
                continue
            _seen_signatures[signature] = timestamp
            if len(_seen_signatures) >= MAX_SEEN_SIGNATURES:
                break
        _seen_signatures = OrderedDict(sorted(_seen_signatures.items(), key=lambda item: item[1]))
        # Charger last_alert_at
        _last_alert_at = {
            wallet: ts
            for wallet, ts in conn.execute("SELECT wallet, timestamp FROM last_alerts")
            if ts >= cutoff
        }
        conn.close()
    except Exception as exc:
        LOGGER.warning("state load failed", extra={"error": str(exc)})


def save_state() -> None:
    """Sauvegarde l'état dans sqlite."""
    try:
        conn = sqlite3.connect(STATE_DB)
        # Sauvegarder last_sig_by_wallet
        conn.execute("DELETE FROM last_signatures")
        for wallet, sig in _last_sig_by_wallet.items():
            conn.execute(
                "INSERT INTO last_signatures (wallet, signature) VALUES (?, ?)", (wallet, sig)
            )
        # Sauvegarder seen_signatures avec TTL
        conn.execute("DELETE FROM seen_signatures")
        cutoff = time.time() - STATE_TTL_SECONDS
        recent_pairs = [(sig, ts) for sig, ts in _seen_signatures.items() if ts >= cutoff][
            -MAX_SEEN_SIGNATURES:
        ]
        conn.executemany(
            "INSERT INTO seen_signatures (signature, timestamp) VALUES (?, ?)",
            recent_pairs,
        )
        # Sauvegarder last_alert_at
        conn.execute("DELETE FROM last_alerts")
        for wallet, ts in _last_alert_at.items():
            conn.execute("INSERT INTO last_alerts (wallet, timestamp) VALUES (?, ?)", (wallet, ts))
        conn.commit()
        conn.close()
    except Exception as exc:
        LOGGER.warning("state save failed", extra={"error": str(exc)})


# [FIX_AUDIT_6] : Garbage collector pour TTL des états en mémoire
def garbage_collect_state(now: Optional[float] = None) -> None:
    current_ts = now or time.time()
    cutoff = current_ts - STATE_TTL_SECONDS

    # Nettoyage signatures vues
    keys_to_remove = []
    for signature, ts in _seen_signatures.items():
        if ts < cutoff:
            keys_to_remove.append(signature)
        else:
            break
    for signature in keys_to_remove:
        _seen_signatures.pop(signature, None)
    while len(_seen_signatures) > MAX_SEEN_SIGNATURES:
        _seen_signatures.popitem(last=False)

    # Nettoyage last_alert_at
    for wallet, ts in list(_last_alert_at.items()):
        if ts < cutoff:
            _last_alert_at.pop(wallet, None)

    CACHE_SIZE_GAUGE.labels(cache="seen_signatures").set(len(_seen_signatures))
    CACHE_SIZE_GAUGE.labels(cache="profit_history").set(len(_profit_history))
    CACHE_SIZE_GAUGE.labels(cache="watchlist").set(len(_watchlist_usage))


def ensure_wallet_series(wallet: str) -> None:
    """Initialise les métriques Prometheus pour un wallet."""
    try:
        PROFIT_GAUGE.labels(wallet=wallet).set(0.0)
        LAST_ALERT_TS.labels(wallet=wallet).set(0.0)
    except Exception:
        pass


# [FIX_AUDIT_7] : Gestion LRU de la watchlist
def register_watchlist_access(wallet: str, watchlist: List[str]) -> None:
    timestamp = time.time()
    _watchlist_usage[wallet] = timestamp
    _watchlist_usage.move_to_end(wallet)
    if wallet not in watchlist:
        watchlist.append(wallet)


def evict_watchlist_if_needed(watchlist: List[str]) -> None:
    while len(watchlist) > WATCHLIST_MAX_SIZE and _watchlist_usage:
        oldest_wallet, _ = _watchlist_usage.popitem(last=False)
        if oldest_wallet in watchlist:
            watchlist.remove(oldest_wallet)
            LOGGER.info("watchlist eviction", extra={"wallet": oldest_wallet})


def classify_signal(dex: str) -> str:
    if dex in NFT_DEX:
        return "Scalper NFT"
    if dex in AMM_DEX:
        return "AMM / Aggregator"
    return "Signal"


def compute_zscore(wallet: str, profit: float) -> float:
    history = _profit_history.setdefault(wallet, deque(maxlen=50))
    if len(history) >= 2:
        mean = sum(history) / len(history)
        std = statistics.pstdev(history)
        z = (profit - mean) / std if std else 0.0
    else:
        z = 0.0
    history.append(profit)
    return z


# Métriques "vivantes" (toujours présentes)
APP_UP = Gauge("wallet_app_up", "1 if app healthy")
APP_START_TS = Gauge("wallet_app_start_timestamp", "Start time (unix)")
WATCHLIST_SIZE = Gauge("wallet_watchlist_size", "Wallets monitored")
LAST_LOOP_TS = Gauge("wallet_mainloop_timestamp", "Last loop unix")
RPC_LATENCY = Histogram(
    "wallet_rpc_latency_seconds",
    "RPC call latency",
    ["method"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)
TX_SCAN_LATENCY = Histogram(
    "wallet_tx_scan_seconds",
    "Per wallet scan latency",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)
RPC_ERRORS = Counter("wallet_rpc_errors_total", "RPC errors", ["endpoint", "code"])
# [FIX_AUDIT_4] : Suivi métriques erreurs et caches
RPC_ERROR_GAUGE = Gauge("wallet_rpc_error_count", "Nombre d'erreurs RPC en cours", ["endpoint"])
CACHE_SIZE_GAUGE = Gauge("wallet_cache_size", "Taille des caches internes", ["cache"])
ALERT_DURATION = Summary("wallet_alert_duration_seconds", "Durée de traitement d'une alerte (s)")

# [DAAS] Métriques Prometheus nouvelles
SIGNALS_SENT_TOTAL = Counter("signals_sent_total", "Nombre de signaux envoyés", ["tier"])
API_CALLS_TOTAL = Counter("api_calls_total", "Nombre d'appels API", ["endpoint", "tier"])
STRIPE_WEBHOOKS_PROCESSED_TOTAL = Counter(
    "stripe_webhooks_processed_total", "Webhooks Stripe traités", ["event"]
)
DISCLAIMER_SHOWN_TOTAL = Counter("disclaimer_shown_total", "Disclaimers affichés", ["output_type"])
# Note: ACTIVE_SUBSCRIPTIONS_TOTAL est défini dans billing.py pour éviter import circulaire


def record_rpc_error(endpoint: str, code: str) -> None:
    endpoint_key = endpoint[:50]
    _rpc_error_counts[endpoint_key] += 1
    RPC_ERROR_GAUGE.labels(endpoint=endpoint_key).set(_rpc_error_counts[endpoint_key])


# [FIX_AUDIT_8] : Backoff avec jitter configurable
def compute_retry_delay(attempt: int) -> float:
    return min(
        RPC_TIMEOUT_SEC,
        RETRY_JITTER_BASE * (2**attempt) + random.random() * RETRY_JITTER_MAX,
    )


# Métriques alertes
ALERT_COUNTER = Counter("wallet_alerts_total", "Nombre total d'alertes", ["wallet"])
PROFIT_GAUGE = Gauge("wallet_last_profit_sol", "Dernier profit détecté (SOL)", ["wallet"])
LAST_ALERT_TS = Gauge("wallet_last_alert_timestamp", "Horodatage dernier signal", ["wallet"])

# ------------------ Utilitaires ------------------


@contextmanager
def observe_latency(metric, method: str = ""):
    """Context manager pour observer la latence RPC/scan."""
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        if method:
            metric.labels(method=method).observe(elapsed)
        else:
            metric.observe(elapsed)


def parse_datetime(s: str) -> dt.datetime | None:
    if not s or s == "Unknown":
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return dt.datetime.strptime(s, fmt).replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
    return None


def load_initial_data() -> Tuple[pd.DataFrame, List[str]]:
    # [FIX_AUDIT_3] : Validation du fichier wallets avant chargement
    if not validate_data_file(DATA_FILE):
        LOGGER.warning("wallets file invalid or empty", extra={"path": str(DATA_FILE)})
        return pd.DataFrame(), []

    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    rows = []
    candidates: List[Tuple[str, float, float]] = []  # (wallet, net_total, win_rate)

    for w in data["wallets"]:
        txs = w.get("transactions", [])
        dates = [parse_datetime(tx.get("date")) for tx in txs]
        dates = [d for d in dates if d]
        duration = 0.0
        if dates:
            duration = max(dates) - min(dates)
            duration = duration.total_seconds() / 3600.0
        total_profit = w.get("total_profit", 0.0) or 0.0
        total_loss = w.get("total_loss", 0.0) or 0.0
        net_total = w.get("net_total", 0.0) or 0.0
        denom = total_profit + total_loss
        profitability = net_total / denom if denom else 0.0
        daily_net = w.get("daily_net", {}) or {}
        dn_vals = list(daily_net.values())
        if denom:
            dn_ratios = [v / denom for v in dn_vals]
        elif net_total:
            dn_ratios = [v / abs(net_total) for v in dn_vals]
        else:
            dn_ratios = [0.0 for _ in dn_vals]
        variance = statistics.pvariance(dn_ratios) if len(dn_ratios) >= 2 else 0.0
        consistency_index = w.get("win_rate", 0.0) * (1 - variance)
        dex_counter = w.get("dex_counter", {}) or {}
        principal_dex = (
            max(dex_counter.items(), key=lambda x: x[1])[0] if dex_counter else "Unknown"
        )
        win_rate = w.get("win_rate", 0.0)

        rows.append(
            {
                "wallet": w.get("wallet"),
                "net_total": net_total,
                "win_rate": win_rate,
                "total_transactions": w.get("total_transactions", 0),
                "dex": principal_dex,
                "duration_hours": duration,
                "profitability": profitability,
                "consistency_index": consistency_index,
                "top_counterparties": [addr for addr, _ in (w.get("top_counterparties") or [])[:5]],
                "top_programs": [addr for addr, _ in (w.get("top_programs") or [])[:5]],
                "best_transaction": w.get("best_transaction") or {},
                "worst_transaction": w.get("worst_transaction") or {},
            }
        )

        wallet_addr = w.get("wallet")
        if not wallet_addr:
            continue
        # Ajouter tous les wallets comme candidats (on triera après)
        candidates.append((wallet_addr, net_total, win_rate))

    # Trier par net_total décroissant et appliquer filtres GAIN/WIN_RATE
    candidates.sort(key=lambda x: x[1], reverse=True)
    filtered = [
        wallet for wallet in candidates if wallet[1] >= GAIN_FILTER and wallet[2] >= WIN_RATE_FILTER
    ]
    top = filtered[:WATCHLIST_MAX_SIZE]
    watchlist: List[str] = [w[0] for w in top]

    for wallet in list(watchlist):
        register_watchlist_access(wallet, watchlist)

    df = pd.DataFrame(rows)
    return df, watchlist


def print_health(df: pd.DataFrame, watchlist: List[str]) -> None:
    LOGGER.info(
        "health snapshot",
        extra={
            "wallet_total": len(df),
            "watchlist_size": len(watchlist),
            "threshold_profit": PROFIT_ALERT_THRESHOLD,
            "cooldown": ALERT_COOLDOWN_SEC,
            "rpc_endpoint": RPC_ENDPOINTS[0] if RPC_ENDPOINTS else None,
        },
    )


def send_alert(
    wallet: str,
    profit: float,
    dex: str,
    win_rate: float,
    signal_type: str,
    zscore: float,
    signature: str | None,
    detect_ms: float,
    confidence: str = "",
    reasons: str = "",
) -> None:
    LOGGER.info(
        "alert emitted",
        extra={
            "wallet": wallet,
            "profit": profit,
            "dex": dex,
            "signal_type": signal_type,
            "win_rate": win_rate,
            "zscore": zscore,
            "confidence": confidence,
            "reasons": reasons,
            "detect_ms": detect_ms,
            "signature": signature,
        },
    )


async def send_discord_alert_async(
    wallet: str,
    profit: float,
    dex: str,
    win_rate: float,
    signal_type: str,
    zscore: float,
    signature: str | None,
    detect_ms: float,
    confidence: str = "",
    confidence_reasons: Optional[dict] = None,
    tier: str = "free",
) -> None:
    if not DISCORD_WEBHOOK:
        return

    # [DAAS] Disclaimer systématique
    disclaimer = "⚠️ Données uniquement, pas de conseil financier"

    # [DAAS] Différenciation par tier
    if tier == "free":
        # Free tier: alertes basiques
        fields = [
            {"name": "Wallet", "value": wallet, "inline": True},
            {"name": "Profit (SOL)", "value": f"{profit:.2f}", "inline": True},
            {"name": "DEX", "value": dex or "Unknown", "inline": True},
            {"name": "Type", "value": signal_type, "inline": True},
        ]
        # CTA Upgrade pour free tier
        if CONFIG.alerting.include_paywall_prompt:
            fields.append(
                {
                    "name": "Upgrade",
                    "value": "[Upgrade to Pro](https://example.com/pricing) for enriched alerts",
                    "inline": False,
                }
            )
    elif tier == "pro":
        # Pro tier: alertes enrichies
        fields = [
            {"name": "Wallet", "value": wallet, "inline": True},
            {"name": "Profit (SOL)", "value": f"{profit:.2f}", "inline": True},
            {"name": "DEX", "value": dex or "Unknown", "inline": True},
            {"name": "Type", "value": signal_type, "inline": True},
            {"name": "Win rate", "value": f"{win_rate:.1f}%", "inline": True},
            {"name": "Z-score", "value": f"{zscore:+.2f}", "inline": True},
            {"name": "Confidence", "value": confidence or "-", "inline": True},
            {"name": "Latence (ms)", "value": f"{detect_ms:.0f}", "inline": True},
        ]
        if confidence_reasons:
            reasons_text = (
                f"Price coverage: {confidence_reasons.get('price_coverage', 0):.1%}\n"
                f"Route complexity: {confidence_reasons.get('route_complexity', 0):.1f}\n"
                f"Fee complete: {'Yes' if confidence_reasons.get('fee_completeness', 0) > 0.9 else 'No'}\n"
                f"Balance alignment: {confidence_reasons.get('balance_alignment', 0):.1%}"
            )
            fields.append({"name": "Confidence Reasons", "value": reasons_text, "inline": False})
    else:  # elite
        # Elite tier: alertes premium (toutes données)
        fields = [
            {"name": "Wallet", "value": wallet, "inline": True},
            {"name": "Profit (SOL)", "value": f"{profit:.2f}", "inline": True},
            {"name": "DEX", "value": dex or "Unknown", "inline": True},
            {"name": "Type", "value": signal_type, "inline": True},
            {"name": "Win rate", "value": f"{win_rate:.1f}%", "inline": True},
            {"name": "Z-score", "value": f"{zscore:+.2f}", "inline": True},
            {"name": "Confidence", "value": confidence or "-", "inline": True},
            {"name": "Latence (ms)", "value": f"{detect_ms:.0f}", "inline": True},
        ]
        if confidence_reasons:
            reasons_text = (
                f"Price coverage: {confidence_reasons.get('price_coverage', 0):.1%}\n"
                f"Route complexity: {confidence_reasons.get('route_complexity', 0):.1f}\n"
                f"Fee complete: {'Yes' if confidence_reasons.get('fee_completeness', 0) > 0.9 else 'No'}\n"
                f"Balance alignment: {confidence_reasons.get('balance_alignment', 0):.1%}"
            )
            fields.append({"name": "Confidence Reasons", "value": reasons_text, "inline": False})

    # Disclaimer toujours présent
    fields.append({"name": "Disclaimer", "value": disclaimer, "inline": False})

    if signature:
        fields.append(
            {
                "name": "Explorer",
                "value": f"[Solscan](https://solscan.io/tx/{signature})",
                "inline": False,
            }
        )

    # Déduplication : éviter d'envoyer la même alerte deux fois dans les 30 secondes
    dedup_key = f"{wallet}_{signature or 'no_sig'}_{int(profit * 100)}"
    if not hasattr(send_discord_alert_async, "_sent_alerts"):
        send_discord_alert_async._sent_alerts = {}

    now = time.time()
    if dedup_key in send_discord_alert_async._sent_alerts:
        last_sent = send_discord_alert_async._sent_alerts[dedup_key]
        if now - last_sent < 30:  # 30 secondes de cooldown
            LOGGER.debug("discord alert deduplicated", extra={"wallet": wallet, "profit": profit})
            return

    send_discord_alert_async._sent_alerts[dedup_key] = now
    # Nettoyer le cache (garder seulement les alertes des 5 dernières minutes)
    cutoff = now - 300
    send_discord_alert_async._sent_alerts = {
        k: v for k, v in send_discord_alert_async._sent_alerts.items() if v > cutoff
    }

    payload = {
        "username": "WalletRadar",
        "embeds": [
            {
                "title": f"⚡ Wallet {wallet[:8]}… +{profit:.2f} SOL",
                "fields": fields,
                "timestamp": dt.datetime.utcnow().isoformat() + "Z",
            }
        ],
    }

    max_retries = 1
    timeout = aiohttp.ClientTimeout(total=2)
    circuit_breaker_key = f"discord_last_failure_{wallet}"
    circuit_breaker_timeout = 30

    last_failure_map = getattr(send_discord_alert_async, "_last_failure", {})
    last_failure = last_failure_map.get(circuit_breaker_key, 0)
    if time.time() - last_failure < circuit_breaker_timeout:
        LOGGER.warning("discord circuit breaker active", extra={"wallet": wallet})
        return

    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(DISCORD_WEBHOOK, json=payload) as resp:
                    if resp.status in (200, 204):
                        if circuit_breaker_key in last_failure_map:
                            del last_failure_map[circuit_breaker_key]
                        send_discord_alert_async._last_failure = last_failure_map
                        return
                    LOGGER.warning(
                        "discord webhook http error",
                        extra={"status": resp.status, "wallet": wallet, "attempt": attempt},
                    )
        except Exception as exc:
            LOGGER.warning(
                "discord webhook exception",
                extra={"wallet": wallet, "error": str(exc), "attempt": attempt},
            )
        await asyncio.sleep(compute_retry_delay(attempt))

    last_failure_map[circuit_breaker_key] = time.time()
    send_discord_alert_async._last_failure = last_failure_map


async def send_discord_system_notification_async(
    status: str,
    message: str,
    details: Optional[dict] = None,
) -> None:
    """Envoie une notification Discord pour les événements système (démarrage/arrêt)."""
    if not DISCORD_WEBHOOK:
        return

    # Déduplication : éviter d'envoyer la même notification deux fois dans les 5 secondes
    cache_key = f"system_notif_{status}_{int(time.time() / 5)}"
    if not hasattr(send_discord_system_notification_async, "_sent_cache"):
        send_discord_system_notification_async._sent_cache = set()

    if cache_key in send_discord_system_notification_async._sent_cache:
        LOGGER.debug("discord system notification deduplicated", extra={"status": status})
        return

    send_discord_system_notification_async._sent_cache.add(cache_key)
    # Nettoyer le cache (garder seulement les 10 dernières clés)
    if len(send_discord_system_notification_async._sent_cache) > 10:
        send_discord_system_notification_async._sent_cache.clear()

    color = 0x00FF00 if status == "started" else 0xFF0000 if status == "stopped" else 0xFFA500
    emoji = "🟢" if status == "started" else "🔴" if status == "stopped" else "🟡"

    fields = [
        {"name": "Status", "value": status.upper(), "inline": True},
        {
            "name": "Time",
            "value": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "inline": True,
        },
    ]

    if details:
        for key, value in details.items():
            fields.append(
                {"name": key.replace("_", " ").title(), "value": str(value), "inline": True}
            )

    payload = {
        "username": "WalletRadar",
        "embeds": [
            {
                "title": f"{emoji} Wallet Monitor Bot - {status.upper()}",
                "description": message,
                "fields": fields,
                "color": color,
                "timestamp": dt.datetime.utcnow().isoformat() + "Z",
            }
        ],
    }

    max_retries = 1
    timeout = aiohttp.ClientTimeout(total=5)

    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(DISCORD_WEBHOOK, json=payload) as resp:
                    if resp.status in (200, 204):
                        LOGGER.info("discord system notification sent", extra={"status": status})
                        return
                    LOGGER.warning(
                        "discord webhook http error",
                        extra={"status": resp.status, "status_type": status, "attempt": attempt},
                    )
        except Exception as exc:
            LOGGER.warning(
                "discord webhook exception",
                extra={"status_type": status, "error": str(exc), "attempt": attempt},
            )
        await asyncio.sleep(compute_retry_delay(attempt))


def lamport_change(pre: list[int], post: list[int], keys: list[str], wallet: str) -> float:
    try:
        idx = keys.index(wallet)
        if idx < len(pre) and idx < len(post):
            return (post[idx] - pre[idx]) / 1e9
    except ValueError:
        pass
    return 0.0


def normalize_signatures(resp) -> List[dict]:
    if not resp:
        return []
    if isinstance(resp, dict):
        result = resp.get("result")
        if isinstance(result, dict):
            result = result.get("value")
        return result or []
    if hasattr(resp, "value"):
        normalized = []
        for item in resp.value or []:
            signature = None
            if hasattr(item, "signature"):
                sig_obj = item.signature
                signature = str(sig_obj)
            elif isinstance(item, dict):
                signature = item.get("signature")
            entry = {"signature": signature}
            if hasattr(item, "slot"):
                entry["slot"] = int(item.slot)
            if hasattr(item, "err"):
                entry["err"] = item.err
            normalized.append(entry)
        return normalized
    return []


def label_from_programs(programs: List[str]) -> str:
    if not programs:
        return "Unknown"
    counts = CollCounter(PROGRAM_MAP.get(p, "Unknown") for p in programs)
    counts.pop("System", None)
    counts.pop("Unknown", None)
    if counts:
        return max(counts.items(), key=lambda kv: kv[1])[0]
    return "Unknown"


def estimate_profit(
    rpc: RpcManager,
    wallet: str,
    signatures: List[dict],
    max_tx: int = 5,
    price_cache: Optional[TokenPriceCache] = None,
) -> Tuple[float, str, List[str], List[str], dict]:
    """
    Estimation de profit enrichie avec support tokens et multi-hops (synchrone).
    Retourne: (profit_sol, pnl_confidence, counterparties, programs, confidence_reasons)
    """
    if price_cache is None:
        price_cache = TokenPriceCache()

    return estimate_profit_enriched(rpc, wallet, signatures, max_tx, price_cache)


async def estimate_profit_async(
    rpc: AsyncRpcManager,
    wallet: str,
    signatures: List[dict],
    max_tx: int = 5,
    price_cache: Optional[TokenPriceCache] = None,
) -> Tuple[float, str, List[str], List[str], dict]:
    """
    Estimation de profit enrichie avec support tokens et multi-hops (async).
    [FIX_AUDIT_7] : Gestion d'erreurs avec try/except + retries avec backoff

    Retourne: (profit_sol, pnl_confidence, counterparties, programs, confidence_reasons)
    """
    if price_cache is None:
        price_cache = TokenPriceCache()

    # Adaptation de estimate_profit_enriched pour async
    profit = 0.0
    confidence = "high"
    counterparties: List[str] = []
    programs: List[str] = []

    # Métriques pour confidence_reasons
    total_tokens = 0
    priced_tokens = 0
    total_inner_inst = 0
    unique_mints = set()
    fee_known = True
    fee_total = 0.0
    sol_delta_sum = 0.0
    token_delta_sum = 0.0

    # [FIX_AUDIT_7] : Gestion d'erreurs avec retries
    max_retries = 2
    for sig_info in signatures[:max_tx]:
        signature = sig_info.get("signature")
        if not signature:
            continue

        tx_resp = None
        for attempt in range(max_retries):
            try:
                tx_resp = await rpc.get_transaction(signature)
                if tx_resp:
                    break
            except Exception as exc:
                LOGGER.warning(
                    "rpc get_transaction retry",
                    extra={
                        "wallet": wallet,
                        "signature": signature,
                        "attempt": attempt,
                        "error": str(exc),
                    },
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(compute_retry_delay(attempt))
                else:
                    LOGGER.error(
                        "rpc get_transaction failed",
                        extra={"wallet": wallet, "signature": signature, "error": str(exc)},
                    )
                    continue

        if not tx_resp:
            continue

        # Normalise tx_resp
        if isinstance(tx_resp, dict):
            tx = tx_resp.get("result")
        else:
            tx = tx_resp

        if not tx:
            continue

        if isinstance(tx, str):
            try:
                tx = json.loads(tx)
            except json.JSONDecodeError:
                continue

        meta = tx.get("meta") or {}
        msg = (tx.get("transaction") or {}).get("message") or {}

        # 1. SOL direct
        pre_sol = meta.get("preBalances", [])
        post_sol = meta.get("postBalances", [])
        raw_keys = msg.get("accountKeys") or []
        keys = [k["pubkey"] if isinstance(k, dict) and "pubkey" in k else str(k) for k in raw_keys]

        # [CLEANUP] : Import relatif pour la nouvelle structure
        from .profit_estimator import estimate_token_delta, lamport_change

        sol_delta = lamport_change(pre_sol, post_sol, keys, wallet)
        profit += sol_delta
        sol_delta_sum += sol_delta

        # 2. Tokens
        pre_tokens = meta.get("preTokenBalances", []) or []
        post_tokens = meta.get("postTokenBalances", []) or []

        # Comptabiliser tokens pour price_coverage
        all_tokens_this_tx = set()
        for token in pre_tokens + post_tokens:
            mint = token.get("mint", "")
            if mint:
                all_tokens_this_tx.add(mint)
                unique_mints.add(mint)

        total_tokens += len(all_tokens_this_tx)

        # [FIX_AUDIT_4] : Normalisation WSOL → SOL natif
        token_delta, delta_wsol = estimate_token_delta(pre_tokens, post_tokens, wallet, price_cache)
        profit += token_delta
        profit += delta_wsol  # WSOL normalisé comme SOL natif
        token_delta_sum += abs(token_delta)
        sol_delta_sum += abs(delta_wsol)  # WSOL ajouté à sol_delta_sum

        # Comptabiliser tokens pricés
        for mint in all_tokens_this_tx:
            if price_cache.get_price(mint) is not None:
                priced_tokens += 1

        # 3. Fees
        fee = meta.get("fee", 0) / 1e9
        profit -= fee
        fee_total += fee

        # 4. Inner instructions (route complexity)
        inner_insts = meta.get("innerInstructions", []) or []
        inner_count = sum(len(inst.get("instructions", [])) for inst in inner_insts)
        total_inner_inst += inner_count

        # 5. Counterparties & programs
        instructions = msg.get("instructions", []) or []
        for inst in instructions:
            program_id = inst.get("programId")
            if program_id:
                programs.append(str(program_id))

        account_keys = msg.get("accountKeys", []) or []
        for key in account_keys:
            pk = key.get("pubkey") if isinstance(key, dict) else str(key)
            if pk and pk != wallet:
                counterparties.append(str(pk))

    # Calcul confidence_reasons
    price_coverage = (priced_tokens / total_tokens) if total_tokens > 0 else 1.0
    route_complexity = min(total_inner_inst / max(len(signatures[:max_tx]), 1), 10.0)
    fee_completeness = 1.0 if fee_known else 0.0
    # [FIX_AUDIT_8] : balance_alignment utilise BALANCE_TOLERANCE_PCT configurable
    total_valorized = abs(sol_delta_sum) + token_delta_sum
    total_observed = abs(profit) + fee_total
    tolerance = BALANCE_TOLERANCE_PCT / 100.0  # Convertir % en décimal
    balance_alignment = (
        1.0
        if total_valorized > 0
        and abs(total_valorized - total_observed) / max(total_valorized, 1e-9) <= tolerance
        else 0.5
    )

    confidence_reasons = {
        "price_coverage": price_coverage,
        "route_complexity": route_complexity,
        "fee_completeness": fee_completeness,
        "balance_alignment": balance_alignment,
        "total_tokens": total_tokens,
        "priced_tokens": priced_tokens,
        "unique_mints": len(unique_mints),
        "total_inner_inst": total_inner_inst,
    }

    # Score de confiance explicite
    score = 2  # high
    if price_coverage < 0.7 or route_complexity > 5.0:
        score -= 1
    if fee_completeness < 1.0 or balance_alignment < 0.8:
        score -= 1

    confidence = ["low", "med", "high"][max(0, min(2, score))]

    # [FIX_AUDIT_7] : Gestion d'erreurs globale avec retour par défaut
    try:
        return (
            profit,
            confidence,
            list(set(counterparties)),
            list(set(programs)),
            confidence_reasons,
        )
    except Exception as exc:
        LOGGER.error(
            "estimate_profit_async failed",
            extra={"wallet": wallet, "signatures_count": len(signatures), "error": str(exc)},
        )
        # Retour par défaut en cas d'erreur
        return (
            0.0,
            "low",
            [],
            [],
            {
                "price_coverage": 0.0,
                "route_complexity": 0.0,
                "fee_completeness": 0.0,
                "balance_alignment": 0.0,
                "total_tokens": 0,
                "priced_tokens": 0,
                "unique_mints": 0,
                "total_inner_inst": 0,
            },
        )


def filter_new_signatures(wallet: str, signatures: List[dict]) -> List[dict]:
    last = _last_sig_by_wallet.get(wallet)
    subset: List[dict] = []
    if not signatures:
        return subset
    if last is None:
        subset = signatures[:5]
    else:
        for entry in signatures:
            sig = entry.get("signature")
            if not sig:
                continue
            if sig == last:
                break
            subset.append(entry)
    head_sig = signatures[0].get("signature")
    if head_sig:
        _last_sig_by_wallet[wallet] = head_sig
    return subset


def should_alert(wallet: str, new_sigs: List[str]) -> bool:
    if not new_sigs:
        return False
    now = time.time()
    if any(sig in _seen_signatures for sig in new_sigs):
        return False
    if now - _last_alert_at.get(wallet, 0.0) < ALERT_COOLDOWN_SEC:
        return False
    return True


def mark_alert(wallet: str, sigs: List[str]) -> None:
    timestamp = time.time()
    _last_alert_at[wallet] = timestamp
    for signature in sigs:
        _seen_signatures[signature] = timestamp
        _seen_signatures.move_to_end(signature)
    while len(_seen_signatures) > MAX_SEEN_SIGNATURES:
        _seen_signatures.popitem(last=False)


# [FIX_AUDIT_9] : Batch processing par bloc


def build_signature_batches(signatures: List[dict]) -> List[List[dict]]:
    grouped: Dict[int | None, List[dict]] = defaultdict(list)
    for sig in signatures:
        grouped[sig.get("slot")].append(sig)
    batches: List[List[dict]] = []
    for _, items in sorted(grouped.items(), key=lambda kv: kv[0] or 0, reverse=True):
        for idx in range(0, len(items), ALERT_BATCH_SIZE):
            batches.append(items[idx : idx + ALERT_BATCH_SIZE])
    if not batches and signatures:
        batches.append(signatures[:ALERT_BATCH_SIZE])
    return batches


async def scan_wallet_async(
    wallet: str,
    rpc: AsyncRpcManager,
    df: pd.DataFrame,
    watchlist: List[str],
    price_cache: TokenPriceCache,
    alerts: List[dict],
    cluster_counter: CollCounter,
    sem: asyncio.Semaphore,
    alerts_queue: Optional[List[dict]] = None,
) -> None:
    """Scan async d'un wallet avec backpressure via sémaphore et queue API service."""

    async with sem:
        _scan_stats["total_scans"] += 1
        register_watchlist_access(wallet, watchlist)
        evict_watchlist_if_needed(watchlist)
        with observe_latency(TX_SCAN_LATENCY):
            process_start = time.perf_counter()
            try:
                Pubkey.from_string(wallet)
            except ValueError:
                _scan_stats["failed_scans"] += 1
                LOGGER.warning("invalid wallet format", extra={"wallet": wallet})
                return

            try:
                _scan_stats["rpc_calls"] += 1
                resp = await rpc.get_signatures_for_address(wallet, limit=TX_LOOKBACK)
            except Exception as exc:
                _scan_stats["failed_scans"] += 1
                _scan_stats["rpc_errors"] += 1
                LOGGER.warning(
                    "signatures fetch failed", extra={"wallet": wallet, "error": str(exc)}
                )
                return

            if not resp:
                return

            result = resp.get("result")
            if isinstance(result, dict):
                raw_sigs = result.get("value", []) or []
            elif isinstance(result, list):
                raw_sigs = result
            else:
                raw_sigs = []

            increment = filter_new_signatures(wallet, raw_sigs)
            if not increment:
                _scan_stats["successful_scans"] += 1
                return

            _scan_stats["transactions_detected"] += len(increment)
            batches = build_signature_batches(increment)
            wallet_row = df[df["wallet"] == wallet]
            net_total = float(wallet_row["net_total"].iat[0]) if not wallet_row.empty else 0.0
            win_rate = float(wallet_row["win_rate"].iat[0]) if not wallet_row.empty else 0.0

            for batch in batches:
                batch_start = time.perf_counter()
                try:
                    _scan_stats["rpc_calls"] += len(batch)  # Appels pour récupérer les transactions
                    (
                        profit,
                        pnl_confidence,
                        counterparties,
                        programs,
                        confidence_reasons,
                    ) = await estimate_profit_async(rpc, wallet, batch, price_cache=price_cache)
                except Exception as exc:
                    _scan_stats["rpc_errors"] += 1
                    LOGGER.error(
                        "estimate profit failed", extra={"wallet": wallet, "error": str(exc)}
                    )
                    await asyncio.sleep(compute_retry_delay(0))
                    continue

                new_sigs = [s.get("signature") for s in batch if s.get("signature")]
                if not new_sigs:
                    continue

                dex = label_from_programs(programs)
                if dex == "Unknown" and not wallet_row.empty:
                    dex = wallet_row["dex"].iat[0]

                if net_total < GAIN_FILTER or win_rate < WIN_RATE_FILTER:
                    _blocked_alerts.append(
                        {
                            "wallet": wallet,
                            "profit": profit,
                            "reason": "wallet_filtered",
                            "details": {
                                "net_total": net_total,
                                "win_rate": win_rate,
                                "gain_filter": GAIN_FILTER,
                                "win_rate_filter": WIN_RATE_FILTER,
                            },
                            "timestamp": time.time(),
                        }
                    )
                    LOGGER.debug(
                        "wallet filtered by thresholds",
                        extra={
                            "wallet": wallet,
                            "net_total": net_total,
                            "win_rate": win_rate,
                            "gain_filter": GAIN_FILTER,
                            "win_rate_filter": WIN_RATE_FILTER,
                        },
                    )
                    continue

                if profit < PROFIT_ALERT_THRESHOLD:
                    _blocked_alerts.append(
                        {
                            "wallet": wallet,
                            "profit": profit,
                            "reason": "profit_below_threshold",
                            "details": {
                                "profit": profit,
                                "threshold": PROFIT_ALERT_THRESHOLD,
                            },
                            "timestamp": time.time(),
                        }
                    )
                    LOGGER.debug(
                        "profit below threshold",
                        extra={
                            "wallet": wallet,
                            "profit": profit,
                            "threshold": PROFIT_ALERT_THRESHOLD,
                        },
                    )
                    continue

                if pnl_confidence not in ("med", "high"):
                    _blocked_alerts.append(
                        {
                            "wallet": wallet,
                            "profit": profit,
                            "reason": "confidence_too_low",
                            "details": {
                                "confidence": pnl_confidence,
                            },
                            "timestamp": time.time(),
                        }
                    )
                    LOGGER.debug(
                        "confidence too low",
                        extra={"wallet": wallet, "profit": profit, "confidence": pnl_confidence},
                    )
                    continue

                if not should_alert(wallet, new_sigs):
                    last_alert = _last_alert_at.get(wallet, 0.0)
                    cooldown_remaining = ALERT_COOLDOWN_SEC - (time.time() - last_alert)
                    _blocked_alerts.append(
                        {
                            "wallet": wallet,
                            "profit": profit,
                            "reason": "cooldown",
                            "details": {
                                "cooldown_remaining": cooldown_remaining,
                                "last_alert_timestamp": last_alert,
                            },
                            "timestamp": time.time(),
                        }
                    )
                    LOGGER.debug(
                        "alert blocked by cooldown",
                        extra={
                            "wallet": wallet,
                            "cooldown_remaining": cooldown_remaining,
                            "profit": profit,
                        },
                    )
                    continue

                zscore = compute_zscore(wallet, profit)
                signal_type = classify_signal(dex)
                primary_sig = new_sigs[0]
                detect_ms = (time.perf_counter() - process_start) * 1000.0
                loop_start = dt.datetime.now(dt.timezone.utc)

                # [DAAS] Déterminer tier depuis API key (pour MVP, utiliser "free" par défaut)
                # TODO: Récupérer tier depuis API key associée au wallet
                tier = "free"  # MVP: par défaut free tier

                alert_event = {
                    "wallet": wallet,
                    "profit": profit,
                    "dex": dex,
                    "win_rate": win_rate,
                    "timestamp": loop_start,
                    "counterparties": counterparties[:10],
                    "signal_type": signal_type,
                    "zscore": zscore,
                    "signature": primary_sig,
                    "detect_ms": detect_ms,
                    "pnl_confidence": pnl_confidence,
                    "confidence_reasons": confidence_reasons,
                    "dry_run": DRY_RUN,
                    "tier": tier,  # [DAAS] Tier ajouté
                }
                alerts.append(alert_event)

                # [DAAS] Ajouter à queue API service
                if CONFIG.daas_mode and alerts_queue is not None:
                    alerts_queue.append(alert_event)
                    # Garder queue limitée (dernières 1000 alertes)
                    if len(alerts_queue) > 1000:
                        alerts_queue.pop(0)

                _scan_stats["successful_scans"] += 1
                mark_alert(wallet, new_sigs)
                append_log(
                    {
                        "wallet": wallet,
                        "profit": profit,
                        "timestamp": loop_start.isoformat(),
                        "signatures": new_sigs,
                        "counterparties": counterparties[:5],
                        "programs": programs[:3],
                        "signal_type": signal_type,
                        "zscore": zscore,
                        "detect_ms": detect_ms,
                        "pnl_confidence": pnl_confidence,
                        "confidence_reasons": confidence_reasons,
                        "dry_run": DRY_RUN,
                    }
                )
                ALERT_COUNTER.labels(wallet=wallet).inc()
                PROFIT_GAUGE.labels(wallet=wallet).set(profit)
                LAST_ALERT_TS.labels(wallet=wallet).set(time.time())
                ALERT_DURATION.observe(time.perf_counter() - batch_start)

                reasons_str = ", ".join(
                    [
                        f"price_cov={confidence_reasons.get('price_coverage', 0):.1%}",
                        f"route={confidence_reasons.get('route_complexity', 0):.1f}",
                        f"fee_ok={'Y' if confidence_reasons.get('fee_completeness', 0) > 0.9 else 'N'}",
                        f"bal_align={confidence_reasons.get('balance_alignment', 0):.1%}",
                    ]
                )

                if not DRY_RUN:
                    send_alert(
                        wallet,
                        profit,
                        dex,
                        win_rate,
                        signal_type,
                        zscore,
                        primary_sig,
                        detect_ms,
                        pnl_confidence,
                        reasons_str,
                        tier=tier,
                    )

                # Envoyer notification Discord même en DRY_RUN (pour test)
                await send_discord_alert_async(
                    wallet,
                    profit,
                    dex,
                    win_rate,
                    signal_type,
                    zscore,
                    primary_sig,
                    detect_ms,
                    pnl_confidence,
                    confidence_reasons,
                    tier=tier,
                )

                # [DAAS] Métrique signals_sent_total
                SIGNALS_SENT_TOTAL.labels(tier=tier).inc()
                DISCLAIMER_SHOWN_TOTAL.labels(output_type="discord").inc()

                if COPY_TRADER_ENABLED and profit < -0.1:
                    open_positions = get_open_positions(wallet)
                    for pos in open_positions:
                        exit_sig = primary_sig
                        exit_price = 1.0 * (1.0 + profit / 10.0)
                        pnl = close_position(pos["id"], exit_price, exit_sig, "wallet_sold")
                        if pnl is not None:
                            LOGGER.info(
                                "copy trade closed",
                                extra={"position_id": pos["id"], "wallet": wallet, "pnl": pnl},
                            )

                if COPY_TRADER_ENABLED and profit >= PROFIT_ALERT_THRESHOLD and primary_sig:
                    position_id = on_alert(wallet, profit, primary_sig, dex, signal_type)
                    if position_id:
                        LOGGER.info(
                            "copy trade opened",
                            extra={"position_id": position_id, "wallet": wallet},
                        )

                cluster_counter.update(counterparties)

                if profit >= NEW_WALLET_GAIN:
                    candidates = [addr for addr in counterparties if addr not in watchlist]
                    for addr in candidates:
                        if len(addr) < 32 or "111111111111111111111111" in addr:
                            continue
                        try:
                            Pubkey.from_string(addr)
                        except ValueError:
                            continue
                        stats_resp = await rpc.get_signatures_for_address(
                            addr, limit=NEW_WALLET_MIN_TRX
                        )
                        if not stats_resp:
                            continue
                        stats_result = stats_resp.get("result")
                        if isinstance(stats_result, dict):
                            stats = stats_result.get("value", []) or []
                        elif isinstance(stats_result, list):
                            stats = stats_result
                        else:
                            stats = []
                        if len(stats) >= NEW_WALLET_MIN_TRX:
                            register_watchlist_access(addr, watchlist)
                            evict_watchlist_if_needed(watchlist)
                            LOGGER.info("watchlist auto add", extra={"wallet": addr})
                            if addr not in df["wallet"].values:
                                df.loc[len(df)] = {
                                    "wallet": addr,
                                    "net_total": 0.0,
                                    "win_rate": 0.0,
                                    "total_transactions": 0,
                                    "dex": label_from_programs(programs) or "Unknown",
                                    "duration_hours": 0.0,
                                    "profitability": 0.0,
                                    "consistency_index": 0.0,
                                    "top_counterparties": [],
                                    "top_programs": [],
                                    "best_transaction": {},
                                    "worst_transaction": {},
                                }


def rollover_log(max_bytes: int = LOG_MAX_BYTES) -> None:
    if LOG_FILE.exists() and LOG_FILE.stat().st_size > max_bytes:
        backup = LOG_FILE.with_suffix(".1.json")
        backup.write_text(LOG_FILE.read_text(encoding="utf-8"), encoding="utf-8")
        LOG_FILE.write_text("[]", encoding="utf-8")


def update_dashboard(df: pd.DataFrame, alerts: List[dict]) -> None:
    latest: dict[str, dict] = {}
    for event in alerts:
        latest[event["wallet"]] = event
    df_out = df.copy()
    df_out["last_alert_profit"] = df_out["wallet"].map(lambda w: latest.get(w, {}).get("profit"))
    df_out["last_activity"] = df_out["wallet"].map(
        lambda w: (
            latest.get(w, {}).get("timestamp") or dt.datetime.fromtimestamp(0, tz=dt.timezone.utc)
        ).isoformat()
        if w in latest
        else None
    )
    df_out["alert_active"] = df_out["wallet"].isin(latest.keys())
    df_out["last_signal_type"] = df_out["wallet"].map(
        lambda w: latest.get(w, {}).get("signal_type")
    )
    df_out["last_zscore"] = df_out["wallet"].map(lambda w: latest.get(w, {}).get("zscore"))
    df_out["last_detect_ms"] = df_out["wallet"].map(lambda w: latest.get(w, {}).get("detect_ms"))
    df_out.sort_values("net_total", ascending=False).to_csv(DASHBOARD_CSV, index=False)


def update_report(df: pd.DataFrame, alerts: List[dict], clusters: CollCounter) -> None:
    lines = ["# Surveillance Wallets Solana\n"]
    now = dt.datetime.now(dt.timezone.utc)
    lines.append(f"_Dernière mise à jour : {now.isoformat()}_\n")
    lines.append("## Résumé\n")
    for _, row in df.sort_values("net_total", ascending=False).iterrows():
        best = row["best_transaction"].get("net_result")
        worst = row["worst_transaction"].get("net_result")
        comment = (
            f"- **{row['wallet'][:12]}…** ({row['dex']}) : net {row['net_total']:+.2f} SOL | "
            f"win rate {row['win_rate']:.1f}% | durée {row['duration_hours']:.1f} h"
        )
        if best is not None and math.isfinite(best):
            comment += f" | meilleure tx {best:+.2f}"
        if worst is not None and math.isfinite(worst):
            comment += f" | pire tx {worst:+.2f}"
        lines.append(comment)
    lines.append("\n## 10 Dernières Alertes\n")
    if not alerts:
        lines.append("Aucune alerte en cours.\n")
    else:
        recent_alerts = sorted(
            alerts,
            key=lambda x: x.get("timestamp", dt.datetime.fromtimestamp(0, tz=dt.timezone.utc)),
            reverse=True,
        )[:10]
        for al in recent_alerts:
            timestamp_str = (
                al["timestamp"].isoformat()
                if hasattr(al["timestamp"], "isoformat")
                else str(al.get("timestamp", ""))
            )
            confidence_str = al.get("pnl_confidence", "-")
            reasons = al.get("confidence_reasons", {})
            reasons_text = ""
            if reasons:
                reasons_text = (
                    f" | price_cov={reasons.get('price_coverage', 0):.1%}, "
                    f"route={reasons.get('route_complexity', 0):.1f}, "
                    f"fee_ok={'Y' if reasons.get('fee_completeness', 0) > 0.9 else 'N'}, "
                    f"bal_align={reasons.get('balance_alignment', 0):.1%}"
                )
            lines.append(
                f"- ⚡ **{al['wallet'][:12]}…** : +{al['profit']:.2f} SOL à {timestamp_str} "
                f"(DEX {al['dex']} | {al.get('signal_type', 'Signal')} | Z {al.get('zscore', 0.0):+.2f} | conf {confidence_str}{reasons_text})"
            )
            if al.get("signature"):
                lines.append(f"  - [Solscan](https://solscan.io/tx/{al['signature']})")
    lines.append("\n## Clusters suspects\n")
    if clusters:
        for addr, count in clusters.most_common(10):
            lines.append(f"- {addr} repéré {count} fois dans les nouvelles activités")
    else:
        lines.append("Aucun comportement coordonné détecté récemment.")
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


def generate_detailed_report(
    df: pd.DataFrame,
    alerts: List[dict],
    clusters: CollCounter,
    watchlist: List[str],
    rpc: AsyncRpcManager,
) -> Dict[str, Any]:
    """Génère un rapport détaillé JSON synthétisant l'activité courante."""
    now = dt.datetime.now(dt.timezone.utc)
    uptime = time.time() - _scan_stats["start_time"]

    # Collecter les métriques Prometheus
    from prometheus_client import REGISTRY

    metrics_data = {}
    for collector in REGISTRY._collector_to_names:
        if hasattr(collector, "_metrics"):
            for metric_name, metric in collector._metrics.items():
                if hasattr(metric, "_type"):
                    metrics_data[metric_name] = {
                        "type": metric._type,
                        "value": str(metric._value) if hasattr(metric, "_value") else "N/A",
                    }

    # Statistiques des wallets
    wallets_stats = []
    for wallet in watchlist:
        wallet_row = df[df["wallet"] == wallet]
        if not wallet_row.empty:
            row = wallet_row.iloc[0]
            last_alert = _last_alert_at.get(wallet, 0.0)
            cooldown_remaining = max(0, ALERT_COOLDOWN_SEC - (time.time() - last_alert))
            wallets_stats.append(
                {
                    "wallet": wallet,
                    "net_total": float(row["net_total"]),
                    "win_rate": float(row["win_rate"]),
                    "dex": str(row["dex"]),
                    "duration_hours": float(row["duration_hours"]),
                    "last_alert_timestamp": last_alert,
                    "cooldown_remaining_seconds": cooldown_remaining,
                    "passes_gain_filter": float(row["net_total"]) >= GAIN_FILTER,
                    "passes_win_rate_filter": float(row["win_rate"]) >= WIN_RATE_FILTER,
                }
            )

    # Alertes bloquées (dernières 10 minutes)
    recent_blocked = [b for b in _blocked_alerts if time.time() - b.get("timestamp", 0) < 600]

    report = {
        "timestamp": now.isoformat(),
        "uptime_seconds": uptime,
        "configuration": {
            "profit_alert_threshold": PROFIT_ALERT_THRESHOLD,
            "gain_filter": GAIN_FILTER,
            "win_rate_filter": WIN_RATE_FILTER,
            "alert_cooldown_sec": ALERT_COOLDOWN_SEC,
            "tx_refresh_seconds": TX_REFRESH_SECONDS,
            "max_concurrency": MAX_CONCURRENCY,
            "dry_run": DRY_RUN,
            "rpc_endpoints_count": len(RPC_ENDPOINTS),
        },
        "statistics": {
            "total_scans": _scan_stats["total_scans"],
            "successful_scans": _scan_stats["successful_scans"],
            "failed_scans": _scan_stats["failed_scans"],
            "transactions_detected": _scan_stats["transactions_detected"],
            "rpc_calls": _scan_stats["rpc_calls"],
            "rpc_errors": _scan_stats["rpc_errors"],
            "success_rate": (
                _scan_stats["successful_scans"] / _scan_stats["total_scans"] * 100
                if _scan_stats["total_scans"] > 0
                else 0
            ),
            "watchlist_size": len(watchlist),
            "total_wallets_in_data": len(df),
            "alerts_generated": len(alerts),
            "alerts_blocked": len(recent_blocked),
            "seen_signatures_count": len(_seen_signatures),
        },
        "wallets": wallets_stats,
        "recent_alerts": [
            {
                "wallet": a["wallet"],
                "profit": a["profit"],
                "timestamp": a["timestamp"].isoformat()
                if hasattr(a["timestamp"], "isoformat")
                else str(a["timestamp"]),
                "dex": a.get("dex", "Unknown"),
                "signal_type": a.get("signal_type", "Signal"),
                "zscore": a.get("zscore", 0.0),
                "confidence": a.get("pnl_confidence", "-"),
                "signature": a.get("signature"),
            }
            for a in sorted(
                alerts,
                key=lambda x: x.get("timestamp", dt.datetime.fromtimestamp(0, tz=dt.timezone.utc)),
                reverse=True,
            )[:20]
        ],
        "blocked_alerts": recent_blocked[-50:],  # Dernières 50 alertes bloquées
        "rpc_health": {
            "endpoints": RPC_ENDPOINTS,
            "error_counts": dict(_rpc_error_counts),
            "circuit_breaker_active": any(
                rpc._failure_counts.get(endpoint, 0) >= RPC_CIRCUIT_BREAKER_FAILURES
                for endpoint in RPC_ENDPOINTS
            )
            if hasattr(rpc, "_failure_counts")
            else False,
        },
        "clusters": {
            "top_addresses": [
                {"address": addr, "count": count} for addr, count in clusters.most_common(10)
            ]
        },
        "caches": {
            "seen_signatures": len(_seen_signatures),
            "last_alert_timestamps": len(_last_alert_at),
            "last_sig_by_wallet": len(_last_sig_by_wallet),
        },
    }

    return report


def format_report_for_discord(
    report: Dict[str, Any], title_override: Optional[str] = None
) -> Dict[str, Any]:
    """Formate le rapport pour Discord avec des embeds enrichis."""
    stats = report["statistics"]
    config = report["configuration"]

    # Calculer les pourcentages
    success_rate = f"{stats['success_rate']:.1f}%"
    error_rate = (
        f"{stats['rpc_errors'] / stats['rpc_calls'] * 100:.1f}%" if stats["rpc_calls"] > 0 else "0%"
    )

    # Graphique ASCII pour le taux de succès
    success_bar_length = int(stats["success_rate"] / 10)
    success_bar = "█" * success_bar_length + "░" * (10 - success_bar_length)

    # Résumé principal enrichi
    main_desc = (
        f"**📊 Statistiques du bot**\n"
        f"```\n"
        f"Scans:      {stats['total_scans']:>4} (✓{stats['successful_scans']:>3} ✗{stats['failed_scans']:>3}) - {success_rate}\n"
        f"Succès:     [{success_bar}] {success_rate}\n"
        f"TX détect:  {stats['transactions_detected']:>4}\n"
        f"RPC calls:  {stats['rpc_calls']:>4} (erreurs: {stats['rpc_errors']:>3} - {error_rate})\n"
        f"Alertes:    Générées: {stats['alerts_generated']:>3} | Bloquées: {stats['alerts_blocked']:>3}\n"
        f"Watchlist:  {stats['watchlist_size']:>3} wallets surveillés\n"
        f"```\n"
    )

    # Résumé des alertes bloquées par raison avec graphique
    blocked_by_reason = {}
    for blocked in report.get("blocked_alerts", [])[:50]:
        reason = blocked.get("reason", "unknown")
        blocked_by_reason[reason] = blocked_by_reason.get(reason, 0) + 1

    blocked_summary = ""
    if blocked_by_reason:
        blocked_summary = "\n**🔒 Alertes bloquées par raison:**\n```\n"
        reason_names = {
            "wallet_filtered": "Filtre wallet",
            "profit_below_threshold": "Profit < seuil",
            "confidence_too_low": "Confiance faible",
            "cooldown": "Cooldown actif",
            "idempotence": "Déjà envoyée",
        }
        total_blocked = sum(blocked_by_reason.values())
        for reason, count in sorted(blocked_by_reason.items(), key=lambda x: x[1], reverse=True):
            pct = (count / total_blocked * 100) if total_blocked > 0 else 0
            bar_length = int(pct / 10)
            bar = "█" * bar_length + "░" * (10 - bar_length)
            blocked_summary += f"{reason_names.get(reason, reason):<20} [{bar}] {pct:>5.1f}%\n"
        blocked_summary += "```\n"

    # Top wallets avec liens Solscan
    wallets_summary = ""
    if report.get("wallets"):
        top_wallets = sorted(report["wallets"], key=lambda w: w.get("net_total", 0), reverse=True)[
            :10
        ]
        wallets_summary = "\n**👛 Top 10 Wallets:**\n```\n"
        wallets_summary += f"{'Wallet':<12} {'Profit':>8} {'Win%':>6} {'Status'}\n"
        wallets_summary += "-" * 40 + "\n"
        for idx, w in enumerate(top_wallets, 1):
            status = "✓" if w.get("passes_gain_filter") and w.get("passes_win_rate_filter") else "✗"
            wallet_short = w["wallet"][:10] + "…"
            wallets_summary += f"{idx:>2}. {wallet_short:<12} {w['net_total']:>+7.2f} {w['win_rate']:>5.1f}% {status}\n"
        wallets_summary += "```\n"
        # Ajouter les liens Solscan pour les 3 premiers
        if top_wallets:
            wallets_summary += "\n**🔗 Liens Solscan (Top 3):**\n"
            for idx, w in enumerate(top_wallets[:3], 1):
                wallet_addr = w["wallet"]
                wallets_summary += f"{idx}. [Wallet {wallet_addr[:8]}…](https://solscan.io/account/{wallet_addr})\n"

    # Top alertes récentes avec liens
    alerts_summary = ""
    if report.get("recent_alerts"):
        alerts_summary = "\n**⚡ Alertes récentes (Top 5):**\n```\n"
        alerts_summary += f"{'Wallet':<12} {'Profit':>8} {'DEX':<10} {'Type'}\n"
        alerts_summary += "-" * 45 + "\n"
        for alert in report["recent_alerts"][:5]:
            wallet_short = alert["wallet"][:10] + "…"
            alerts_summary += (
                f"{wallet_short:<12} {alert['profit']:>+7.2f} {alert['dex']:<10} {alert.get('signal_type', 'Signal')}\n"
            )
        alerts_summary += "```\n"
        # Ajouter les liens Solscan pour les signatures
        signatures_links = []
        for alert in report["recent_alerts"][:5]:
            if alert.get("signature"):
                sig = alert["signature"]
                signatures_links.append(f"• [TX {sig[:8]}…](https://solscan.io/tx/{sig})")
        if signatures_links:
            alerts_summary += "\n**🔗 Transactions:**\n" + "\n".join(signatures_links) + "\n"

    # Configuration avec indicateurs visuels
    dry_run_status = "🔴 DRY_RUN" if config["dry_run"] else "🟢 LIVE"
    config_summary = (
        f"\n**⚙️ Configuration actuelle:**\n"
        f"```\n"
        f"Mode:            {dry_run_status}\n"
        f"Seuil profit:    {config['profit_alert_threshold']:>6.2f} SOL\n"
        f"Filtre gain:     {config['gain_filter']:>6.2f} SOL\n"
        f"Filtre win rate: {config['win_rate_filter']:>6.1f}%\n"
        f"Cooldown:        {config['alert_cooldown_sec']:>6d}s\n"
        f"Refresh TX:      {config['tx_refresh_seconds']:>6d}s\n"
        f"Endpoints RPC:   {config['rpc_endpoints_count']:>6d}\n"
        f"```\n"
    )

    # Santé RPC avec graphique
    rpc_health = report.get("rpc_health", {})
    rpc_summary = ""
    if rpc_health:
        endpoints_count = len(rpc_health.get("endpoints", []))
        errors_count = sum(rpc_health.get("error_counts", {}).values())
        circuit_breaker = "⚠️ ACTIF" if rpc_health.get("circuit_breaker_active") else "✅ OK"
        rpc_summary = (
            f"\n**🌐 Santé RPC:**\n"
            f"```\n"
            f"Endpoints:        {endpoints_count:>3}\n"
            f"Erreurs totales:  {errors_count:>3}\n"
            f"Circuit breaker:  {circuit_breaker}\n"
            f"```\n"
        )
        # Détails par endpoint
        error_counts = rpc_health.get("error_counts", {})
        if error_counts:
            rpc_summary += "\n**📡 Erreurs par endpoint:**\n```\n"
            for endpoint, count in sorted(error_counts.items(), key=lambda x: x[1], reverse=True):
                endpoint_short = endpoint[:40] + "…" if len(endpoint) > 40 else endpoint
                rpc_summary += f"{endpoint_short:<43} {count:>3}\n"
            rpc_summary += "```\n"

    # Uptime formaté
    uptime_sec = report["uptime_seconds"]
    uptime_hours = int(uptime_sec // 3600)
    uptime_minutes = int((uptime_sec % 3600) // 60)
    uptime_str = f"{uptime_hours}h {uptime_minutes}m"

    # Description complète
    full_description = (
        main_desc
        + blocked_summary
        + wallets_summary
        + alerts_summary
        + config_summary
        + rpc_summary
    )

    # Couleur selon l'état
    if stats["rpc_errors"] == 0 and stats["success_rate"] > 95:
        color = 0x00FF00  # Vert
    elif stats["rpc_errors"] < 10 and stats["success_rate"] > 80:
        color = 0xFFA500  # Orange
    else:
        color = 0xFF0000  # Rouge

    # Créer l'embed Discord principal
    title = title_override if title_override else "📊 Rapport détaillé - Wallet Monitor Bot"
    embed = {
        "title": title,
        "description": full_description,
        "color": color,
        "timestamp": report["timestamp"],
        "footer": {"text": f"Uptime: {uptime_str} | Bot actif"},
    }

    # Créer un second embed pour les métriques supplémentaires si disponibles
    embeds = [embed]
    if stats.get("alerts_generated", 0) > 0 or stats.get("transactions_detected", 0) > 0:
        activity_embed = {
            "title": "📈 Activité récente",
            "description": (
                f"**Transactions analysées:** {stats.get('transactions_detected', 0)}\n"
                f"**Alertes générées:** {stats.get('alerts_generated', 0)}\n"
                f"**Watchlist:** {stats.get('watchlist_size', 0)} wallets\n"
                f"**Signatures vues:** {stats.get('seen_signatures_count', 0)}\n"
            ),
            "color": 0x3498DB,
            "timestamp": report["timestamp"],
        }
        embeds.append(activity_embed)

    payload = {"username": "WalletRadar", "embeds": embeds}

    return payload


async def send_report_to_discord(
    report: Dict[str, Any], title_override: Optional[str] = None
) -> None:
    """Envoie le rapport détaillé sur Discord."""
    if not DISCORD_WEBHOOK:
        return

    try:
        payload = format_report_for_discord(report, title_override=title_override)
        timeout = aiohttp.ClientTimeout(total=10)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(DISCORD_WEBHOOK, json=payload) as resp:
                if resp.status in (200, 204):
                    LOGGER.info(
                        "detailed report sent to discord",
                        extra={"report_size": len(json.dumps(report, default=str))},
                    )
                else:
                    LOGGER.warning(
                        "failed to send report to discord", extra={"status": resp.status}
                    )
    except Exception as exc:
        LOGGER.warning("error sending report to discord", extra={"error": str(exc)})


def save_detailed_report(report: Dict[str, Any], title_override: Optional[str] = None) -> None:
    """Sauvegarde le rapport détaillé dans un fichier JSON avec timestamp et l'envoie sur Discord."""
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_file = Path("data") / f"detailed_report_{timestamp}.json"
    report_file.parent.mkdir(parents=True, exist_ok=True)

    # Garder seulement les 10 derniers rapports
    existing_reports = sorted(report_file.parent.glob("detailed_report_*.json"), reverse=True)
    for old_report in existing_reports[10:]:
        old_report.unlink()

    report_file.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    LOGGER.info(
        "detailed report saved",
        extra={"file": str(report_file), "report_size": len(json.dumps(report, default=str))},
    )

    # Envoyer le rapport sur Discord
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Si on est dans une boucle async, créer une tâche
            asyncio.create_task(send_report_to_discord(report, title_override=title_override))
        else:
            # Sinon, exécuter directement
            loop.run_until_complete(send_report_to_discord(report, title_override=title_override))
    except Exception as exc:
        LOGGER.warning("failed to send report to discord", extra={"error": str(exc)})


def prune_blocked_alerts(retention_seconds: int = 7200) -> None:
    """Nettoie les alertes bloquées anciennes pour éviter la croissance infinie."""

    global _blocked_alerts

    cutoff = time.time() - retention_seconds
    _blocked_alerts = [b for b in _blocked_alerts if b.get("timestamp", 0) > cutoff]


def append_log(event: dict) -> None:
    rollover_log()
    history = []
    if LOG_FILE.exists():
        try:
            history = json.loads(LOG_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            history = []
    history.append(event)
    LOG_FILE.write_text(json.dumps(history, indent=2), encoding="utf-8")


# ------------------ Healthcheck endpoint ------------------


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            try:
                import json

                # Récupère la valeur de LAST_LOOP_TS via Prometheus registry
                loop_ts = 0.0
                watchlist_size = 0
                last_profit = 0.0
                try:
                    samples = list(LAST_LOOP_TS.collect()[0].samples)
                    if samples:
                        loop_ts = samples[0].value
                    samples = list(WATCHLIST_SIZE.collect()[0].samples)
                    if samples:
                        watchlist_size = int(samples[0].value)
                    # Récupère dernier profit (exemple)
                    samples = list(PROFIT_GAUGE.collect()[0].samples)
                    if samples:
                        last_profit = max(s.value for s in samples)
                except Exception:
                    pass

                ok = (time.time() - loop_ts) < 180 if loop_ts > 0 else False
                if ok and APP_UP.collect()[0].samples[0].value > 0:
                    # [DAAS] Health check enrichi avec métriques
                    health_data = {
                        "status": "OK",
                        "loop_ts": loop_ts,
                        "watchlist_size": watchlist_size,
                        "last_profit": last_profit,
                        "dry_run": DRY_RUN,
                        "daas_mode": CONFIG.daas_mode,
                    }
                    self.send_response(200)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(health_data).encode())
                else:
                    self.send_response(500)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "STALE"}).encode())
            except Exception as exc:
                self.send_response(500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ERROR", "error": str(exc)}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Supprime les logs HTTP


def start_health_server(port: int = 8001) -> None:
    """Démarre un serveur HTTP pour /healthz."""
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.timeout = 1
    import threading

    def serve():
        while True:
            server.handle_request()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()


# ------------------ Main ------------------


async def main_async() -> None:
    # Initialisation persistance
    init_state_db()
    load_state()

    # Initialisation copy-trader
    if COPY_TRADER_ENABLED:
        init_copy_trader()

    # [DAAS] Initialisation service API
    alerts_queue: List[dict] = []  # Queue partagée pour API service

    if CONFIG.daas_mode:
        from .api_auth import ApiAuth
        from .api_service import start_api_server
        from .rate_limiter import RateLimiter

        api_auth = ApiAuth()
        rate_limiter = RateLimiter()

        start_api_server(api_auth, rate_limiter, alerts_queue, port=CONFIG.api.api_port)
        LOGGER.info("api service started", extra={"port": CONFIG.api.api_port})

    # Initialisation métriques "vivantes"
    APP_UP.set(1)
    APP_START_TS.set(time.time())

    # Chargement données
    df, watchlist = load_initial_data()

    # Initialisation métriques watchlist
    WATCHLIST_SIZE.set(len(watchlist))
    for wallet in watchlist:
        ensure_wallet_series(wallet)

    print_health(df, watchlist)
    start_http_server(PROMETHEUS_PORT)
    start_health_server(8001)

    # Handler sauvegarde état à l'arrêt
    def save_on_exit():
        save_state()
        # Envoyer notification d'arrêt de manière synchrone (dans un thread séparé pour éviter les conflits)
        if DISCORD_WEBHOOK:
            try:
                import threading

                def send_notification():
                    try:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(
                            send_discord_system_notification_async(
                                "stopped",
                                "Wallet Monitor Bot s'est arrêté.",
                                {
                                    "watchlist_size": len(watchlist),
                                    "uptime": f"{(time.time() - APP_START_TS._value.get()):.0f}s"
                                    if hasattr(APP_START_TS, "_value")
                                    else "N/A",
                                },
                            )
                        )
                        loop.close()
                    except Exception:
                        pass

                thread = threading.Thread(target=send_notification, daemon=True)
                thread.start()
                thread.join(timeout=3)
            except Exception as e:
                LOGGER.warning("failed to send stop notification on exit", extra={"error": str(e)})

    atexit.register(save_on_exit)
    signal.signal(signal.SIGTERM, lambda s, f: (save_on_exit(), exit(0)))
    signal.signal(signal.SIGINT, lambda s, f: (save_on_exit(), exit(0)))

    # Envoyer notification de démarrage
    await send_discord_system_notification_async(
        "started",
        "Wallet Monitor Bot est maintenant en ligne.",
        {
            "watchlist_size": len(watchlist),
            "rpc_endpoints": len(RPC_ENDPOINTS),
            "prometheus_port": PROMETHEUS_PORT,
        },
    )

    # Initialise cache prix tokens
    price_cache = TokenPriceCache()

    alerts: List[dict] = []
    cluster_counter: CollCounter[str] = CollCounter()

    # [DAAS] Queue partagée pour API service (doit être accessible dans scan_wallet_async)
    # Note: alerts_queue est créé dans main_async() et passé à scan_wallet_async()
    debug_flag = _env_bool("DEBUG_FORCE_ALERT", False)
    if debug_flag:
        forced_wallet = os.getenv("DEBUG_FORCE_ALERT_WALLET", "TEST_WALLET_FORCED")
        forced_profit = float(os.getenv("DEBUG_FORCE_ALERT_PROFIT", "0.7"))
        now = dt.datetime.now(dt.timezone.utc)
        alert_event = {
            "wallet": forced_wallet,
            "profit": forced_profit,
            "dex": "Debug",
            "win_rate": 100.0,
            "timestamp": now,
            "counterparties": [],
            "signal_type": "Debug",
            "zscore": 0.0,
            "signature": None,
            "detect_ms": 0.0,
            "dry_run": DRY_RUN,
        }
        alerts.append(alert_event)
        mark_alert(forced_wallet, [f"debug-{now.timestamp()}"])
        ALERT_COUNTER.labels(wallet=forced_wallet).inc()
        PROFIT_GAUGE.labels(wallet=forced_wallet).set(forced_profit)
        LAST_ALERT_TS.labels(wallet=forced_wallet).set(time.time())
        send_alert(
            forced_wallet, forced_profit, "Debug", 100.0, "Debug", 0.0, None, 0.0, tier="free"
        )
        await send_discord_alert_async(
            forced_wallet,
            forced_profit,
            "Debug",
            100.0,
            "Debug",
            0.0,
            None,
            0.0,
            tier="free",
        )
    last_report_ts = dt.datetime.fromtimestamp(0, tz=dt.timezone.utc)
    last_detailed_report_ts = dt.datetime.fromtimestamp(0, tz=dt.timezone.utc)
    last_heartbeat_ts = dt.datetime.fromtimestamp(0, tz=dt.timezone.utc)

    save_counter = 0
    sem = asyncio.Semaphore(MAX_CONCURRENCY)

    async with AsyncRpcManager(RPC_ENDPOINTS) as rpc:
        if REPORT_INITIAL_DELAY_SECONDS >= 0:
            if REPORT_INITIAL_DELAY_SECONDS:
                await asyncio.sleep(REPORT_INITIAL_DELAY_SECONDS)

            startup_report = generate_detailed_report(
                df, alerts, cluster_counter, watchlist, rpc
            )
            save_detailed_report(
                startup_report, title_override="🚀 Rapport initial - Bot prêt"
            )
            now_ts = dt.datetime.now(dt.timezone.utc)
            last_detailed_report_ts = now_ts
            last_heartbeat_ts = now_ts

        while True:
            loop_start = dt.datetime.now(dt.timezone.utc)
            LAST_LOOP_TS.set(time.time())
            garbage_collect_state(loop_start.timestamp())

            tasks = []
            for wallet in list(watchlist):
                ensure_wallet_series(wallet)
                tasks.append(
                    scan_wallet_async(
                        wallet,
                        rpc,
                        df,
                        watchlist,
                        price_cache,
                        alerts,
                        cluster_counter,
                        sem,
                        alerts_queue,
                    )
                )

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    LOGGER.error("scan wallet exception", extra={"error": str(result)})

            WATCHLIST_SIZE.set(len(watchlist))

            # Générer rapport détaillé selon REPORT_REFRESH_SECONDS (minimum 600s = 10 min)
            report_interval = max(REPORT_REFRESH_SECONDS, 600)
            if (loop_start - last_report_ts).total_seconds() >= report_interval:
                update_dashboard(df, alerts)
                update_report(df, alerts, cluster_counter)

                # Générer rapport détaillé enrichi si minimum interval respecté
                if (
                    REPORT_MIN_INTERVAL_SECONDS >= 0
                    and (loop_start - last_detailed_report_ts).total_seconds()
                    >= REPORT_MIN_INTERVAL_SECONDS
                ):
                    detailed_report = generate_detailed_report(
                        df, alerts, cluster_counter, watchlist, rpc
                    )
                    save_detailed_report(detailed_report)  # Sauvegarde ET envoie sur Discord (avec format enrichi)
                    last_detailed_report_ts = loop_start

                # Nettoyer les alertes bloquées (garder seulement les 2 dernières heures)
                global _blocked_alerts
                cutoff = time.time() - 7200
                _blocked_alerts = [b for b in _blocked_alerts if b.get("timestamp", 0) > cutoff]

                last_report_ts = loop_start
                prune_blocked_alerts()

            if HEARTBEAT_INTERVAL_SECONDS > 0:
                if (
                    loop_start - last_heartbeat_ts
                ).total_seconds() >= HEARTBEAT_INTERVAL_SECONDS:
                    detailed_report_payload = generate_detailed_report(
                        df, alerts, cluster_counter, watchlist, rpc
                    )
                    await send_report_to_discord(
                        detailed_report_payload, title_override="👀 Heartbeat - Bot actif"
                    )
                    prune_blocked_alerts()
                    last_heartbeat_ts = loop_start

            save_counter += 1
            if save_counter >= 10:
                save_state()
                save_counter = 0

            elapsed = (dt.datetime.now(dt.timezone.utc) - loop_start).total_seconds()
            await asyncio.sleep(max(5.0, TX_REFRESH_SECONDS - elapsed))


def main() -> None:
    """Point d'entrée principal (synchrone, lance l'async loop)."""
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        LOGGER.info("shutdown requested")
    except Exception as e:
        LOGGER.error("fatal error", extra={"error": str(e)})
        # Envoyer notification d'erreur si possible
        if DISCORD_WEBHOOK:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(
                    send_discord_system_notification_async(
                        "error",
                        f"Erreur fatale: {str(e)}",
                    )
                )
                loop.close()
            except Exception:
                pass
        raise


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        LOGGER.info("shutdown requested")
