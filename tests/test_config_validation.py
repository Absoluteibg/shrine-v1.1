import pytest

from app.core.config import _DEV_ONLY_ADMIN_PASSWORD_HASH, Settings, validate_production_config


def _prod_settings(**overrides) -> Settings:
    base = dict(
        ENV="production",
        SECRET_KEY="a-real-randomly-generated-secret",
        ADMIN_PASSWORD_HASH="$2b$12$notTheDevDefaultHashValueXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
        DEBUG=False,
    )
    base.update(overrides)
    return Settings(**base)


def test_safe_production_settings_pass():
    validate_production_config(_prod_settings())  # should not raise


def test_development_settings_are_never_checked():
    # Every dev default left in place — fine, because ENV isn't "production".
    validate_production_config(Settings())


def test_default_secret_key_in_production_raises():
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        validate_production_config(_prod_settings(SECRET_KEY="dev-only-insecure-secret-change-me"))


def test_default_admin_password_in_production_raises():
    with pytest.raises(RuntimeError, match="ADMIN_PASSWORD_HASH"):
        validate_production_config(_prod_settings(ADMIN_PASSWORD_HASH=_DEV_ONLY_ADMIN_PASSWORD_HASH))


def test_debug_true_in_production_raises():
    with pytest.raises(RuntimeError, match="DEBUG"):
        validate_production_config(_prod_settings(DEBUG=True))


def test_all_problems_reported_together_not_just_the_first():
    """
    Every dev default left in place under ENV=production should report
    all three problems in one error, not just whichever was checked
    first — so fixing one doesn't just reveal the next one at a time.
    """
    with pytest.raises(RuntimeError) as exc_info:
        validate_production_config(Settings(ENV="production"))
    message = str(exc_info.value)
    assert "SECRET_KEY" in message
    assert "ADMIN_PASSWORD_HASH" in message
    assert "DEBUG" in message
