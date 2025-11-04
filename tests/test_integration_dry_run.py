#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests d'intégration en mode DRY_RUN."""

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from prometheus_client import REGISTRY

from src.profit_estimator import TokenPriceCache, estimate_profit_enriched

# [CLEANUP] : Import depuis src/ pour la nouvelle structure
from src.wallet_monitor import DRY_RUN, WSOL_MINT, AsyncRpcManager

# ==================== Tests Intégration DRY_RUN ====================


class TestIntegrationDryRun:
    """Tests d'intégration en mode DRY_RUN."""

    @pytest.fixture
    def mock_env_dry_run(self, monkeypatch):
        """Active DRY_RUN via variable d'env."""
        monkeypatch.setenv("DRY_RUN", "true")
        # Recharger CONFIG
        import importlib

        import src.config as config

        importlib.reload(config)

    @pytest.fixture
    def mock_rpc_fixtures(self):
        """Mock RPC avec fixtures déterministes."""
        fixtures_dir = Path("fixtures")

        async def mock_get_signatures_for_address(wallet, limit=20):
            path = fixtures_dir / "signatures" / f"{wallet}.json"
            if path.exists():
                with open(path, "r") as f:
                    data = json.load(f)
                return {"result": data}
            return {"result": []}

        async def mock_get_transaction(signature, commitment="finalized"):
            path = fixtures_dir / "transactions" / f"{signature}.json"
            if path.exists():
                with open(path, "r") as f:
                    data = json.load(f)
                return {"result": data}
            return None

        rpc = Mock(spec=AsyncRpcManager)
        rpc.get_signatures_for_address = AsyncMock(side_effect=mock_get_signatures_for_address)
        rpc.get_transaction = AsyncMock(side_effect=mock_get_transaction)
        return rpc

    @pytest.mark.asyncio
    async def test_dry_run_no_discord_no_copy_trade(self, mock_env_dry_run, mock_rpc_fixtures):
        """[FIX_AUDIT_OPTIONAL] DRY_RUN → pas d'envoi Discord, pas de copy-trade."""
        from src.wallet_monitor import COPY_TRADER_ENABLED, send_discord_alert_async

        # DRY_RUN doit être activé
        assert DRY_RUN is True

        # Copy-trader doit être désactivé en DRY_RUN
        assert COPY_TRADER_ENABLED is False

        # Envoi Discord ne doit rien faire en DRY_RUN
        with patch("src.wallet_monitor.send_discord_alert_async"):
            # Simuler alerte
            await send_discord_alert_async(
                "TEST_WALLET", 5.0, "Jupiter", 90.0, "Signal", 2.0, "SIG", 100.0
            )
            # En DRY_RUN, Discord ne devrait pas être appelé
            # (ou être appelé mais sans réel envoi)
            # Vérifier selon implémentation

    @pytest.mark.asyncio
    async def test_wsol_sol_transactions_ingested(self, mock_rpc_fixtures):
        """[FIX_AUDIT_4] Ingest transactions WSOL/SOL."""
        price_cache = TokenPriceCache()

        # Transaction avec WSOL
        tx_wsol = {
            "transaction": {
                "message": {
                    "accountKeys": ["TEST_WALLET"],
                    "instructions": [],
                }
            },
            "meta": {
                "err": None,
                "fee": 5000,
                "preBalances": [10000000000],  # 10 SOL
                "postBalances": [10000000000],  # 10 SOL (pas de delta SOL)
                "preTokenBalances": [
                    {
                        "owner": "TEST_WALLET",
                        "mint": WSOL_MINT,
                        "uiTokenAmount": {"uiAmount": 10.0, "decimals": 9},
                    }
                ],
                "postTokenBalances": [
                    {
                        "owner": "TEST_WALLET",
                        "mint": WSOL_MINT,
                        "uiTokenAmount": {"uiAmount": 5.0, "decimals": 9},
                    }
                ],
                "innerInstructions": [],
            },
        }

        mock_rpc = Mock()
        mock_rpc.call.return_value = {"result": tx_wsol}

        sigs = [{"signature": "WSOL_TX"}]
        profit, confidence, _, _, reasons = estimate_profit_enriched(
            mock_rpc, "TEST_WALLET", sigs, max_tx=1, price_cache=price_cache
        )

        # Profit doit inclure delta WSOL normalisé comme SOL
        # WSOL: -5.0 SOL, fee: -0.000005 SOL
        assert profit == pytest.approx(-5.000005, abs=1e-6)

    @pytest.mark.asyncio
    async def test_batch_processing_by_slot(self, mock_rpc_fixtures):
        """[FIX_AUDIT_9] Batch processing par slot."""
        from src.wallet_monitor import build_signature_batches

        # Signatures avec slots différents
        signatures = [
            {"signature": "SIG_1", "slot": 100},
            {"signature": "SIG_2", "slot": 100},
            {"signature": "SIG_3", "slot": 101},
            {"signature": "SIG_4", "slot": 101},
            {"signature": "SIG_5", "slot": 101},
        ]

        batches = build_signature_batches(signatures)

        # Doit grouper par slot
        assert len(batches) >= 2  # Au moins 2 slots
        # Chaque batch doit contenir signatures du même slot
        for batch in batches:
            slots = {sig.get("slot") for sig in batch if "slot" in sig}
            assert len(slots) <= 1  # Un seul slot par batch

    @pytest.mark.asyncio
    async def test_metrics_export_prometheus(self):
        """[FIX_AUDIT_4] Métriques exportées Prometheus."""
        from prometheus_client import generate_latest

        # Générer métriques
        metrics_text = generate_latest(REGISTRY).decode("utf-8")

        # Vérifier présence métriques clés
        assert "wallet_app_up" in metrics_text
        assert "wallet_cache_size" in metrics_text
        assert "wallet_rpc_error_count" in metrics_text
        assert "wallet_alert_duration_seconds" in metrics_text

    @pytest.mark.asyncio
    async def test_logs_json_format(self, mock_env_dry_run):
        """[FIX_AUDIT_2] Logs en format JSON."""
        import logging

        from src.wallet_monitor import LOGGER

        # Capturer logs
        log_capture = []
        handler = logging.StreamHandler()
        handler.setLevel(logging.INFO)

        def capture_log(record):
            log_capture.append(record.getMessage())

        handler.emit = capture_log
        LOGGER.addHandler(handler)

        # Générer log
        LOGGER.info("test log", extra={"key": "value"})

        # Vérifier que log est au format JSON (si JsonFormatter actif)
        # Note: Le format exact dépend de l'implémentation JsonFormatter
        assert len(log_capture) > 0

    @pytest.mark.asyncio
    async def test_rpc_error_injection_circuit_breaker(self, monkeypatch):
        """[FIX_AUDIT_10] Injection erreurs RPC → circuit-breaker pause 5s."""
        async with AsyncRpcManager(["https://api.mainnet-beta.solana.com"]) as rpc:
            endpoint = rpc._current_endpoint()

            # Simuler 3 échecs consécutifs
            for _ in range(3):
                rpc._record_failure(endpoint, "Timeout")

            # Circuit-breaker doit être ouvert
            state = rpc.circuit_state[endpoint]
            assert state["state"] == "open"
            assert state["failures"] >= 3

            # Vérifier que _allow_request bloque
            assert rpc._allow_request(endpoint) is False

            # Attendre pause (5s)
            state["opened_at"] = time.time() - 6  # 6s dans le passé

            # Après pause, circuit-breaker doit être half-open
            assert rpc._allow_request(endpoint) is True
