"""Unit tests for Desktop OAuth Browser Flow & RFC 8628 Device Code Grant Engine Suite."""

from __future__ import annotations

import time

import pytest

from myrm_agent_harness.core.security.desktop_oauth_device import (
    DeviceAuthStatus,
    DeviceCodeEngine,
    OAuthPkceChallenge,
    OAuthTokenGrant,
    SilentTokenRotator,
    TokenStatus,
    build_authorization_url,
    compute_code_challenge,
    generate_code_verifier,
    generate_pkce_challenge,
    verify_code_challenge,
)


def test_pkce_generation_and_verification() -> None:
    # 1. Verifier constraints
    verifier = generate_code_verifier(64)
    assert len(verifier) == 64

    with pytest.raises(ValueError, match="length must be between 43 and 128"):
        generate_code_verifier(30)

    # 2. S256 Challenge
    challenge = compute_code_challenge(verifier)
    assert len(challenge) > 0
    assert "=" not in challenge  # base64url unpadded

    # 3. Verification
    assert verify_code_challenge(verifier, challenge) is True
    assert verify_code_challenge(verifier + "extra", challenge) is False

    # 4. Complete challenge generator
    pkce = generate_pkce_challenge(state="test-state-123")
    assert pkce.state == "test-state-123"
    assert pkce.code_challenge_method == "S256"
    assert verify_code_challenge(pkce.code_verifier, pkce.code_challenge) is True


def test_build_authorization_url() -> None:
    challenge = OAuthPkceChallenge(
        code_verifier="mock-verifier-val",
        code_challenge="mock-challenge-val",
        code_challenge_method="S256",
        state="xyz987",
    )
    url = build_authorization_url(
        base_auth_url="https://github.com/login/oauth/authorize",
        client_id="myrm-desktop-client-id",
        redirect_uri="http://127.0.0.1:41920/callback",
        challenge=challenge,
        scopes=["read:user", "repo"],
    )

    assert url.startswith("https://github.com/login/oauth/authorize?")
    assert "response_type=code" in url
    assert "client_id=myrm-desktop-client-id" in url
    assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A41920%2Fcallback" in url
    assert "state=xyz987" in url
    assert "code_challenge=mock-challenge-val" in url
    assert "code_challenge_method=S256" in url
    assert "scope=read%3Auser+repo" in url


def test_device_code_engine_full_lifecycle() -> None:
    engine = DeviceCodeEngine()

    # 1. Initiate session
    session = engine.initiate_session(
        verification_uri="https://auth.myrm.dev/device",
        client_id="headless-cli-client",
        expires_in=300,
        interval=2,
    )

    assert len(session.device_code) > 20
    assert len(session.user_code) == 9  # XXXX-XXXX
    assert "-" in session.user_code
    assert session.verification_uri_complete == f"https://auth.myrm.dev/device?user_code={session.user_code}"
    assert session.status == DeviceAuthStatus.AUTHORIZATION_PENDING

    # 2. Polling before authorization (pending)
    status, token, _ = engine.poll_session(session.device_code, enforce_interval=False)
    assert status == DeviceAuthStatus.AUTHORIZATION_PENDING
    assert token is None

    # 3. Authorize via user code
    token_grant = OAuthTokenGrant(
        access_token="act_sec_live_9988",
        refresh_token="rft_sec_live_1122",
        expires_in=3600,
        created_at=time.time(),
    )
    success, auth_msg = engine.authorize_user_code(session.user_code.lower(), token_grant)
    assert success is True
    assert "successfully authorized" in auth_msg

    # 4. Polling after authorization (authorized)
    status_after, token_after, _ = engine.poll_session(session.device_code, enforce_interval=False)
    assert status_after == DeviceAuthStatus.AUTHORIZED
    assert token_after is not None
    assert token_after.access_token == "act_sec_live_9988"
    assert token_after.refresh_token == "rft_sec_live_1122"


def test_device_code_engine_deny_and_expiry() -> None:
    engine = DeviceCodeEngine()

    # 1. Deny flow
    session = engine.initiate_session(
        verification_uri="https://auth.myrm.dev/device",
        client_id="cli-deny",
        expires_in=10,
    )
    deny_ok, _ = engine.deny_user_code(session.user_code)
    assert deny_ok is True

    status, _, _ = engine.poll_session(session.device_code, enforce_interval=False)
    assert status == DeviceAuthStatus.ACCESS_DENIED

    # 2. Expiry flow
    expired_session = engine.initiate_session(
        verification_uri="https://auth.myrm.dev/device",
        client_id="cli-expired",
        expires_in=-1,  # instantly expired
    )
    # Attempting to authorize expired code
    dummy_grant = OAuthTokenGrant(access_token="tok", refresh_token=None)
    auth_ok, auth_err = engine.authorize_user_code(expired_session.user_code, dummy_grant)
    assert auth_ok is False
    assert "expired" in auth_err.lower()

    status_exp, _, _ = engine.poll_session(expired_session.device_code, enforce_interval=False)
    assert status_exp == DeviceAuthStatus.EXPIRED_TOKEN


def test_silent_token_rotator_and_refresh() -> None:
    rotator = SilentTokenRotator()
    provider = "github"

    now = time.time()
    # 1. Active token
    active_grant = OAuthTokenGrant(
        access_token="act_111",
        refresh_token="rft_111",
        expires_in=3600,
        created_at=now,
    )
    rotator.register_grant(provider, active_grant)

    assert rotator.check_status(provider, current_time=now) == TokenStatus.ACTIVE
    res_active = rotator.ensure_active_token(provider, current_time=now)
    assert res_active.status == TokenStatus.ACTIVE
    assert res_active.rotated is False
    assert res_active.token is not None
    assert res_active.token.access_token == "act_111"

    # 2. Expiring soon token (triggers silent rotation)
    expiring_grant = OAuthTokenGrant(
        access_token="act_222",
        refresh_token="rft_222",
        expires_in=50,  # 50s left < 60s buffer
        created_at=now,
    )
    rotator.register_grant(provider, expiring_grant)
    assert rotator.check_status(provider, buffer_seconds=60.0, current_time=now) == TokenStatus.EXPIRING_SOON

    def dummy_refresher(prov: str, rft: str) -> OAuthTokenGrant:
        assert prov == "github"
        assert rft == "rft_222"
        return OAuthTokenGrant(
            access_token="act_new_333",
            refresh_token="rft_new_333",
            expires_in=3600,
            created_at=now,
        )

    res_rot = rotator.ensure_active_token(
        provider,
        refresh_handler=dummy_refresher,
        buffer_seconds=60.0,
        current_time=now,
    )
    assert res_rot.status == TokenStatus.ACTIVE
    assert res_rot.rotated is True
    assert res_rot.token is not None
    assert res_rot.token.access_token == "act_new_333"

    # 3. Rotated grant persisted in rotator
    stored = rotator.get_grant(provider)
    assert stored is not None
    assert stored.access_token == "act_new_333"
