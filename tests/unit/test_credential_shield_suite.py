"""Unit tests for Credential Stdin Pipelining & Process Leakage Shield Suite (Item 41).

[INPUT]
- CommandLineCredentialInspector, EphemeralCredentialZeroizer, and CredentialStdinPipeliningEngine.

[OUTPUT]
- Verified test outcomes ensuring credentials in argv are detected, transformed into stdin pipelines,
  and in-memory buffers are zeroized.

[POS]
- Harness core security test suite.
"""

from __future__ import annotations

import io

from myrm_agent_harness.core.security.credential_shield import (
    CommandLineCredentialInspector,
    CredentialStdinPipeliningEngine,
    CredentialTransportMode,
    EphemeralCredentialZeroizer,
    LeakageRiskLevel,
)


def test_command_line_credential_inspector_detection() -> None:
    # 1. Clean command
    res_clean = CommandLineCredentialInspector.inspect("curl -sS https://api.github.com/repos")
    assert res_clean.is_safe_for_process_table is True
    assert res_clean.risk_level == LeakageRiskLevel.SAFE
    assert len(res_clean.detected_leaks) == 0

    # 2. Curl with Authorization Bearer
    bad_curl = "curl -sS -H 'Authorization: Bearer ghp_secret123456789' https://api.github.com/user"
    res_curl = CommandLineCredentialInspector.inspect(bad_curl)
    assert res_curl.is_safe_for_process_table is False
    assert res_curl.risk_level == LeakageRiskLevel.HIGH_RISK_PROCESS_TABLE_EXPOSURE
    assert "HTTP_AUTH_HEADER_DETECTED" in res_curl.detected_leaks

    # 3. CLI --token flag
    bad_cli = "my-cli deploy --token secret_token_value_9999 --env prod"
    res_cli = CommandLineCredentialInspector.inspect(bad_cli)
    assert res_cli.is_safe_for_process_table is False
    assert "CLI_API_KEY_FLAG_DETECTED" in res_cli.detected_leaks

    # 4. Embedded URL credential
    bad_git = "git clone https://user:super_secret_pwd@github.com/org/repo.git"
    res_git = CommandLineCredentialInspector.inspect(bad_git)
    assert res_git.is_safe_for_process_table is False
    assert "URL_EMBEDDED_CREDENTIAL_DETECTED" in res_git.detected_leaks

    # 5. Sanitized display
    display_str = CommandLineCredentialInspector.sanitize_display(bad_curl)
    assert "ghp_secret123456789" not in display_str
    assert "[REDACTED_CREDENTIAL]" in display_str


def test_ephemeral_credential_zeroizer() -> None:
    # 1. Direct wipe_buffer
    buf = bytearray(b"super_secret_api_key")
    EphemeralCredentialZeroizer.wipe_buffer(buf)
    assert all(b == 0 for b in buf)

    # 2. Pipe and wipe stream
    dest_stream = io.BytesIO()
    secret_str = "ghp_transient_secret_998877"
    bytes_written = EphemeralCredentialZeroizer.pipe_and_wipe(secret_str, dest_stream)
    assert bytes_written == len(secret_str.encode("utf-8"))
    assert dest_stream.getvalue().decode("utf-8") == secret_str


def test_credential_stdin_pipelining_engine_curl_rewriting() -> None:
    raw_curl = (
        "curl -sS -H 'Authorization: Bearer ghp_super_secure_token' "
        "-H 'X-Api-Key: api_key_123' https://api.github.com/user"
    )

    spec = CredentialStdinPipeliningEngine.pipeline_command(raw_curl)

    # Transport mode should be STDIN_CONFIG_STREAM
    assert spec.transport_mode == CredentialTransportMode.STDIN_CONFIG_STREAM

    # Sanitized argv must NOT contain the plain-text secret!
    argv_str = " ".join(spec.sanitized_argv)
    assert "ghp_super_secure_token" not in argv_str
    assert "api_key_123" not in argv_str
    assert "-K" in spec.sanitized_argv
    assert "-" in spec.sanitized_argv

    # Stdin payload must contain the configuration instructions
    stdin_str = spec.stdin_payload.decode("utf-8")
    assert 'header = "Authorization: Bearer ghp_super_secure_token"' in stdin_str
    assert 'header = "X-Api-Key: api_key_123"' in stdin_str

    # Display command
    assert "[CREDENTIAL_VIA_STDIN_PIPELINE]" in spec.sanitized_display_cmd


def test_credential_stdin_pipelining_safe_command() -> None:
    safe_cmd = "echo 'all good'"
    spec = CredentialStdinPipeliningEngine.pipeline_command(safe_cmd)
    assert spec.transport_mode == CredentialTransportMode.STDIN_PIPELINE
    assert spec.stdin_payload == b""
    assert spec.sanitized_argv == ("echo", "all good")
