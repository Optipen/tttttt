"""Module rate limiting pour API DaaS."""

import time
from collections import defaultdict
from typing import Dict, Tuple

from .config import CONFIG


class RateLimiter:
    """Rate limiter simple en mémoire (MVP)."""

    def __init__(self):
        self.limits = {
            "free": CONFIG.api.rate_limit_free,
            "pro": CONFIG.api.rate_limit_pro,
            "elite": CONFIG.api.rate_limit_elite,
        }
        # (api_key_hash, count, reset_time)
        self._counters: Dict[str, Tuple[int, float]] = defaultdict(lambda: (0, time.time()))

    def _get_reset_time(self) -> float:
        """Retourne le timestamp de reset (début de journée)."""
        time.time()
        # Reset à minuit UTC
        import datetime

        today = datetime.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        return today.timestamp()

    def check_limit(self, api_key_hash: str, tier: str) -> Tuple[bool, int, int]:
        """
        Vérifie si la limite est atteinte.

        Returns:
            (allowed, remaining, limit)
        """
        limit = self.limits.get(tier, self.limits["free"])

        reset_time = self._get_reset_time()
        count, last_reset = self._counters[api_key_hash]

        # Reset si nouveau jour
        if last_reset < reset_time:
            count = 0
            last_reset = reset_time

        remaining = max(0, limit - count)
        allowed = count < limit

        if allowed:
            count += 1

        self._counters[api_key_hash] = (count, last_reset)

        return (allowed, remaining, limit)

    def get_usage(self, api_key_hash: str, tier: str) -> Tuple[int, int]:
        """Retourne l'usage actuel (count, limit)."""
        limit = self.limits.get(tier, self.limits["free"])

        reset_time = self._get_reset_time()
        count, last_reset = self._counters[api_key_hash]

        # Reset si nouveau jour
        if last_reset < reset_time:
            count = 0

        return (count, limit)
