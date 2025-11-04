"""Service HTTP API pour DaaS."""

import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

from .api_auth import ApiAuth
from .config import CONFIG
from .rate_limiter import RateLimiter

LOGGER = logging.getLogger("api_service")

# [DAAS] Métriques Prometheus pour API
# Note: API_CALLS_TOTAL est défini dans wallet_monitor.py pour éviter duplication
# Import depuis wallet_monitor si nécessaire


class ApiHandler(BaseHTTPRequestHandler):
    """Handler HTTP pour API DaaS."""

    def __init__(
        self, *args, api_auth: ApiAuth, rate_limiter: RateLimiter, alerts_queue: list, **kwargs
    ):
        self.api_auth = api_auth
        self.rate_limiter = rate_limiter
        self.alerts_queue = alerts_queue
        super().__init__(*args, **kwargs)

    def do_GET(self):
        """Gère les requêtes GET."""
        if self.path == "/healthz":
            self._handle_healthz()
        elif self.path.startswith("/api/v1/signals"):
            self._handle_signals()
        elif self.path.startswith("/api/v1/wallet/"):
            self._handle_wallet_score()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        """Gère les requêtes POST."""
        if self.path == "/api/v1/billing/webhook":
            self._handle_billing_webhook()
        elif self.path == "/api/v1/billing/fake-checkout":
            self._handle_fake_checkout()
        else:
            self.send_response(404)
            self.end_headers()

    def _get_api_key(self) -> Optional[str]:
        """Récupère l'API key depuis le header."""
        api_key = self.headers.get("x-api-key")
        return api_key

    def _authenticate(self) -> Optional[tuple]:
        """Authentifie la requête."""
        api_key = self._get_api_key()
        if not api_key:
            return None

        result = self.api_auth.validate_key(api_key)
        if not result:
            return None

        tier, is_active = result
        return (api_key, tier, is_active)

    def _handle_healthz(self):
        """Health check endpoint."""
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "OK"}).encode())

    def _handle_signals(self):
        """Endpoint GET /api/v1/signals."""
        auth = self._authenticate()
        if not auth:
            self.send_response(401)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Unauthorized"}).encode())
            return

        api_key, tier, is_active = auth

        # [DAAS] Métrique API calls
        from src.wallet_monitor import API_CALLS_TOTAL

        API_CALLS_TOTAL.labels(endpoint="/api/v1/signals", tier=tier).inc()

        # Rate limiting
        key_hash = self.api_auth.hash_key(api_key)
        allowed, remaining, limit = self.rate_limiter.check_limit(key_hash, tier)

        if not allowed:
            self.send_response(429)
            self.send_header("Content-type", "application/json")
            self.send_header("X-RateLimit-Remaining", "0")
            self.send_header("X-RateLimit-Limit", str(limit))
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Rate limit exceeded"}).encode())
            return

        # Récupère dernières alertes depuis queue
        signals = list(self.alerts_queue[-100:])  # Dernières 100 alertes

        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.send_header("X-RateLimit-Remaining", str(remaining))
        self.send_header("X-RateLimit-Limit", str(limit))
        self.end_headers()
        self.wfile.write(json.dumps({"signals": signals, "count": len(signals)}).encode())

    def _handle_wallet_score(self):
        """Endpoint GET /api/v1/wallet/{address}/score."""
        auth = self._authenticate()
        if not auth:
            self.send_response(401)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Unauthorized"}).encode())
            return

        api_key, tier, is_active = auth

        # [DAAS] Métrique API calls
        from src.wallet_monitor import API_CALLS_TOTAL

        API_CALLS_TOTAL.labels(endpoint="/api/v1/wallet/{address}/score", tier=tier).inc()

        # Rate limiting
        key_hash = self.api_auth.hash_key(api_key)
        allowed, remaining, limit = self.rate_limiter.check_limit(key_hash, tier)

        if not allowed:
            self.send_response(429)
            self.send_header("Content-type", "application/json")
            self.send_header("X-RateLimit-Remaining", "0")
            self.send_header("X-RateLimit-Limit", str(limit))
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Rate limit exceeded"}).encode())
            return

        # Extraire wallet address depuis path
        wallet_address = self.path.split("/")[-1]

        # TODO: Récupérer score depuis wallet_monitor
        # Pour MVP, retourner données mockées
        score_data = {
            "wallet": wallet_address,
            "tier": tier,
            "score": {
                "z_score": 0.0,
                "win_rate": 0.0,
                "net_total": 0.0,
            },
        }

        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.send_header("X-RateLimit-Remaining", str(remaining))
        self.send_header("X-RateLimit-Limit", str(limit))
        self.end_headers()
        self.wfile.write(json.dumps(score_data).encode())

    def _handle_billing_webhook(self):
        """Endpoint POST /api/v1/billing/webhook (Stripe)."""
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            data = json.loads(body.decode())
            event_type = data.get("type")

            # [DAAS] Métrique webhooks Stripe
            from src.wallet_monitor import STRIPE_WEBHOOKS_PROCESSED_TOTAL

            STRIPE_WEBHOOKS_PROCESSED_TOTAL.labels(event=event_type).inc()

            # TODO: Valider signature Stripe

            # Traiter webhook
            from .billing import BillingService

            billing = BillingService(self.api_auth)
            result = billing.handle_stripe_webhook(event_type, data.get("data", {}))

            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "result": result}).encode())
        except Exception as exc:
            LOGGER.error("billing webhook error", extra={"error": str(exc)})
            self.send_response(500)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(exc)}).encode())

    def _handle_fake_checkout(self):
        """Endpoint POST /api/v1/billing/fake-checkout (MVP)."""
        if not CONFIG.billing.fake_checkout_enabled:
            self.send_response(403)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Fake checkout disabled"}).encode())
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            data = json.loads(body.decode())
            tier = data.get("tier", "free")
            email = data.get("email", "")

            from .billing import BillingService

            billing = BillingService(self.api_auth)
            result = billing.fake_checkout(tier, email)

            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
        except Exception as exc:
            LOGGER.error("fake checkout error", extra={"error": str(exc)})
            self.send_response(500)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(exc)}).encode())

    def log_message(self, format, *args):
        """Supprime les logs HTTP par défaut."""
        pass


def start_api_server(
    api_auth: ApiAuth, rate_limiter: RateLimiter, alerts_queue: list, port: int = None
) -> None:
    """Démarre le serveur API HTTP."""
    port = port or CONFIG.api.api_port
    host = CONFIG.api.api_host

    def handler_factory(*args, **kwargs):
        return ApiHandler(
            *args, api_auth=api_auth, rate_limiter=rate_limiter, alerts_queue=alerts_queue, **kwargs
        )

    server = HTTPServer((host, port), handler_factory)
    server.timeout = 1

    import threading

    def serve():
        while True:
            server.handle_request()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()

    LOGGER.info("api server started", extra={"host": host, "port": port})
