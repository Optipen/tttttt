"""Tests module billing."""


import pytest

from src.api_auth import ApiAuth
from src.billing import BillingService


@pytest.fixture
def api_auth():
    """Crée une instance ApiAuth."""
    return ApiAuth()


@pytest.fixture
def billing_service(api_auth):
    """Crée une instance BillingService."""
    return BillingService(api_auth=api_auth)


def test_fake_checkout(billing_service):
    """Test fake checkout."""
    result = billing_service.fake_checkout(tier="pro", email="test@example.com")

    assert "api_key" in result
    assert "subscription_id" in result
    assert result["tier"] == "pro"
    assert result["status"] == "active"
    assert result["api_key"].startswith("daas_")


def test_stripe_webhook_subscription_created(billing_service):
    """Test webhook Stripe subscription created."""
    data = {
        "customer": "cus_test123",
        "id": "sub_test123",
        "metadata": {"tier": "pro"},
    }

    api_key = billing_service.handle_stripe_webhook("customer.subscription.created", data)

    assert api_key is not None
    assert api_key.startswith("daas_")


def test_stripe_webhook_subscription_updated(billing_service):
    """Test webhook Stripe subscription updated."""
    # Créer subscription d'abord
    data_created = {
        "customer": "cus_test123",
        "id": "sub_test123",
        "metadata": {"tier": "free"},
    }
    billing_service.handle_stripe_webhook("customer.subscription.created", data_created)

    # Mettre à jour tier
    data_updated = {
        "id": "sub_test123",
        "status": "active",
        "metadata": {"tier": "pro"},
    }
    result = billing_service.handle_stripe_webhook("customer.subscription.updated", data_updated)

    assert result is not None


def test_stripe_webhook_subscription_deleted(billing_service):
    """Test webhook Stripe subscription deleted."""
    # Créer subscription d'abord
    data_created = {
        "customer": "cus_test123",
        "id": "sub_test123",
        "metadata": {"tier": "pro"},
    }
    api_key = billing_service.handle_stripe_webhook("customer.subscription.created", data_created)

    # Supprimer subscription
    data_deleted = {
        "id": "sub_test123",
    }
    result = billing_service.handle_stripe_webhook("customer.subscription.deleted", data_deleted)

    assert result is not None

    # Vérifier API key désactivée
    auth = billing_service.api_auth
    validation = auth.validate_key(api_key)
    assert validation is None  # Désactivée
