"""Tests for Three-Layer TraceSpanSanitizer in OpenTelemetry tracing infrastructure."""

from __future__ import annotations

from myrm_agent_harness.infra.tracing.sanitizer import (
    TraceSpanSanitizer,
    sanitize_trace_attributes,
    sanitize_trace_payload,
)


class TestTraceSpanSanitizer:
    def test_layer1_blocks_unauthorized_sensitive_keys(self) -> None:
        sanitizer = TraceSpanSanitizer()
        attrs = {
            "gen_ai.system": "myrm-agent",
            "gen_ai.prompt": "What is Python?",
            "http.method": "POST",
            "custom_secret_key": "raw_sensitive_data",
            "user_token": "abcde12345",
            "db_password": "supersecretpassword",
            "authorization": "Bearer xyz",
        }
        result = sanitizer.sanitize_attributes(attrs)

        # Safe namespaces preserved
        assert result["gen_ai.system"] == "myrm-agent"
        assert result["gen_ai.prompt"] == "What is Python?"
        assert result["http.method"] == "POST"

        # Dangerous keys masked at Layer 1
        assert result["custom_secret_key"] == "[REDACTED_SENSITIVE_KEY]"
        assert result["user_token"] == "[REDACTED_SENSITIVE_KEY]"
        assert result["db_password"] == "[REDACTED_SENSITIVE_KEY]"
        assert result["authorization"] == "[REDACTED_SENSITIVE_KEY]"

    def test_layer2_redacts_credentials_in_values(self) -> None:
        sanitizer = TraceSpanSanitizer()
        attrs = {
            "gen_ai.prompt": "Use apiKey: sk-ant-api03-abcdef12345678901234567890 to call upstream",
            "tool.call_args": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.t-ID",
            "http.url": "https://admin:mypassword123@internal.corp/query",
        }
        result = sanitizer.sanitize_attributes(attrs)

        # Layer 2 redacts sensitive patterns
        assert "sk-ant-" not in str(result["gen_ai.prompt"])
        assert "Bearer eyJ" not in str(result["tool.call_args"])
        assert "mypassword123" not in str(result["http.url"])

    def test_layer3_bounded_hash_truncation(self) -> None:
        sanitizer = TraceSpanSanitizer(max_value_len=256)
        long_text = "A" * 1000
        attrs = {
            "gen_ai.prompt": long_text,
            "tool.output": "B" * 500,
        }
        result = sanitizer.sanitize_attributes(attrs)

        prompt_res = str(result["gen_ai.prompt"])
        assert "[TRUNCATED:len=1000:sha256=" in prompt_res
        assert len(prompt_res) < 500

        output_res = str(result["tool.output"])
        assert "[TRUNCATED:len=500:sha256=" in output_res

    def test_primitive_types_and_sequences_preserved(self) -> None:
        sanitizer = TraceSpanSanitizer()
        attrs = {
            "http.status_code": 200,
            "myrm.latency_ms": 12.34,
            "myrm.is_cache_hit": True,
            "gen_ai.tags": ["agent", "search", "sk-test-token-1234567890"],
        }
        result = sanitizer.sanitize_attributes(attrs)

        assert result["http.status_code"] == 200
        assert result["myrm.latency_ms"] == 12.34
        assert result["myrm.is_cache_hit"] is True

        tags = result["gen_ai.tags"]
        assert isinstance(tags, list)
        assert tags[0] == "agent"
        assert tags[1] == "search"
        assert "sk-test-token" not in str(tags[2])

    def test_sanitize_payload_recursive(self) -> None:
        payload = {
            "session_id": "sess-42",
            "step": 1,
            "active": True,
            "meta": {
                "token": "secret_abc",
                "nested_prompt": "Bearer topsecrettoken",
                "items": ["safe", "Authorization: Bearer mytoken"],
            },
        }
        sanitized = sanitize_trace_payload(payload)

        assert sanitized["session_id"] == "sess-42"
        assert sanitized["step"] == 1
        assert sanitized["active"] is True

        meta = sanitized["meta"]
        assert isinstance(meta, dict)
        assert meta["token"] == "[REDACTED_SENSITIVE_KEY]"
        assert "topsecrettoken" not in str(meta["nested_prompt"])

        items = meta["items"]
        assert isinstance(items, list)
        assert items[0] == "safe"
        assert "mytoken" not in str(items[1])

    def test_convenience_helpers(self) -> None:
        attrs = {"gen_ai.system": "myrm", "api_key": "val"}
        res = sanitize_trace_attributes(attrs)
        assert res["gen_ai.system"] == "myrm"
        assert res["api_key"] == "[REDACTED_SENSITIVE_KEY]"
