#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Estimateur de profit enrichi avec support multi-hops et tokens."""

import os
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from solders.signature import Signature

# [FIX_AUDIT_8] : Import config pour BALANCE_TOLERANCE_PCT
# [CLEANUP] : Import relatif pour la nouvelle structure
try:
    from .config import CONFIG
except ImportError:
    # Fallback si config non disponible
    class CONFIG:
        class metrics:
            balance_tolerance_pct = 10.0


STATE_DB = Path("wallet_monitor_state.db")
PRICE_CACHE_DB = Path("token_price_cache.db")

# [FIX_AUDIT_4] : Normalisation WSOL → SOL natif
WSOL_MINT = "So11111111111111111111111111111111111111112"


class TokenPriceCache:
    """Cache simple pour les prix tokens (dernier prix vu)."""

    def __init__(self, db_path: Path = PRICE_CACHE_DB):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initialise la DB pour le cache prix."""
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS token_prices (
                mint TEXT PRIMARY KEY,
                price_sol REAL NOT NULL,
                last_seen REAL NOT NULL
            )
        """
        )
        conn.commit()
        conn.close()

    def get_price(self, mint: str, ttl_seconds: int = 60) -> Optional[float]:
        """Récupère le prix en SOL d'un token (dernier prix vu)."""
        if not self.db_path.exists():
            return None
        try:
            conn = sqlite3.connect(self.db_path)
            row = conn.execute(
                "SELECT price_sol, last_seen FROM token_prices WHERE mint = ?", (mint,)
            ).fetchone()
            conn.close()
            if not row:
                return None
            price_sol, last_seen = row
            if ttl_seconds and (time.time() - float(last_seen)) > ttl_seconds:
                return None
            return float(price_sol)
        except Exception:
            return None

    def set_price(self, mint: str, price_sol: float) -> None:
        """Met à jour le prix d'un token."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                """INSERT OR REPLACE INTO token_prices (mint, price_sol, last_seen)
                   VALUES (?, ?, ?)""",
                (mint, price_sol, time.time()),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass


def fetch_price_sol_from_jupiter(mint: str) -> Optional[float]:
    """Récupère le prix d'un token en SOL via l'API publique Jupiter.

    Stratégie:
    - Appel de `https://price.jup.ag/v6/price?ids=<mint>,So11111111111111111111111111111111111111112`
    - Convertit prix USD du token en SOL via (token_usd / sol_usd)
    - Retourne None si indisponible/erreur
    """
    try:
        sol_mint = "So11111111111111111111111111111111111111112"
        url = f"https://price.jup.ag/v6/price?ids={mint},{sol_mint}"
        resp = requests.get(url, timeout=5)
        if resp.status_code != 200:
            return None
        data = resp.json().get("data", {})
        token_entry = data.get(mint)
        sol_entry = data.get(sol_mint)
        if not token_entry or not sol_entry:
            return None
        token_usd = float(token_entry.get("price", 0.0) or 0.0)
        sol_usd = float(sol_entry.get("price", 0.0) or 0.0)
        if token_usd <= 0 or sol_usd <= 0:
            return None
        return token_usd / sol_usd
    except Exception:
        return None


def fetch_price_sol_from_birdeye(mint: str, api_key: str) -> Optional[float]:
    """Récupère le prix d'un token en SOL via l'API Birdeye (optionnel).

    Stratégie:
    - Appel de `https://public-api.birdeye.so/v1/price?address=<mint>`
    - Convertit prix USD en SOL via (token_usd / sol_usd_approx)
    - Retourne None si indisponible/erreur ou si api_key vide
    """
    if not api_key:
        return None
    try:
        url = "https://public-api.birdeye.so/v1/price"
        headers = {"X-API-KEY": api_key}
        params = {"address": mint}
        resp = requests.get(url, headers=headers, params=params, timeout=5)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if "data" not in data:
            return None
        token_usd = float(data["data"].get("value", 0.0) or 0.0)
        if token_usd <= 0:
            return None
        # Approximation: SOL ≈ $150 USD (mettre à jour si besoin)
        sol_usd_approx = 150.0
        return token_usd / sol_usd_approx
    except Exception:
        return None


def lamport_change(pre: List[int], post: List[int], keys: List[str], wallet: str) -> float:
    """Retourne la variation de balance SOL pour wallet sur une tx."""
    try:
        idx = keys.index(wallet)
        if idx < len(pre) and idx < len(post):
            return (post[idx] - pre[idx]) / 1e9
    except ValueError:
        pass
    return 0.0


def parse_token_balance(token_info: dict) -> Tuple[str, str, float, int]:
    """
    Parse token balance info.
    Retourne: (owner, mint, amount, decimals)
    """
    owner = token_info.get("owner", "")
    ui_amount = token_info.get("uiTokenAmount", {}) or {}
    amount = float(ui_amount.get("uiAmount", 0.0))
    mint = token_info.get("mint", "")
    decimals = int(ui_amount.get("decimals", 0))
    return owner, mint, amount, decimals


def estimate_token_delta(
    pre_tokens: List[dict], post_tokens: List[dict], wallet: str, price_cache: TokenPriceCache
) -> Tuple[float, float]:
    """
    Calcule la variation de valeur tokens en SOL équivalent.
    [FIX_AUDIT_4] : Normalise WSOL → SOL natif (retourne aussi delta WSOL pour normalisation)

    Retourne: (delta_sol, delta_wsol_sol)
    - delta_sol: delta tokens en SOL (sans WSOL)
    - delta_wsol_sol: delta WSOL en SOL (pour normalisation)
    """
    # Index par owner+mint
    pre_map: Dict[Tuple[str, str], float] = {}
    post_map: Dict[Tuple[str, str], float] = {}

    for token in pre_tokens:
        owner, mint, amount, _ = parse_token_balance(token)
        if owner == wallet:
            pre_map[(owner, mint)] = amount

    for token in post_tokens:
        owner, mint, amount, _ = parse_token_balance(token)
        if owner == wallet:
            post_map[(owner, mint)] = amount

    # Calcule delta par token
    delta_sol = 0.0
    delta_wsol_sol = 0.0
    all_mints = set(list(pre_map.keys()) + list(post_map.keys()))

    for owner, mint in all_mints:
        pre_amount = pre_map.get((owner, mint), 0.0)
        post_amount = post_map.get((owner, mint), 0.0)
        token_delta = post_amount - pre_amount

        if abs(token_delta) < 1e-9:
            continue

        # [FIX_AUDIT_4] : WSOL traité comme SOL natif (1:1)
        if mint == WSOL_MINT:
            delta_wsol_sol += token_delta
            continue

        # Récupère prix depuis cache (ordre: cache, Jupiter, Birdeye si clé dispo)
        price = price_cache.get_price(mint)
        if price is None:
            fetched = fetch_price_sol_from_jupiter(mint)
            if fetched is not None:
                price_cache.set_price(mint, fetched)
                price = fetched
            else:
                # Fallback Birdeye si clé API disponible
                birdeye_key = os.getenv("BIRDEYE_API_KEY", "").strip()
                if birdeye_key:
                    fetched = fetch_price_sol_from_birdeye(mint, birdeye_key)
                    if fetched is not None:
                        price_cache.set_price(mint, fetched)
                        price = fetched
            if price is None:
                # Pas de prix fiable → ignorer ce mint
                continue

        delta_sol += token_delta * price

    return delta_sol, delta_wsol_sol


def estimate_profit_enriched(
    rpc,
    wallet: str,
    signatures: List[dict],
    max_tx: int = 5,
    price_cache: Optional[TokenPriceCache] = None,
) -> Tuple[float, str, List[str], List[str]]:
    """
    Estimation de profit enrichie avec support tokens et multi-hops.

    Args:
        rpc: RpcManager instance
        wallet: Adresse wallet
        signatures: Liste de signatures à analyser
        max_tx: Nombre max de transactions à analyser
        price_cache: Cache prix tokens (optionnel)

    Returns:
        (profit_sol, pnl_confidence, counterparties, programs, confidence_reasons)
        - profit_sol: Profit estimé en SOL
        - pnl_confidence: "high" | "med" | "low"
        - counterparties: Liste des contreparties
        - programs: Liste des programmes utilisés
        - confidence_reasons: Dict avec price_coverage, route_complexity, fee_completeness, balance_alignment
    """
    if price_cache is None:
        price_cache = TokenPriceCache()

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

    for sig_info in signatures[:max_tx]:
        signature = sig_info.get("signature")
        if not signature:
            continue

        try:
            sig_param = Signature.from_string(signature)
        except ValueError:
            sig_param = signature

        tx_resp = rpc.call(
            "get_transaction",
            sig_param,
            commitment="finalized",
            encoding="json",
            max_supported_transaction_version=0,
        )
        if not tx_resp:
            continue

        # Normalise tx_resp
        if isinstance(tx_resp, dict):
            tx = tx_resp.get("result")
        else:
            tx_value = getattr(tx_resp, "value", None)
            tx = tx_value.to_json() if hasattr(tx_value, "to_json") else tx_value

        if not tx:
            continue

        if isinstance(tx, str):
            import json

            try:
                tx = json.loads(tx)
            except json.JSONDecodeError:
                continue

        meta = tx.get("meta") or {}
        msg = (tx.get("transaction") or {}).get("message") or {}

        # 1. SOL direct (comme avant)
        pre_sol = meta.get("preBalances", [])
        post_sol = meta.get("postBalances", [])
        raw_keys = msg.get("accountKeys") or []
        keys = [k["pubkey"] if isinstance(k, dict) and "pubkey" in k else k for k in raw_keys]
        sol_delta = lamport_change(pre_sol, post_sol, keys, wallet)
        profit += sol_delta

        # 2. Tokens (nouveau)
        pre_tokens = meta.get("preTokenBalances", []) or []
        post_tokens = meta.get("postTokenBalances", []) or []

        # Comptabiliser tokens pour price_coverage
        all_tokens_this_tx = set()
        for token in pre_tokens + post_tokens:
            mint = token.get("mint", "")
            if mint:
                all_tokens_this_tx.add(mint)
        total_tokens += len(all_tokens_this_tx)
        unique_mints.update(all_tokens_this_tx)

        # [FIX_AUDIT_4] : Normalisation WSOL → SOL natif
        token_delta_sol, delta_wsol_sol = estimate_token_delta(
            pre_tokens, post_tokens, wallet, price_cache
        )
        profit += token_delta_sol
        profit += delta_wsol_sol  # WSOL normalisé comme SOL natif
        token_delta_sum += abs(token_delta_sol)
        sol_delta_sum += abs(delta_wsol_sol)  # WSOL ajouté à sol_delta_sum

        # Vérifier si tokens pricés
        for mint in all_tokens_this_tx:
            if price_cache.get_price(mint, ttl_seconds=0) is not None:
                priced_tokens += 1

        # 3. Fees
        fee = meta.get("fee", 0) / 1e9
        fee_total += fee
        if fee == 0:
            fee_known = False
        profit -= fee

        # 4. Détection complexité (multi-hops)
        inner_instructions = meta.get("innerInstructions", []) or []
        total_inner_inst += len(inner_instructions)
        if len(inner_instructions) > 3:
            confidence = "med" if confidence == "high" else "low"

        # Si tokens mais pas de prix en cache → confidence réduite
        if (pre_tokens or post_tokens) and abs(token_delta_sol) < 1e-9:
            confidence = "med" if confidence == "high" else "low"

        # Sol delta pour balance_alignment
        sol_delta_sum += abs(sol_delta)

        # 5. Extraction programs et counterparties
        program_set = set()
        for inst in msg.get("instructions") or []:
            idx = inst.get("programIdIndex")
            if isinstance(idx, int) and 0 <= idx < len(keys):
                program_set.add(keys[idx])

        programs.extend(list(program_set))

        for addr in keys:
            if addr != wallet and addr not in program_set:
                counterparties.append(addr)

    # Dédupliquer
    programs = list(set(programs))
    counterparties = list(set(counterparties))

    # Calcul confidence_reasons
    price_coverage = (priced_tokens / total_tokens) if total_tokens > 0 else 1.0
    route_complexity = min(total_inner_inst / max(len(signatures[:max_tx]), 1), 10.0)  # normalisé
    fee_completeness = 1.0 if fee_known else 0.0
    # [FIX_AUDIT_8] : balance_alignment utilise BALANCE_TOLERANCE_PCT configurable
    total_valorized = abs(sol_delta_sum) + token_delta_sum
    total_observed = abs(profit) + fee_total
    tolerance = CONFIG.metrics.balance_tolerance_pct / 100.0  # Convertir % en décimal
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

    # Calcul pnl_confidence final (basé sur confidence + confidence_reasons)
    score = 2  # high
    if price_coverage < 0.7 or route_complexity > 5.0:
        score -= 1
    if fee_completeness < 1.0 or balance_alignment < 0.8:
        score -= 1
    pnl_confidence = ["low", "med", "high"][max(0, min(2, score))]

    return profit, pnl_confidence, counterparties, programs, confidence_reasons
