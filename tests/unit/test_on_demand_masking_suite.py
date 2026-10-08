"""Unit tests for OnDemandCredentialMasking suite."""

import base64
import urllib.parse
import pytest

from myrm_agent_harness.core.security.on_demand_masking import (
    CredentialConflictError,
    CredentialField,
    MultiEncodingSecretMasker,
    OnDemandCredentialResolver,
)


def test_multi_encoding_masking_variants() -> None:
    secret = "ghp_secureSecretToken123"
    env = {"GITHUB_TOKEN": secret}

    masker = MultiEncodingSecretMasker(env)

    # 1. Raw match
    raw_text = f"Connecting using {secret}..."
    masked_raw, labels = masker.mask(raw_text)
    assert masked_raw == "Connecting using <redacted:GITHUB_TOKEN>..."
    assert "GITHUB_TOKEN" in labels

    # 2. URL-encoded match
    encoded_secret = urllib.parse.quote(secret)
    url_text = f"https://api.github.com?token={encoded_secret}"
    masked_url, _ = masker.mask(url_text)
    assert f"<redacted:GITHUB_TOKEN>" in masked_url

    # 3. Base64 match
    b64_secret = base64.b64encode(secret.encode("utf-8")).decode("utf-8").rstrip("=")
    b64_text = f"Basic {b64_secret}"
    masked_b64, _ = masker.mask(b64_text)
    assert f"<redacted:GITHUB_TOKEN>" in masked_b64

    # 4. Hex match (both lower and upper)
    hex_secret = secret.encode("utf-8").hex()
    hex_text = f"Hash trace: {hex_secret}"
    masked_hex, _ = masker.mask(hex_text)
    assert f"<redacted:GITHUB_TOKEN>" in masked_hex

    hex_upper_text = f"UPPER_HASH: {hex_secret.upper()}"
    masked_hex_upper, _ = masker.mask(hex_upper_text)
    assert f"<redacted:GITHUB_TOKEN>" in masked_hex_upper


def test_longest_first_ordering() -> None:
    env = {
        "SHORT_KEY": "secret_abc",
        "LONG_KEY": "secret_abc_longer_suffix",
    }
    masker = MultiEncodingSecretMasker(env)

    text = "Logging in with secret_abc_longer_suffix now."
    masked, labels = masker.mask(text)

    # Should match LONG_KEY first and not corrupt it into <redacted:SHORT_KEY>_longer_suffix
    assert masked == "Logging in with <redacted:LONG_KEY> now."
    assert labels == ["LONG_KEY"]


def test_non_secret_and_short_keys_ignored() -> None:
    env = {
        "AWS_REGION": "us-east-1",  # non-secret key
        "TINY_PASS": "12345",  # shorter than MIN_MASKABLE_LENGTH (8)
    }
    masker = MultiEncodingSecretMasker(env)
    assert masker.variant_count == 0

    text = "Region is us-east-1, pass is 12345"
    masked, labels = masker.mask(text)
    assert masked == text
    assert len(labels) == 0


def test_on_demand_resolver_conflict_and_isolation() -> None:
    resolver = OnDemandCredentialResolver()

    resolver.register_provider(
        "cred-1",
        lambda: [
            CredentialField(key="DB_HOST", value="postgres.prod", is_secret=False),
            CredentialField(key="DB_PASS", value="secretPass9988", is_secret=True),
        ],
    )
    resolver.register_provider(
        "cred-2",
        lambda: [
            CredentialField(key="API_KEY", value="apiKey_abcdef123", is_secret=True),
        ],
    )
    resolver.register_provider(
        "cred-conflict",
        lambda: [
            CredentialField(key="DB_HOST", value="mysql.other", is_secret=False),
        ],
    )

    # 1. Resolve single requested credential - unrequested cred-2 is absent
    env1, masker1 = resolver.resolve_requested(["cred-1"])
    assert "DB_HOST" in env1
    assert "DB_PASS" in env1
    assert "API_KEY" not in env1  # Absent!

    masked, _ = masker1.mask("Connecting with secretPass9988 to db")
    assert masked == "Connecting with <redacted:DB_PASS> to db"

    # 2. Conflict detection
    with pytest.raises(CredentialConflictError) as exc_info:
        resolver.resolve_requested(["cred-1", "cred-conflict"])
    assert "conflicting environment key: DB_HOST" in str(exc_info.value)
