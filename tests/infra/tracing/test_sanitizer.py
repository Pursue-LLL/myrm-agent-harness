"""Unit tests for OpenTelemetry trace span and payload privacy sanitizer.

[INPUT]
- myrm_agent_harness.infra.tracing.sanitizer::TraceSpanSanitizer
- myrm_agent_harness.infra.tracing.sanitizer::sanitize_trace_attributes
- myrm_agent_harness.infra.tracing.sanitizer::sanitize_trace_payload

[OUTPUT]
- 覆盖三层渐进脱敏（命名空间白名单、正则凭证掩码、超长文本 SHA-256 截断、任意嵌套 JSON）的单元测试
"""

from myrm_agent_harness.infra.tracing import (
    TraceSpanSanitizer,
    sanitize_trace_attributes,
    sanitize_trace_payload,
)


def test_is_safe_key_allowed_namespaces():
    """Keys starting with standard prefixes are deemed safe."""
    sanitizer = TraceSpanSanitizer()
    assert sanitizer.is_safe_key("gen_ai.request.model") is True
    assert sanitizer.is_safe_key("myrm.agent.turn") is True
    assert sanitizer.is_safe_key("http.status_code") is True
    assert sanitizer.is_safe_key("tool.name") is True
    assert sanitizer.is_safe_key("session.id") is True
    assert sanitizer.is_safe_key("code.filepath") is True


def test_is_safe_key_sensitive_keywords_blocked():
    """Unscoped keys containing sensitive keywords are flagged unsafe."""
    sanitizer = TraceSpanSanitizer()
    assert sanitizer.is_safe_key("user_password") is False
    assert sanitizer.is_safe_key("api_key") is False
    assert sanitizer.is_safe_key("openai_secret") is False
    assert sanitizer.is_safe_key("auth_token") is False
    assert sanitizer.is_safe_key("client_credential") is False


def test_sanitize_string_bearer_token():
    """Bearer tokens in strings are scrubbed by pattern."""
    sanitizer = TraceSpanSanitizer()
    raw = "Authorization: Bearer sk-1234567890abcdef1234567890abcdef"
    cleaned = sanitizer.sanitize_string_value(raw)
    assert "Bearer [REDACTED_BEARER_TOKEN]" in cleaned
    assert "sk-1234567890" not in cleaned


def test_sanitize_string_sensitive_credentials():
    """High-entropy sensitive patterns like OpenAI keys are redacted."""
    sanitizer = TraceSpanSanitizer()
    raw = "Calling LLM with key sk-proj-abcdef12345678901234567890"
    cleaned = sanitizer.sanitize_string_value(raw)
    assert "[REDACTED:" in cleaned
    assert "sk-proj-abcdef" not in cleaned


def test_sanitize_string_length_truncation_with_fingerprint():
    """Strings exceeding max_value_len are truncated with SHA-256 integrity hash."""
    sanitizer = TraceSpanSanitizer(max_value_len=200)
    oversized = "A" * 500
    cleaned = sanitizer.sanitize_string_value(oversized)
    assert len(cleaned) < 500
    assert "[TRUNCATED:len=500:sha256=" in cleaned


def test_sanitize_attributes_layer_one_and_two():
    """Attribute keys and values are sanitized according to layers 1 and 2."""
    raw_attrs = {
        "gen_ai.system": "openai",
        "api_key": "raw_secret_value_12345",
        "tool.args": "Connecting with Bearer token_secret_999",
        "retry_count": 3,
        "is_cached": True,
        "scores": [1.0, 2.5],
        "tags": ["safe", "Bearer internal_tok_888"],
    }
    sanitized = sanitize_trace_attributes(raw_attrs)
    assert sanitized["gen_ai.system"] == "openai"
    assert sanitized["api_key"] == "[REDACTED_SENSITIVE_KEY]"
    assert "Bearer [REDACTED_BEARER_TOKEN]" in str(sanitized["tool.args"])
    assert sanitized["retry_count"] == 3
    assert sanitized["is_cached"] is True
    assert sanitized["scores"] == [1.0, 2.5]
    assert sanitized["tags"] == ["safe", "Bearer [REDACTED_BEARER_TOKEN]"]


def test_sanitize_payload_nested_structure():
    """Nested dictionaries and lists are sanitized recursively without mutating primitives."""
    payload = {
        "session_id": "sess-123",
        "tool_calls": [
            {
                "tool_name": "bash",
                "arguments": {
                    "command": "curl -H 'Authorization: Bearer secret_pass_111' https://internal",
                    "password": "plain_password_here",
                },
                "output": "HTML content " * 300,
                "exit_code": 0,
            }
        ],
        "metadata": {
            "token": "token_abc123",
            "debug": None,
            "latency_ms": 42.5,
        },
    }
    cleaned = sanitize_trace_payload(payload)

    assert cleaned["session_id"] == "sess-123"
    tool_call = cleaned["tool_calls"][0]
    assert tool_call["tool_name"] == "bash"
    assert "Bearer [REDACTED_BEARER_TOKEN]" in tool_call["arguments"]["command"]
    assert tool_call["arguments"]["password"] == "[REDACTED_SENSITIVE_KEY]"
    assert "[TRUNCATED:len=" in tool_call["output"]
    assert tool_call["exit_code"] == 0
    assert cleaned["metadata"]["token"] == "[REDACTED_SENSITIVE_KEY]"
    assert cleaned["metadata"]["debug"] is None
    assert cleaned["metadata"]["latency_ms"] == 42.5


def test_custom_sanitizer_parameters():
    """Custom sanitizer honors custom prefix and min length boundaries."""
    custom = TraceSpanSanitizer(max_value_len=150, safe_prefixes=("custom_safe.",))
    assert custom.is_safe_key("custom_safe.token_count") is True
    assert custom.is_safe_key("other_token") is False

    long_str = "x" * 250
    cleaned = custom.sanitize_string_value(long_str)
    assert "[TRUNCATED:len=250:sha256=" in cleaned
