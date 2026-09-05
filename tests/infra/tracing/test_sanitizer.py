"""Unit tests for Three-layer Trace Privacy Sanitizer and SpanProcessor.

[TESTS]
- Layer 1: High-risk key detection vs safe namespace prefix whitelist
- Layer 2: Sensitive pattern redaction (Bearer, API Keys, Passwords)
- Layer 3: Long payload bounded truncation with SHA-256 fingerprint preservation
- SanitizingSpanProcessor: OpenTelemetry Span attribute scrub prior to export
"""

from __future__ import annotations

import pytest
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult

from myrm_agent_harness.infra.tracing.sanitizer import (
    SanitizingSpanProcessor,
    TraceSpanSanitizer,
    sanitize_trace_attributes,
    sanitize_trace_payload,
)


class MemorySpanExporter(SpanExporter):
    """Simple in-memory exporter capturing sanitized ReadableSpans for testing."""

    def __init__(self) -> None:
        self.spans: list[ReadableSpan] = []

    def export(self, spans: list[ReadableSpan]) -> SpanExportResult:
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass


def test_layer1_key_namespace_allowlist_and_sensitive_key_redaction() -> None:
    sanitizer = TraceSpanSanitizer()

    # Safe namespace prefixes should pass regardless of naming
    assert sanitizer.is_safe_key("gen_ai.request.model") is True
    assert sanitizer.is_safe_key("myrm.agent.id") is True
    assert sanitizer.is_safe_key("tool.call.parameters") is True
    assert sanitizer.is_safe_key("http.status_code") is True

    # High-risk un-namespaced keys should be flagged as unsafe
    assert sanitizer.is_safe_key("user_password") is False
    assert sanitizer.is_safe_key("api_key") is False
    assert sanitizer.is_safe_key("auth_token") is False
    assert sanitizer.is_safe_key("session_secret") is False

    attributes = {
        "gen_ai.request.model": "gpt-4o",
        "raw_user_password": "supersecretpassword123",
        "custom.auth_token": "token-xyz-888",
        "normal_meta": "safe-value",
    }
    sanitized = sanitizer.sanitize_attributes(attributes)
    assert sanitized["gen_ai.request.model"] == "gpt-4o"
    assert sanitized["normal_meta"] == "safe-value"
    assert sanitized["raw_user_password"] == "[REDACTED_SENSITIVE_KEY]"
    assert sanitized["custom.auth_token"] == "[REDACTED_SENSITIVE_KEY]"


def test_layer2_pattern_redaction() -> None:
    sanitizer = TraceSpanSanitizer()

    # Bearer token redaction
    bearer_text = "curl -H 'Authorization: Bearer sk-ant-api03-abcdef1234567890' https://api.anthropic.com"
    redacted = sanitizer.sanitize_string_value(bearer_text)
    assert "sk-ant-api03-abcdef1234567890" not in redacted
    assert "[REDACTED" in redacted

    # OpenAI-like API Key redaction
    openai_text = "Using key sk-proj-1234567890abcdef1234567890 to connect"
    redacted_openai = sanitizer.sanitize_string_value(openai_text)
    assert "sk-proj-1234567890abcdef1234567890" not in redacted_openai


def test_layer3_bounded_truncation_with_sha256() -> None:
    sanitizer = TraceSpanSanitizer(max_value_len=256)

    long_str = "x" * 1000
    res = sanitizer.sanitize_string_value(long_str)
    assert len(res) < 500
    assert "[TRUNCATED:len=1000:sha256=" in res

    # Short string should remain unchanged
    short_str = "This is a concise tool output."
    assert sanitizer.sanitize_string_value(short_str) == short_str


def test_sanitize_trace_payload_recursive() -> None:
    payload = {
        "session_id": "sess-001",
        "api_secret": "raw-key-12345",
        "metadata": {
            "gen_ai.system": "open-perplexity",
            "db_password": "mypassword999",
            "nested_list": [
                "Bearer eyJhbGciOi...",
                {"inner_secret": "val", "safe_val": 42},
            ],
        },
        "massive_body": "A" * 5000,
    }

    sanitized = sanitize_trace_payload(payload)
    assert sanitized["session_id"] == "sess-001"
    assert sanitized["api_secret"] == "[REDACTED_SENSITIVE_KEY]"

    meta = sanitized["metadata"]
    assert isinstance(meta, dict)
    assert meta["gen_ai.system"] == "open-perplexity"
    assert meta["db_password"] == "[REDACTED_SENSITIVE_KEY]"

    nested = meta["nested_list"]
    assert isinstance(nested, list)
    assert "[REDACTED" in str(nested[0])
    assert nested[1]["inner_secret"] == "[REDACTED_SENSITIVE_KEY]"
    assert nested[1]["safe_val"] == 42

    massive = sanitized["massive_body"]
    assert isinstance(massive, str)
    assert "[TRUNCATED:len=5000:sha256=" in massive


def test_sanitizing_span_processor_integration() -> None:
    provider = TracerProvider()
    exporter = MemorySpanExporter()

    # Register SanitizingSpanProcessor prior to exporter
    provider.add_span_processor(SanitizingSpanProcessor(max_value_len=128))
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    tracer = provider.get_tracer("test_privacy")
    with tracer.start_as_current_span("exec_tool") as span:
        span.set_attribute("gen_ai.operation.name", "execute_code")
        span.set_attribute("user_password", "plaintext_secret_123")
        span.set_attribute("auth.token", "Bearer secret-token-value")
        span.set_attribute("massive_output", "Z" * 1000)

    assert len(exporter.spans) == 1
    exported = exporter.spans[0]
    attrs = exported.attributes
    assert attrs is not None

    # Layer 1
    assert attrs["gen_ai.operation.name"] == "execute_code"
    assert attrs["user_password"] == "[REDACTED_SENSITIVE_KEY]"

    # Layer 2
    assert "secret-token-value" not in str(attrs.get("auth.token"))

    # Layer 3
    assert "[TRUNCATED:len=1000:sha256=" in str(attrs.get("massive_output"))
