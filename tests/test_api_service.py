"""Tests module api_service."""


import pytest

from src.api_auth import ApiAuth
from src.api_service import ApiHandler
from src.rate_limiter import RateLimiter


@pytest.fixture
def api_auth():
    """Crée une instance ApiAuth."""
    return ApiAuth()


@pytest.fixture
def rate_limiter():
    """Crée une instance RateLimiter."""
    return RateLimiter()


@pytest.fixture
def alerts_queue():
    """Crée une queue d'alertes vide."""
    return []


def test_api_auth_required(api_auth, rate_limiter, alerts_queue):
    """Test que l'API key est requise."""

    # Mock HTTP request sans header x-api-key
    class MockRequest:
        def __init__(self):
            self.headers = {}
            self.path = "/api/v1/signals"
            self.wfile = MockWFile()
            self.rfile = None

        def send_response(self, code):
            self.status_code = code

        def send_header(self, key, value):
            pass

        def end_headers(self):
            pass

    class MockWFile:
        def write(self, data):
            self.data = data

    handler = ApiHandler(
        MockRequest(),
        api_auth=api_auth,
        rate_limiter=rate_limiter,
        alerts_queue=alerts_queue,
    )

    handler._handle_signals()
    assert handler.status_code == 401


def test_api_auth_valid(api_auth, rate_limiter, alerts_queue):
    """Test que l'API key valide fonctionne."""
    # Créer API key
    api_key, _ = api_auth.create_key(tier="pro")

    # Mock HTTP request avec header x-api-key
    class MockRequest:
        def __init__(self, api_key):
            self.headers = {"x-api-key": api_key}
            self.path = "/api/v1/signals"
            self.wfile = MockWFile()
            self.rfile = None

        def send_response(self, code):
            self.status_code = code

        def send_header(self, key, value):
            pass

        def end_headers(self):
            pass

    class MockWFile:
        def write(self, data):
            self.data = data

    handler = ApiHandler(
        MockRequest(api_key),
        api_auth=api_auth,
        rate_limiter=rate_limiter,
        alerts_queue=alerts_queue,
    )

    handler._handle_signals()
    assert handler.status_code == 200


def test_rate_limiting(api_auth, rate_limiter):
    """Test rate limiting."""
    api_key, _ = api_auth.create_key(tier="free")
    key_hash = api_auth.hash_key(api_key)

    # Free tier: 10 appels/jour
    for i in range(10):
        allowed, remaining, limit = rate_limiter.check_limit(key_hash, "free")
        assert allowed is True
        assert remaining == 10 - i - 1

    # 11ème appel devrait être bloqué
    allowed, remaining, limit = rate_limiter.check_limit(key_hash, "free")
    assert allowed is False
    assert remaining == 0
