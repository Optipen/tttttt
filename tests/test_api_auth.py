"""Tests module api_auth."""

import os
import tempfile
from pathlib import Path

import pytest

from src.api_auth import ApiAuth


@pytest.fixture
def temp_db():
    """Crée une base de données temporaire."""
    fd, path = tempfile.mkstemp(suffix=".db")
    yield Path(path)
    os.close(fd)
    if Path(path).exists():
        Path(path).unlink()


def test_api_auth_create_key(temp_db):
    """Test création API key."""
    auth = ApiAuth(db_path=temp_db)
    api_key, key_hash = auth.create_key(tier="pro")

    assert api_key.startswith("daas_")
    assert len(api_key) >= 48
    assert key_hash == auth.hash_key(api_key)


def test_api_auth_validate_key(temp_db):
    """Test validation API key."""
    auth = ApiAuth(db_path=temp_db)
    api_key, key_hash = auth.create_key(tier="pro")

    result = auth.validate_key(api_key)
    assert result is not None
    tier, is_active = result
    assert tier == "pro"
    assert is_active is True


def test_api_auth_validate_key_invalid(temp_db):
    """Test validation API key invalide."""
    auth = ApiAuth(db_path=temp_db)
    result = auth.validate_key("invalid_key")
    assert result is None


def test_api_auth_deactivate_key(temp_db):
    """Test désactivation API key."""
    auth = ApiAuth(db_path=temp_db)
    api_key, key_hash = auth.create_key(tier="pro")

    # Désactiver
    updated = auth.deactivate_key(api_key)
    assert updated is True

    # Vérifier désactivé
    result = auth.validate_key(api_key)
    assert result is None


def test_api_auth_update_tier(temp_db):
    """Test mise à jour tier."""
    auth = ApiAuth(db_path=temp_db)
    api_key, key_hash = auth.create_key(tier="free")

    # Mettre à jour tier
    updated = auth.update_tier(api_key, "pro")
    assert updated is True

    # Vérifier tier mis à jour
    result = auth.validate_key(api_key)
    assert result is not None
    tier, is_active = result
    assert tier == "pro"
