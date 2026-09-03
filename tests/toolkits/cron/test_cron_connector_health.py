"""Unit tests for connector health classification and structured alerts."""

from __future__ import annotations

from myrm_agent_harness.toolkits.cron.engine.connector_health import (
    ConnectorErrorCategory,
    ConnectorFailureDetail,
    ConnectorHealthStatus,
    StructuredAlertPayload,
    classify_connector_error,
    generate_fix_suggestion,
    redact_connector_url,
)


class TestConnectorUrlRedaction:
    def test_empty_or_none(self) -> None:
        assert redact_connector_url(None) == ""
        assert redact_connector_url("") == ""

    def test_basic_auth_redaction(self) -> None:
        url = "https://admin:mysecretpassword@api.example.com/v1/webhook"
        redacted = redact_connector_url(url)
        assert "mysecretpassword" not in redacted
        assert redacted == "https://admin:***@api.example.com/v1/webhook"

    def test_query_params_redaction(self) -> None:
        url = "https://api.example.com/webhook?token=secret123&channel=alerts&api_key=key999"
        redacted = redact_connector_url(url)
        assert "secret123" not in redacted
        assert "key999" not in redacted
        assert "token=" in redacted
        assert "api_key=" in redacted
        assert "channel=alerts" in redacted

    def test_safe_url_unchanged(self) -> None:
        url = "https://hooks.slack.com/services/T00/B00/safe"
        assert redact_connector_url(url) == url


class TestConnectorErrorClassification:
    def test_status_codes(self) -> None:
        cat, msg = classify_connector_error(Exception("any"), status_code=401)
        assert cat == ConnectorErrorCategory.AUTH_FAILURE
        assert "401" in msg

        cat, msg = classify_connector_error(Exception("any"), status_code=404)
        assert cat == ConnectorErrorCategory.HTTP_CLIENT_ERROR
        assert "404" in msg

        cat, msg = classify_connector_error(Exception("any"), status_code=502)
        assert cat == ConnectorErrorCategory.HTTP_SERVER_ERROR
        assert "502" in msg

    def test_error_string_patterns(self) -> None:
        cat, msg = classify_connector_error("Webhook returned 403: Forbidden")
        assert cat == ConnectorErrorCategory.AUTH_FAILURE

        cat, msg = classify_connector_error("Webhook returned 502: Bad Gateway")
        assert cat == ConnectorErrorCategory.HTTP_SERVER_ERROR

        cat, msg = classify_connector_error("ConnectTimeout: connection timed out after 10s")
        assert cat == ConnectorErrorCategory.TIMEOUT

        cat, msg = classify_connector_error("Name or service not known (DNS failure)")
        assert cat == ConnectorErrorCategory.NETWORK_UNREACHABLE

        cat, msg = classify_connector_error("Invalid json response payload too large")
        assert cat == ConnectorErrorCategory.PAYLOAD_CONTRACT

        cat, msg = classify_connector_error("Broken pipe on stdio socket")
        assert cat == ConnectorErrorCategory.PROCESS_ERROR

        cat, msg = classify_connector_error("Unknown internal anomaly")
        assert cat == ConnectorErrorCategory.UNKNOWN


class TestFixSuggestions:
    def test_suggestions(self) -> None:
        sug = generate_fix_suggestion(ConnectorErrorCategory.AUTH_FAILURE)
        assert "secret" in sug or "token" in sug

        sug502 = generate_fix_suggestion(ConnectorErrorCategory.HTTP_SERVER_ERROR, status_code=502)
        assert "reverse proxy" in sug502 or "backend" in sug502

        sug_to = generate_fix_suggestion(ConnectorErrorCategory.TIMEOUT)
        assert "timeout" in sug_to or "latency" in sug_to


class TestStructuredAlertPayload:
    def test_to_dict_schema(self) -> None:
        detail = ConnectorFailureDetail(
            category=ConnectorErrorCategory.HTTP_SERVER_ERROR,
            target="https://api.example.com/hook",
            status_code=502,
            message="Bad Gateway",
        )
        d = detail.to_dict()
        assert d["category"] == "http_server_error"
        assert d["target"] == "https://api.example.com/hook"
        assert d["status_code"] == 502

        payload = StructuredAlertPayload(
            job_id="job_123",
            job_name="Sync Task",
            consecutive_failures=3,
            status=ConnectorHealthStatus.DOWN,
            category=ConnectorErrorCategory.HTTP_SERVER_ERROR,
            target="https://api.example.com/hook",
            error_summary="Destination gateway down (502 Bad Gateway)",
            fix_suggestion="Check server logs.",
            last_status_code=502,
        )
        data = payload.to_dict()
        assert data["event"] == "cron.connector.degraded"
        assert data["job_id"] == "job_123"
        assert data["status"] == "down"

    def test_edge_cases_redaction_and_classification(self) -> None:
        """Thorough verification of edge cases and boundary conditions."""
        # Malformed or exotic URLs
        assert redact_connector_url("not_a_valid_url") == "not_a_valid_url"
        assert redact_connector_url("http://user:pass@") == "http://user:***@"
        # Empty token parameter is masked to prevent leaking
        assert "token=" in redact_connector_url("https://example.com/?token=")

        # Classification with various exception types
        class CustomNetworkErr(IOError):
            pass

        cat, msg = classify_connector_error(CustomNetworkErr("Connection reset by peer"))
        assert cat == ConnectorErrorCategory.NETWORK_UNREACHABLE

        # Empty / None error classifications
        cat, msg = classify_connector_error(None)
        assert cat == ConnectorErrorCategory.UNKNOWN
        assert "Unknown error" in msg

        cat, msg = classify_connector_error("")
        assert cat == ConnectorErrorCategory.UNKNOWN
        assert "Unknown error" in msg

        # HTTP Client 400 bad request / validation error
        cat, msg = classify_connector_error("Bad Request: schema mismatch", status_code=400)
        assert cat == ConnectorErrorCategory.HTTP_CLIENT_ERROR

        # 429 Rate limited
        cat, msg = classify_connector_error("Too Many Requests", status_code=429)
        assert cat == ConnectorErrorCategory.HTTP_CLIENT_ERROR
        sug429 = generate_fix_suggestion(ConnectorErrorCategory.HTTP_CLIENT_ERROR, status_code=429)
        assert "rate limit" in sug429.lower() or "quota" in sug429.lower() or "429" in sug429
