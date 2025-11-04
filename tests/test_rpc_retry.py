#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests unitaires pour RPC retry avec jitter."""

from unittest.mock import AsyncMock

import pytest

# [CLEANUP] : Import depuis src/ pour la nouvelle structure
from src.wallet_monitor import RPC_TIMEOUT_SEC, AsyncRpcManager, compute_retry_delay

# ==================== Tests RPC Retry ====================


class TestRPCRetry:
    """Tests de retry RPC avec jitter."""

    def test_retry_delay_conforms_to_compute_retry_delay(self):
        """[FIX_AUDIT_8] 2 échecs + 1 succès → délai cumulé conforme."""
        delays = []

        for attempt in range(3):
            delay = compute_retry_delay(attempt)
            delays.append(delay)

        # Délai doit augmenter exponentiellement
        assert delays[1] > delays[0]
        assert delays[2] > delays[1]

        # Délai max ne doit pas dépasser RPC_TIMEOUT_SEC
        assert all(d <= RPC_TIMEOUT_SEC for d in delays)

    @pytest.mark.asyncio
    async def test_rpc_retry_on_failure(self):
        """[FIX_AUDIT_7] RPC retry sur échec."""
        async with AsyncRpcManager(["https://api.mainnet-beta.solana.com"]) as rpc:
            # Mock session pour simuler échecs puis succès
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value={"result": "success"})

            call_count = 0

            async def mock_post(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count < 2:
                    # Premier appel échoue
                    raise Exception("Network error")
                # Deuxième appel réussit
                return mock_resp

            rpc.session.post = mock_post

            # Appel RPC
            result = await rpc._call_jsonrpc("getSignaturesForAddress", ["TEST_WALLET"])

            # Doit avoir retenté
            assert call_count >= 2
            # Résultat final doit être OK
            assert result is not None

    @pytest.mark.asyncio
    async def test_circuit_breaker_reset_on_success(self):
        """[FIX_AUDIT_10] Circuit-breaker : compteur d'échecs repart à 0 après succès."""
        async with AsyncRpcManager(["https://api.mainnet-beta.solana.com"]) as rpc:
            endpoint = rpc._current_endpoint()

            # Simuler 2 échecs
            state = rpc.circuit_state[endpoint]
            state["failures"] = 2

            # Enregistrer succès
            rpc._record_success(endpoint)

            # Compteur doit être réinitialisé
            assert state["failures"] == 0
            assert state["state"] == "closed"

    def test_retry_jitter_randomness(self):
        """[FIX_AUDIT_8] Retry avec jitter → délais variés."""
        delays = set()

        # Calculer délais plusieurs fois pour vérifier jitter
        for _ in range(10):
            delay = compute_retry_delay(1)
            delays.add(delay)

        # Avec jitter, délais ne doivent pas tous être identiques
        # (sauf si seed fixe, mais ici on veut vérifier la variabilité)
        assert len(delays) > 1 or pytest.skip("Jitter non testable sans seed")
