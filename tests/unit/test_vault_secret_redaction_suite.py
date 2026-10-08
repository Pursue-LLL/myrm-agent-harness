"""Unit tests for always-on vault secret dynamic redaction suite.

Verifies:
- Longest-first secret matching to prevent prefix shadowing
- Min-length threshold exclusion preventing false positives on short words
- Tool returns (nested dict/list) and user inbound messages scrubbing
- Streaming sliding-window boundary holdback and flush behavior
- CredentialVault synchronization and ambient environment collection
- ANSI escape stripping and match statistics tracking
"""

from __future__ import annotations

from myrm_agent_harness.core.security.credential_vault import CredentialVault
from myrm_agent_harness.core.security.vault_secret_redaction import (
    AlwaysOnVaultSecretRedactor,
    SecretSourceType,
    VaultSecretRedactionConfig,
    VaultSecretRedactionFacade,
)


def test_basic_redaction_and_longest_first_precedence() -> None:
    redactor = AlwaysOnVaultSecretRedactor()
    # Register overlapping secrets: short and long
    assert redactor.register_secret("KEY_SHORT", "super_secret_token")
    assert redactor.register_secret(
        "KEY_LONG", "super_secret_token_extended_edition"
    )

    text = "Found token: super_secret_token_extended_edition and also super_secret_token in stdout."
    result = redactor.redact_text(text)

    # Longer token must be replaced first, so no partial broken tokens exist
    assert "super_secret_token_extended_edition" not in result.clean_content
    assert "super_secret_token" not in result.clean_content
    assert "KEY_LONG=<REDACTED>" in result.clean_content
    assert "KEY_SHORT=<REDACTED>" in result.clean_content
    assert result.redacted_count == 2
    assert "KEY_LONG" in result.matched_secrets
    assert "KEY_SHORT" in result.matched_secrets


def test_min_length_threshold_prevents_false_positives() -> None:
    redactor = AlwaysOnVaultSecretRedactor(
        config=VaultSecretRedactionConfig(min_secret_length=8)
    )
    # Secrets shorter than 8 characters must be rejected
    assert not redactor.register_secret("DEV_ENV", "dev")
    assert not redactor.register_secret("SHORT_PIN", "12345")
    # Valid length must be accepted
    assert redactor.register_secret("VALID_TOKEN", "sk-proj-99887766")

    text = "In dev mode with 12345 pin, token is sk-proj-99887766."
    result = redactor.redact_text(text)
    assert "In dev mode with 12345 pin" in result.clean_content
    assert "sk-proj-99887766" not in result.clean_content
    assert "VALID_TOKEN=<REDACTED>" in result.clean_content


def test_ansi_escape_code_stripping() -> None:
    redactor = AlwaysOnVaultSecretRedactor()
    redactor.register_secret("SECRET_API", "my_super_secret_9988")

    # ANSI colored output in terminal
    ansi_text = "\x1b[31mError\x1b[0m with key: \x1b[32mmy_super_secret_9988\x1b[0m"
    result = redactor.redact_text(ansi_text)
    assert "\x1b[" not in result.clean_content
    assert "SECRET_API=<REDACTED>" in result.clean_content
    assert "my_super_secret_9988" not in result.clean_content


def test_tool_return_nested_data_scrubbing() -> None:
    redactor = AlwaysOnVaultSecretRedactor()
    redactor.register_secret("DB_PASS", "postgres_master_pw_42")
    redactor.register_secret("API_KEY", "claude_secret_token_123")

    payload = {
        "status": "success",
        "details": {
            "connection_string": "postgres://admin:postgres_master_pw_42@localhost:5432/db",
            "headers": ["Bearer claude_secret_token_123", "User-Agent: test"],
        },
        "count": 1,
    }

    cleaned_payload, res = redactor.redact_tool_return(payload)
    assert isinstance(cleaned_payload, dict)
    cleaned_dict = cleaned_payload["details"]
    assert isinstance(cleaned_dict, dict)
    assert "postgres_master_pw_42" not in cleaned_dict["connection_string"]
    assert "DB_PASS=<REDACTED>" in cleaned_dict["connection_string"]
    assert "claude_secret_token_123" not in cleaned_dict["headers"][0]
    assert "API_KEY=<REDACTED>" in cleaned_dict["headers"][0]
    assert res.redacted_count == 2


def test_inbound_user_message_scrubbing() -> None:
    redactor = AlwaysOnVaultSecretRedactor()
    redactor.register_secret("OPENAI_KEY", "sk-live-09876543210987654321")

    user_msg = "Please analyze this config: key=sk-live-09876543210987654321 and tell me if it works"
    cleaned_msg, res = redactor.redact_user_message(user_msg)
    assert "sk-live-09876543210987654321" not in str(cleaned_msg)
    assert "OPENAI_KEY=<REDACTED>" in str(cleaned_msg)
    assert res.redacted_count == 1


def test_streaming_sliding_window_holdback_and_flush() -> None:
    redactor = AlwaysOnVaultSecretRedactor()
    secret = "sk-ant-admin-99881122"
    redactor.register_secret("ANTHROPIC_KEY", secret)

    scrubber = redactor.create_stream_scrubber()

    # Split secret across two chunks:
    # chunk 1: "The secret is sk-ant-ad"
    # chunk 2: "min-99881122 done!"
    chunk1 = "The secret is sk-ant-ad"
    chunk2 = "min-99881122 done!"

    emitted1 = scrubber.push(chunk1)
    # The trailing partial "sk-ant-ad" should be held back
    assert secret not in emitted1
    assert "sk-ant-ad" not in emitted1
    assert emitted1 == "The secret is "
    assert scrubber.held_back_length > 0

    emitted2 = scrubber.push(chunk2)
    # Once chunk 2 completes the secret, it should be emitted scrubbed
    assert secret not in emitted2
    assert "ANTHROPIC_KEY=<REDACTED>" in emitted2
    assert "done!" in emitted2

    # Flush should be empty since holdback was resolved
    flushed = scrubber.flush()
    assert flushed == ""


def test_streaming_scrubber_partial_flush_when_stream_ends() -> None:
    redactor = AlwaysOnVaultSecretRedactor()
    secret = "super_long_secret_12345"
    redactor.register_secret("KEY", secret)

    scrubber = redactor.create_stream_scrubber()
    # Provide text that matches prefix but stream abruptly ends
    chunk = "Prefix text super_long_"
    emitted = scrubber.push(chunk)
    assert emitted == "Prefix text "
    assert scrubber.held_back_length == len("super_long_")

    flushed = scrubber.flush()
    # Flushed content is not the full secret, so it outputs without the secret mask
    assert flushed == "super_long_"


def test_credential_vault_synchronization_and_ambient_env() -> None:
    vault = CredentialVault()
    vault.add_credential(
        "github_main",
        password="ghp_super_secret_github_password_1234",
        totp_seed="JBSWY3DPEHPK3PXP",
    )
    vault.add_credential("short_one", password="123")  # Too short, skipped

    redactor = AlwaysOnVaultSecretRedactor()
    synced = redactor.sync_from_credential_vault(vault)
    assert synced == 2  # password and totp_seed for github_main

    # Ambient env collection
    test_env = {
        "OPENAI_API_KEY": "sk-proj-ambient-token-998811",
        "NON_SENSITIVE_VAR": "hello_world_variable",
    }
    collected = redactor.collect_ambient_env_secrets(test_env)
    assert collected == 1

    text = "Using gh: ghp_super_secret_github_password_1234 and JBSWY3DPEHPK3PXP with sk-proj-ambient-token-998811"
    res = redactor.redact_text(text)
    assert "ghp_super_secret_github_password_1234" not in res.clean_content
    assert "JBSWY3DPEHPK3PXP" not in res.clean_content
    assert "sk-proj-ambient-token-998811" not in res.clean_content
    assert res.redacted_count == 3


def test_facade_lifecycle_and_statistics() -> None:
    facade = VaultSecretRedactionFacade()
    facade.clear()
    assert facade.register_secret(
        "MY_SECRET",
        "secret_token_number_one",
        source=SecretSourceType.DYNAMIC_CAPTURED,
    )
    assert "MY_SECRET" in facade.list_secret_names()

    res = facade.redact_text(
        "Output: secret_token_number_one and secret_token_number_one"
    )
    assert res.redacted_count == 2
    stats = facade.get_stats()
    assert stats["MY_SECRET"] == 2

    assert facade.unregister_secret("MY_SECRET")
    assert not facade.unregister_secret("NON_EXISTENT")
    assert "MY_SECRET" not in facade.list_secret_names()

    res_after = facade.redact_text("Output: secret_token_number_one")
    assert res_after.redacted_count == 0
    assert "secret_token_number_one" in res_after.clean_content
