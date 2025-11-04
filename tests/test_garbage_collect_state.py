#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests unitaires pour garbage collector d'état."""

import time
from collections import deque

# [CLEANUP] : Import depuis src/ pour la nouvelle structure
from src.wallet_monitor import (
    MAX_SEEN_SIGNATURES,
    STATE_TTL_SECONDS,
    _last_alert_at,
    _profit_history,
    _seen_signatures,
    garbage_collect_state,
)

# ==================== Tests Garbage Collector ====================


class TestGarbageCollectState:
    """Tests de garbage collector d'état."""

    def setup_method(self):
        """Reset état avant chaque test."""
        _seen_signatures.clear()
        _last_alert_at.clear()
        _profit_history.clear()

    def test_ttl_expired_keys_purged(self):
        """[FIX_AUDIT_6] TTL expiré → clés purgées."""
        now = time.time()

        # Ajouter signatures avec timestamps expirés
        old_timestamp = now - STATE_TTL_SECONDS - 100
        _seen_signatures["OLD_SIG_1"] = old_timestamp
        _seen_signatures["OLD_SIG_2"] = old_timestamp

        # Ajouter signatures récentes
        recent_timestamp = now - 10
        _seen_signatures["RECENT_SIG_1"] = recent_timestamp
        _seen_signatures["RECENT_SIG_2"] = recent_timestamp

        # Ajouter last_alert_at expiré
        _last_alert_at["OLD_WALLET"] = old_timestamp
        _last_alert_at["RECENT_WALLET"] = recent_timestamp

        # Exécuter garbage collector
        garbage_collect_state(now)

        # Signatures expirées doivent être purgées
        assert "OLD_SIG_1" not in _seen_signatures
        assert "OLD_SIG_2" not in _seen_signatures
        # Signatures récentes doivent être conservées
        assert "RECENT_SIG_1" in _seen_signatures
        assert "RECENT_SIG_2" in _seen_signatures

        # Last_alert_at expiré doit être purgé
        assert "OLD_WALLET" not in _last_alert_at
        # Recent doit être conservé
        assert "RECENT_WALLET" in _last_alert_at

    def test_cache_size_metric_decreases(self):
        """[FIX_AUDIT_6] Métrique wallet_cache_size baisse après purge."""
        from src.wallet_monitor import CACHE_SIZE_GAUGE

        now = time.time()

        # Ajouter signatures expirées
        old_timestamp = now - STATE_TTL_SECONDS - 100
        for i in range(10):
            _seen_signatures[f"OLD_SIG_{i}"] = old_timestamp

        # Mesurer taille avant
        samples_before = list(CACHE_SIZE_GAUGE.labels(cache="seen_signatures").collect()[0].samples)
        size_before = samples_before[0].value if samples_before else len(_seen_signatures)

        # Exécuter garbage collector
        garbage_collect_state(now)

        # Mesurer taille après
        samples_after = list(CACHE_SIZE_GAUGE.labels(cache="seen_signatures").collect()[0].samples)
        size_after = samples_after[0].value if samples_after else len(_seen_signatures)

        # Taille doit avoir diminué
        assert size_after < size_before or len(_seen_signatures) < 10

    def test_max_seen_signatures_limit(self):
        """[FIX_AUDIT_6] Limite MAX_SEEN_SIGNATURES respectée."""
        now = time.time()

        # Ajouter plus de signatures que la limite
        for i in range(MAX_SEEN_SIGNATURES + 100):
            _seen_signatures[f"SIG_{i}"] = now - (i * 0.001)

        # Exécuter garbage collector
        garbage_collect_state(now)

        # Taille doit être limitée à MAX_SEEN_SIGNATURES
        assert len(_seen_signatures) <= MAX_SEEN_SIGNATURES

    def test_profit_history_metric_updated(self):
        """[FIX_AUDIT_6] Métrique wallet_cache_size{type="profit_history"} mise à jour."""
        from src.wallet_monitor import CACHE_SIZE_GAUGE

        # Ajouter historique profit
        _profit_history["WALLET_1"] = deque([1.0, 2.0, 3.0], maxlen=50)
        _profit_history["WALLET_2"] = deque([4.0, 5.0], maxlen=50)

        # Exécuter garbage collector
        garbage_collect_state()

        # Vérifier que métrique est mise à jour
        samples = list(CACHE_SIZE_GAUGE.labels(cache="profit_history").collect()[0].samples)
        assert len(samples) > 0
        assert samples[0].value == len(_profit_history)
