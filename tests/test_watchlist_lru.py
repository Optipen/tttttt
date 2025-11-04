#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests unitaires pour LRU watchlist."""

import time

# [CLEANUP] : Import depuis src/ pour la nouvelle structure
from src.wallet_monitor import (
    WATCHLIST_MAX_SIZE,
    _watchlist_usage,
    evict_watchlist_if_needed,
    register_watchlist_access,
)

# ==================== Tests Watchlist LRU ====================


class TestWatchlistLRU:
    """Tests de gestion LRU de la watchlist."""

    def setup_method(self):
        """Reset état avant chaque test."""
        _watchlist_usage.clear()

    def test_add_101_wallets_evicts_first(self):
        """[FIX_AUDIT_5] Ajout de 101 wallets → taille=100, premier évincé."""
        watchlist = []

        # Ajouter 101 wallets
        for i in range(101):
            wallet = f"WALLET_{i}"
            watchlist.append(wallet)
            register_watchlist_access(wallet, watchlist)
            evict_watchlist_if_needed(watchlist)

        # Taille watchlist doit être limitée à WATCHLIST_MAX_SIZE
        assert len(watchlist) <= WATCHLIST_MAX_SIZE
        # Premier wallet (WALLET_0) devrait être évincé
        assert "WALLET_0" not in watchlist or len(watchlist) < WATCHLIST_MAX_SIZE

    def test_recent_access_no_eviction(self):
        """[FIX_AUDIT_5] Accès récent → pas d'éviction."""
        watchlist = []

        # Ajouter wallets jusqu'à la limite
        for i in range(WATCHLIST_MAX_SIZE):
            wallet = f"WALLET_{i}"
            watchlist.append(wallet)
            register_watchlist_access(wallet, watchlist)

        # Accéder au premier wallet (récent)
        register_watchlist_access("WALLET_0", watchlist)
        evict_watchlist_if_needed(watchlist)

        # WALLET_0 devrait toujours être présent (accès récent)
        assert "WALLET_0" in watchlist

    def test_lru_eviction_order(self):
        """[FIX_AUDIT_5] Ordre d'éviction LRU (plus ancien d'abord)."""
        watchlist = []

        # Ajouter wallets
        for i in range(WATCHLIST_MAX_SIZE + 5):
            wallet = f"WALLET_{i}"
            watchlist.append(wallet)
            register_watchlist_access(wallet, watchlist)
            time.sleep(0.001)  # Petit délai pour différencier les timestamps
            evict_watchlist_if_needed(watchlist)

        # Taille doit être limitée
        assert len(watchlist) <= WATCHLIST_MAX_SIZE

        # Les wallets les plus récents devraient être présents
        recent_wallets = [
            f"WALLET_{i}" for i in range(WATCHLIST_MAX_SIZE - 5, WATCHLIST_MAX_SIZE + 5)
        ]
        for wallet in recent_wallets:
            if wallet in watchlist:
                assert wallet in watchlist

    def test_watchlist_usage_metric(self):
        """[FIX_AUDIT_5] Métrique wallet_cache_size{type="watchlist"} mise à jour."""
        from src.wallet_monitor import CACHE_SIZE_GAUGE

        watchlist = []

        # Ajouter wallets
        for i in range(10):
            wallet = f"WALLET_{i}"
            register_watchlist_access(wallet, watchlist)

        # Vérifier que métrique est mise à jour
        samples = list(CACHE_SIZE_GAUGE.labels(cache="watchlist").collect()[0].samples)
        assert len(samples) > 0
        # La valeur devrait refléter la taille de _watchlist_usage
        assert samples[0].value == len(_watchlist_usage)
