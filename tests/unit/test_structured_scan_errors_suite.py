"""Unit tests for Structured JSON Scan Failure Errors Suite."""

from __future__ import annotations

import json

from myrm_agent_harness.core.security.structured_scan_errors import (
    RemediationAction,
    ScanErrorCode,
    ScanFailureEmitter,
)


def test_classify_failure_heuristics() -> None:
    # 1. OOM
    code, _, action, steps, retryable, backoff = ScanFailureEmitter.classify_failure(
        exit_code=137, stderr="Killed process 1234 (semgrep-core) out of memory"
    )
    assert code == ScanErrorCode.OUT_OF_MEMORY
    assert action == RemediationAction.RETRY
    assert retryable is True
    assert backoff == 10.0
    assert len(steps) >= 2

    # 2. Rate limit
    code_rl, _, action_rl, _, retry_rl, backoff_rl = ScanFailureEmitter.classify_failure(
        exit_code=1, stderr="HTTP 429 Too Many Requests: Rate limit exceeded for vulnerability database"
    )
    assert code_rl == ScanErrorCode.RATE_LIMITED
    assert action_rl == RemediationAction.RETRY
    assert retry_rl is True
    assert backoff_rl == 60.0

    # 3. Authentication failure
    code_auth, _, action_auth, _, retry_auth, _ = ScanFailureEmitter.classify_failure(
        exit_code=2, stderr="Error 401 Unauthorized: Invalid API token provided for scanner"
    )
    assert code_auth == ScanErrorCode.AUTHENTICATION_FAILED
    assert action_auth == RemediationAction.BLOCK_PIPELINE
    assert retry_auth is False

    # 4. Timeout
    code_to, _, action_to, _, retry_to, _ = ScanFailureEmitter.classify_failure(
        exit_code=124, stderr="Command timed out after 300 seconds"
    )
    assert code_to == ScanErrorCode.TIMEOUT
    assert action_to == RemediationAction.RETRY
    assert retry_to is True

    # 5. Engine crash
    code_crash, _, action_crash, _, _, _ = ScanFailureEmitter.classify_failure(
        exit_code=127, stderr="sh: osv-scanner: command not found"
    )
    assert code_crash == ScanErrorCode.ENGINE_CRASH
    assert action_crash == RemediationAction.BLOCK_PIPELINE


def test_emit_failure_and_json_serialization() -> None:
    emitter = ScanFailureEmitter()

    envelope = emitter.emit_failure(
        scan_id="scan-xyz-101",
        target_path_or_url="/workspace/repo",
        scanner_engine="trivy",
        exit_code=1,
        stderr="Failed to parse ruleset: syntax error on line 42",
        metadata={"git_branch": "main", "commit": "a1b2c3d"},
    )

    assert envelope.error_code == ScanErrorCode.RULESET_SYNTAX_ERROR
    assert envelope.remediation.suggested_action == RemediationAction.BLOCK_PIPELINE
    assert envelope.context.scan_id == "scan-xyz-101"
    assert envelope.context.metadata["git_branch"] == "main"

    # Test serialization
    json_str = envelope.to_json()
    assert isinstance(json_str, str)
    parsed = json.loads(json_str)

    assert parsed["error_code"] == "SCAN_RULESET_SYNTAX_ERROR"
    assert parsed["remediation"]["suggested_action"] == "BLOCK_PIPELINE"
    assert parsed["context"]["scanner_engine"] == "trivy"


def test_emit_from_exception() -> None:
    emitter = ScanFailureEmitter()

    exc = ConnectionRefusedError("Connection refused by vulnerability server at 10.0.0.1:443")
    envelope = emitter.emit_from_exception(
        scan_id="scan-exc-999",
        target_path_or_url="https://registry.internal/vulns",
        scanner_engine="osv-scanner",
        exc=exc,
    )

    assert envelope.error_code == ScanErrorCode.TARGET_UNREACHABLE
    assert envelope.remediation.suggested_action == RemediationAction.RETRY
    assert "ConnectionRefusedError" in (envelope.context.raw_stderr_snippet or "")
