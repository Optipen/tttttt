"""Tests alertes différenciées par tier."""


from src.config import CONFIG


def test_dry_run_enforcement():
    """Test que DRY_RUN=True par défaut."""
    assert CONFIG.alerting.dry_run is True


def test_copy_trader_disabled_by_default():
    """Test que COPY_TRADER_ENABLED=False par défaut."""
    assert CONFIG.copy_trader_enabled is False


def test_daas_mode_enabled():
    """Test que DAAS_MODE=True par défaut."""
    assert CONFIG.daas_mode is True


def test_include_paywall_prompt_enabled():
    """Test que INCLUDE_PAYWALL_PROMPT=True par défaut."""
    assert CONFIG.alerting.include_paywall_prompt is True
