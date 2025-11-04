"""Module billing pour DaaS (Stripe webhooks simulés)."""

import sqlite3
import time
from typing import Dict, Optional

from prometheus_client import Gauge

from .api_auth import ApiAuth
from .config import CONFIG

# [DAAS] Métrique abonnements actifs
ACTIVE_SUBSCRIPTIONS_TOTAL = Gauge("active_subscriptions_total", "Abonnements actifs", ["tier"])


class BillingService:
    """Service billing avec webhooks Stripe simulés."""

    def __init__(self, api_auth: Optional[ApiAuth] = None):
        self.api_auth = api_auth or ApiAuth()
        self.db_path = CONFIG.billing.api_keys_db

    def _init_db(self) -> None:
        """Initialise la base de données billing."""
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                api_key_id INTEGER,
                stripe_customer_id TEXT,
                stripe_subscription_id TEXT,
                tier TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """
        )
        conn.commit()
        conn.close()

    def handle_stripe_webhook(self, event_type: str, data: Dict) -> Optional[str]:
        """
        Traite un webhook Stripe.

        Args:
            event_type: Type d'événement Stripe (customer.subscription.created, etc.)
            data: Données de l'événement

        Returns:
            API key créée/mise à jour ou None
        """
        if event_type == "customer.subscription.created":
            return self._handle_subscription_created(data)
        elif event_type == "customer.subscription.updated":
            return self._handle_subscription_updated(data)
        elif event_type == "customer.subscription.deleted":
            return self._handle_subscription_deleted(data)
        return None

    def _handle_subscription_created(self, data: Dict) -> Optional[str]:
        """Traite création subscription Stripe."""
        customer_id = data.get("customer")
        subscription_id = data.get("id")
        tier = self._extract_tier_from_subscription(data)

        # Créer API key
        api_key, key_hash = self.api_auth.create_key(tier=tier)

        # Enregistrer subscription
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            INSERT INTO subscriptions (api_key_id, stripe_customer_id, stripe_subscription_id, tier, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'active', ?, ?)
        """,
            (key_hash, customer_id, subscription_id, tier, time.time(), time.time()),
        )
        conn.commit()
        conn.close()

        # [DAAS] Mettre à jour métrique abonnements actifs
        self._update_active_subscriptions_metric()

        return api_key

    def _handle_subscription_updated(self, data: Dict) -> Optional[str]:
        """Traite mise à jour subscription Stripe."""
        subscription_id = data.get("id")
        tier = self._extract_tier_from_subscription(data)
        status = data.get("status", "active")

        # Trouver API key associée
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            """
            SELECT api_key_id FROM subscriptions
            WHERE stripe_subscription_id = ?
        """,
            (subscription_id,),
        )

        row = cursor.fetchone()
        if not row:
            conn.close()
            return None

        api_key_id = row[0]

        # Mettre à jour tier
        self.api_auth.update_tier(api_key_id, tier)

        # Mettre à jour subscription
        conn.execute(
            """
            UPDATE subscriptions
            SET tier = ?, status = ?, updated_at = ?
            WHERE stripe_subscription_id = ?
        """,
            (tier, status, time.time(), subscription_id),
        )
        conn.commit()
        conn.close()

        # [DAAS] Mettre à jour métrique abonnements actifs
        self._update_active_subscriptions_metric()

        return api_key_id

    def _handle_subscription_deleted(self, data: Dict) -> Optional[str]:
        """Traite suppression subscription Stripe."""
        subscription_id = data.get("id")

        # Trouver API key associée
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            """
            SELECT api_key_id FROM subscriptions
            WHERE stripe_subscription_id = ?
        """,
            (subscription_id,),
        )

        row = cursor.fetchone()
        if not row:
            conn.close()
            return None

        api_key_id = row[0]

        # Désactiver API key
        self.api_auth.deactivate_key(api_key_id)

        # Mettre à jour subscription
        conn.execute(
            """
            UPDATE subscriptions
            SET status = 'cancelled', updated_at = ?
            WHERE stripe_subscription_id = ?
        """,
            (time.time(), subscription_id),
        )
        conn.commit()
        conn.close()

        # [DAAS] Mettre à jour métrique abonnements actifs
        self._update_active_subscriptions_metric()

        return api_key_id

    def _update_active_subscriptions_metric(self) -> None:
        """Met à jour la métrique active_subscriptions_total."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            """
            SELECT tier, COUNT(*) as count
            FROM subscriptions
            WHERE status = 'active'
            GROUP BY tier
        """
        )

        # Reset toutes les métriques
        for tier in ["free", "pro", "elite"]:
            ACTIVE_SUBSCRIPTIONS_TOTAL.labels(tier=tier).set(0)

        # Mettre à jour avec les valeurs réelles
        for row in cursor.fetchall():
            tier, count = row
            ACTIVE_SUBSCRIPTIONS_TOTAL.labels(tier=tier).set(count)

        conn.close()

    def _extract_tier_from_subscription(self, data: Dict) -> str:
        """Extrait le tier depuis les données subscription."""
        # MVP: mapping simple depuis price_id
        price_id = data.get("items", {}).get("data", [{}])[0].get("price", {}).get("id", "")

        # Mapping price_id → tier (à configurer selon Stripe)
        tier_mapping = {
            "price_free": "free",
            "price_pro": "pro",
            "price_elite": "elite",
        }

        # Par défaut, extraire depuis metadata
        metadata = data.get("metadata", {})
        tier = metadata.get("tier", "free")

        return tier_mapping.get(price_id, tier)

    def fake_checkout(self, tier: str, email: str) -> Dict:
        """
        Simule un checkout (MVP).

        Args:
            tier: Tier souhaité (free, pro, elite)
            email: Email utilisateur

        Returns:
            Dict avec api_key et subscription_id
        """
        # Créer API key directement (sans Stripe)
        api_key, key_hash = self.api_auth.create_key(tier=tier)

        # Créer subscription fictive
        subscription_id = f"fake_sub_{int(time.time())}"

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            INSERT INTO subscriptions (api_key_id, stripe_customer_id, stripe_subscription_id, tier, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'active', ?, ?)
        """,
            (key_hash, email, subscription_id, tier, time.time(), time.time()),
        )
        conn.commit()
        conn.close()

        # [DAAS] Mettre à jour métrique abonnements actifs
        self._update_active_subscriptions_metric()

        return {
            "api_key": api_key,
            "subscription_id": subscription_id,
            "tier": tier,
            "status": "active",
        }
