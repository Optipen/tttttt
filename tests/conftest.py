"""Configuration pytest pour tous les tests."""

import sys
from pathlib import Path

import pytest

# [CLEANUP] : Ajouter le répertoire racine au PYTHONPATH pour imports src/
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "src"))


# Fixtures globales
@pytest.fixture(autouse=True)
def reset_env():
    """Reset variables d'env avant chaque test."""
    yield
    # Cleanup après test si nécessaire
    pass


@pytest.fixture
def fixtures_dir():
    """Répertoire fixtures."""
    # [CLEANUP] : Chemin mis à jour pour la nouvelle structure
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def mock_config():
    """Mock CONFIG pour tests."""
    from unittest.mock import Mock

    config = Mock()
    config.metrics.balance_tolerance_pct = 10.0
    config.alerting.dry_run = False
    config.alerting.watchlist_max_size = 100
    config.alerting.state_ttl_seconds = 3600
    config.alerting.max_seen_signatures = 50000
    config.rpc.circuit_breaker_failures = 3
    config.rpc.circuit_breaker_pause_sec = 5.0
    config.rpc.timeout_sec = 2.5
    config.rpc.max_retries = 3
    config.rpc.jitter_base = 0.5
    config.rpc.jitter_max = 0.2
    return config
