"""[INPUT] Harness failure_facts submodule exports.
[OUTPUT] Unit tests verifying single-line diagnostic headers, credential scrubbing, 4096-byte bounds, error classification, and self-healing recommendations.
[POS] Unit tests for Subagent Bounded Structured Failure Facts & Privacy-Preserving Diagnostic Protocol.
"""

from __future__ import annotations

from myrm_agent_harness.agent.sub_agents.failure_facts import (
    MAX_DIAGNOSTIC_FACTS_BYTES,
    RemediationAction,
    SafeFailureSanitizer,
    StructuredFailureFact,
    SubagentDiagnosticProtocol,
    SubagentFailureCategory,
    SubagentFailureStage,
)


def test_single_line_diagnostic_header_formatting() -> None:
    # 1. Full parameters
    header = SubagentDiagnosticProtocol.format_diagnostic_header(
        product="codex-worker-01",
        stage=SubagentFailureStage.TURN,
        category=SubagentFailureCategory.CONTEXT_WINDOW_EXCEEDED,
        http_status=400,
        exit_code=1,
        signal="none",
    )
    assert header == (
        "Product subagent failure (product: codex-worker-01; "
        "stage: turn; "
        "category: contextWindowExceeded; "
        "HTTP status: 400; "
        "exit code: 1; "
        "signal: none)"
    )

    # 2. None / optional parameters format as 'none'
    header_none = SubagentDiagnosticProtocol.format_diagnostic_header(
        product="claude-scout",
        stage=SubagentFailureStage.QUERY_START,
        category=SubagentFailureCategory.RATE_LIMITED,
        http_status=429,
        exit_code=None,
        signal=None,
    )
    assert header_none == (
        "Product subagent failure (product: claude-scout; "
        "stage: query-start; "
        "category: rateLimited; "
        "HTTP status: 429; "
        "exit code: none; "
        "signal: none)"
    )


def test_credential_and_path_sanitization() -> None:
    raw_leak_text = (
        "Request failed with Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.t-IDN\n"
        "Configured api_key: 'sk-ant-api03-abcdef1234567890123456789'\n"
        "Failed reading /Users/yululiu/projects/AI/myrm/config/secrets.env\n"
        "Environment GITHUB_TOKEN=ghp_9876543210zyxwvutsrqponmlkjihgfedcba\n"
        "Also generic sk key sk-1234567890abcdef123456 was leaked."
    )

    sanitized = SafeFailureSanitizer.sanitize_text(raw_leak_text)

    # Asserts that sensitive parts are masked
    assert "Bearer [REDACTED_TOKEN]" in sanitized
    assert "eyJhbGci" not in sanitized
    assert "[REDACTED_SECRET]" in sanitized
    assert "sk-ant-api03" not in sanitized
    assert "[PATH_REDACTED]/secrets.env" in sanitized
    assert "/Users/yululiu" not in sanitized
    assert "GITHUB_TOKEN=[REDACTED_ENV]" in sanitized
    assert "ghp_98765" not in sanitized
    assert "[REDACTED_KEY]" in sanitized


def test_byte_limit_enforcement() -> None:
    # 1. Under limit stays unchanged
    short_text = "Standard error message"
    bounded, byte_len = SafeFailureSanitizer.enforce_byte_limit(short_text, max_bytes=4096)
    assert bounded == short_text
    assert byte_len == len(short_text.encode("utf-8"))

    # 2. Over limit is strictly truncated
    massive_text = "A" * 10000
    bounded_huge, byte_len_huge = SafeFailureSanitizer.enforce_byte_limit(
        massive_text,
        max_bytes=MAX_DIAGNOSTIC_FACTS_BYTES,
    )
    assert byte_len_huge <= MAX_DIAGNOSTIC_FACTS_BYTES
    assert "[TRUNCATED_4096B]" in bounded_huge


def test_failure_category_classification() -> None:
    # Rate limit
    assert (
        SubagentDiagnosticProtocol.classify_failure(http_status=429)
        == SubagentFailureCategory.RATE_LIMITED
    )
    assert (
        SubagentDiagnosticProtocol.classify_failure(raw_message="Exceeded organization TPM quota")
        == SubagentFailureCategory.RATE_LIMITED
    )

    # Auth error
    assert (
        SubagentDiagnosticProtocol.classify_failure(http_status=401)
        == SubagentFailureCategory.AUTH_ERROR
    )
    assert (
        SubagentDiagnosticProtocol.classify_failure(raw_message="Permission denied on resource")
        == SubagentFailureCategory.AUTH_ERROR
    )

    # Context window
    assert (
        SubagentDiagnosticProtocol.classify_failure(raw_message="This model's maximum context length is 128000 tokens")
        == SubagentFailureCategory.CONTEXT_WINDOW_EXCEEDED
    )

    # Budget & turns
    assert (
        SubagentDiagnosticProtocol.classify_failure(raw_message="Subagent session budget of $5.00 exhausted")
        == SubagentFailureCategory.SESSION_BUDGET_EXCEEDED
    )
    assert (
        SubagentDiagnosticProtocol.classify_failure(raw_message="Maximum iterations reached without convergence")
        == SubagentFailureCategory.ERROR_MAX_TURNS
    )

    # Signal abortion
    assert (
        SubagentDiagnosticProtocol.classify_failure(signal="SIGTERM")
        == SubagentFailureCategory.PROCESS_ABORTED
    )
    assert (
        SubagentDiagnosticProtocol.classify_failure(exit_code=137)
        == SubagentFailureCategory.PROCESS_ABORTED
    )

    # Timeout
    assert (
        SubagentDiagnosticProtocol.classify_failure(http_status=504)
        == SubagentFailureCategory.NETWORK_TIMEOUT
    )
    assert (
        SubagentDiagnosticProtocol.classify_failure(raw_message="Gateway socket timed out")
        == SubagentFailureCategory.NETWORK_TIMEOUT
    )

    # Sandbox
    assert (
        SubagentDiagnosticProtocol.classify_failure(raw_message="Docker sandbox container killed by OOM killer")
        == SubagentFailureCategory.SANDBOX_ERROR
    )


def test_remediation_action_derivation() -> None:
    assert (
        SubagentDiagnosticProtocol.derive_remediation(
            SubagentFailureCategory.CONTEXT_WINDOW_EXCEEDED,
            SubagentFailureStage.TURN,
        )
        == RemediationAction.COMPACT_AND_RESUME
    )

    assert (
        SubagentDiagnosticProtocol.derive_remediation(
            SubagentFailureCategory.RATE_LIMITED,
            SubagentFailureStage.QUERY_START,
        )
        == RemediationAction.RETRY_WITH_BACKOFF
    )

    assert (
        SubagentDiagnosticProtocol.derive_remediation(
            SubagentFailureCategory.AUTH_ERROR,
            SubagentFailureStage.TURN_START,
        )
        == RemediationAction.ESCALATE_TO_USER
    )

    assert (
        SubagentDiagnosticProtocol.derive_remediation(
            SubagentFailureCategory.SANDBOX_ERROR,
            SubagentFailureStage.PROCESS,
        )
        == RemediationAction.RESPAWN_CLEAN_SANDBOX
    )


def test_create_failure_fact_end_to_end() -> None:
    raw_error = "Connection failed to server with Authorization: Bearer secret-jwt-token. Target path /Users/dev/db.sqlite"
    metadata = {"worker_node": "/Users/dev/workers/01", "trace_id": "tr_12345"}

    fact: StructuredFailureFact = SubagentDiagnosticProtocol.create_failure_fact(
        product="deepseek-coder",
        stage=SubagentFailureStage.PROCESS,
        raw_message=raw_error,
        http_status=504,
        metadata=metadata,
    )

    assert fact.product == "deepseek-coder"
    assert fact.stage == SubagentFailureStage.PROCESS
    assert fact.category == SubagentFailureCategory.NETWORK_TIMEOUT
    assert fact.remediation == RemediationAction.RETRY_ONCE
    assert fact.byte_size <= MAX_DIAGNOSTIC_FACTS_BYTES
    assert fact.safe_diagnostic_header == (
        "Product subagent failure (product: deepseek-coder; stage: process; "
        "category: networkTimeout; HTTP status: 504; exit code: none; signal: none)"
    )
    assert "secret-jwt-token" not in fact.sanitized_message
    assert "[PATH_REDACTED]/db.sqlite" in fact.sanitized_message
    assert "[PATH_REDACTED]/01" in fact.metadata["worker_node"]
