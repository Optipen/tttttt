"""Module d'authentification API pour DaaS."""

import hashlib
import secrets
import sqlite3
from pathlib import Path
from typing import Optional, Tuple

from .config import CONFIG


class ApiAuth:
    """Gestion authentification API keys."""

    def __init__(self, db_path: Path = None):
        self.db_path = db_path or CONFIG.billing.api_keys_db
        self._init_db()

    def _init_db(self) -> None:
        """Initialise la base de données API keys."""
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key_hash TEXT UNIQUE NOT NULL,
                tier TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL,
                is_active INTEGER NOT NULL DEFAULT 1
            )
        """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                api_key_id INTEGER NOT NULL,
                tier TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY (api_key_id) REFERENCES api_keys(id)
            )
        """
        )
        conn.commit()
        conn.close()

    def hash_key(self, api_key: str) -> str:
        """Hash une API key (SHA256)."""
        return hashlib.sha256(api_key.encode()).hexdigest()

    def generate_key(self) -> str:
        """Génère une nouvelle API key."""
        return f"daas_{secrets.token_urlsafe(32)}"

    def create_key(self, tier: str = "free", expires_at: Optional[float] = None) -> Tuple[str, str]:
        """
        Crée une nouvelle API key.

        Returns:
            (api_key, key_hash)
        """
        api_key = self.generate_key()
        key_hash = self.hash_key(api_key)

        import time

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            INSERT INTO api_keys (key_hash, tier, created_at, expires_at, is_active)
            VALUES (?, ?, ?, ?, 1)
        """,
            (key_hash, tier, time.time(), expires_at),
        )
        conn.commit()
        conn.close()

        return api_key, key_hash

    def validate_key(self, api_key: str) -> Optional[Tuple[str, bool]]:
        """
        Valide une API key.

        Returns:
            (tier, is_active) ou None si invalide
        """
        key_hash = self.hash_key(api_key)

        import time

        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            """
            SELECT tier, is_active, expires_at
            FROM api_keys
            WHERE key_hash = ?
        """,
            (key_hash,),
        )

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        tier, is_active, expires_at = row

        # Vérifier expiration
        if expires_at and time.time() > expires_at:
            return None

        # Vérifier actif
        if not is_active:
            return None

        return (tier, bool(is_active))

    def deactivate_key(self, api_key: str) -> bool:
        """Désactive une API key."""
        key_hash = self.hash_key(api_key)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            """
            UPDATE api_keys
            SET is_active = 0
            WHERE key_hash = ?
        """,
            (key_hash,),
        )

        updated = cursor.rowcount > 0
        conn.commit()
        conn.close()

        return updated

    def update_tier(self, api_key: str, new_tier: str) -> bool:
        """Met à jour le tier d'une API key."""
        key_hash = self.hash_key(api_key)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            """
            UPDATE api_keys
            SET tier = ?
            WHERE key_hash = ?
        """,
            (new_tier, key_hash),
        )

        updated = cursor.rowcount > 0
        conn.commit()
        conn.close()

        return updated
