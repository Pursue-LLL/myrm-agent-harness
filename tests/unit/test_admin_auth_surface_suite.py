"""Unit test suite for Admin Authentication Surface management framework."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.admin_auth_surface import (
    MASKED_SECRET_PLACEHOLDER,
    AdminAuthSurfaceConfig,
    AdminAuthSurfaceManager,
    AdminAuthSurfaceValidator,
    LoginMethodSettings,
    OAuthConnectionConfig,
    OAuthProviderType,
)


def test_default_config_validity() -> None:
    manager = AdminAuthSurfaceManager()
    cfg = manager.get_config()
    assert cfg.login_methods.password_enabled is True
    assert cfg.login_methods.email_code_enabled is False

    validation = AdminAuthSurfaceValidator.validate(cfg)
    assert validation.is_valid is True
    assert validation.active_login_method_count == 1
    assert len(validation.errors) == 0


def test_deadlock_condition_triggered() -> None:
    manager = AdminAuthSurfaceManager()

    # All login methods disabled
    deadlock_config = AdminAuthSurfaceConfig(
        login_methods=LoginMethodSettings(
            password_enabled=False,
            email_code_enabled=False,
        ),
        oauth_connections=[],
    )

    validation = AdminAuthSurfaceValidator.validate(deadlock_config)
    assert validation.is_valid is False
    assert validation.active_login_method_count == 0
    assert any("Deadlock condition" in e for e in validation.errors)

    with pytest.raises(ValueError, match="Deadlock condition"):
        manager.update_config(deadlock_config)


def test_email_code_auto_registration_prerequisite() -> None:
    # Inconsistent: auto-registration enabled while email login disabled
    inconsistent_config = AdminAuthSurfaceConfig(
        login_methods=LoginMethodSettings(
            password_enabled=True,
            email_code_enabled=False,
            email_code_auto_registration_enabled=True,
        ),
    )

    validation = AdminAuthSurfaceValidator.validate(inconsistent_config)
    assert validation.is_valid is False
    assert any("Inconsistent settings" in e for e in validation.errors)


def test_oauth_connection_validation_and_masking() -> None:
    invalid_oauth = [
        OAuthConnectionConfig(
            id="conn_gh",
            provider=OAuthProviderType.GITHUB,
            name="GitHub Login",
            client_id="",  # missing client_id
            client_secret="secret_12345678",
            authorize_url="https://github.com/login/oauth/authorize",
            token_url="https://github.com/login/oauth/access_token",
            enabled=True,
        )
    ]
    cfg = AdminAuthSurfaceConfig(oauth_connections=invalid_oauth)

    val = AdminAuthSurfaceValidator.validate(cfg)
    assert val.is_valid is False
    assert any("missing required client_id" in e for e in val.errors)

    # Test mask_secret
    masked = AdminAuthSurfaceValidator.mask_secret("secret_12345678")
    assert masked == "se****78"
    assert AdminAuthSurfaceValidator.mask_secret("") == ""
    assert AdminAuthSurfaceValidator.mask_secret("123") == "****"


def test_pure_oauth_mode_and_secret_preservation() -> None:
    initial_oauth = [
        OAuthConnectionConfig(
            id="conn_google",
            provider=OAuthProviderType.GOOGLE,
            name="Google Login",
            client_id="google_client_id",
            client_secret="super_secret_google_key_999",
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            enabled=True,
        )
    ]
    manager = AdminAuthSurfaceManager(
        initial_config=AdminAuthSurfaceConfig(
            login_methods=LoginMethodSettings(password_enabled=True),
            oauth_connections=initial_oauth,
        )
    )

    # 1. Masked view
    masked_cfg = manager.get_masked_config()
    assert masked_cfg.oauth_connections[0].client_secret == "su****99"

    # 2. Update with placeholder
    update_candidate = AdminAuthSurfaceConfig(
        login_methods=LoginMethodSettings(
            password_enabled=False,
            email_code_enabled=False,
        ),
        oauth_connections=[
            OAuthConnectionConfig(
                id="conn_google",
                provider=OAuthProviderType.GOOGLE,
                name="Google Login Updated",
                client_id="google_client_id",
                client_secret=MASKED_SECRET_PLACEHOLDER,
                authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
                token_url="https://oauth2.googleapis.com/token",
                enabled=True,
            )
        ],
    )

    updated_cfg, val = manager.update_config(update_candidate)
    assert val.is_valid is True
    assert updated_cfg.login_methods.password_enabled is False
    assert (
        updated_cfg.oauth_connections[0].client_secret == "super_secret_google_key_999"
    )
    assert any("relies exclusively on third-party OAuth" in w for w in val.warnings)
