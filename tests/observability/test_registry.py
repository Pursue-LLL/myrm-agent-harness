"""Tests for Observability Metrics Registry."""

from myrm_agent_harness.observability.metrics.registry import MetricsRegistry, generate_prometheus_metrics


def test_metrics_registry_singleton():
    reg1 = MetricsRegistry()
    reg2 = MetricsRegistry()
    assert reg1 is reg2


def test_record_execution():
    registry = MetricsRegistry()
    if not registry.enabled:
        return

    registry.record_execution("test_agent", 1.5, "success")

    metrics_text = generate_prometheus_metrics()
    assert "agent_execution_duration_seconds" in metrics_text
    assert 'agent_id="test_agent"' in metrics_text
    assert 'status="success"' in metrics_text


def test_record_tool_call():
    registry = MetricsRegistry()
    if not registry.enabled:
        return

    registry.record_tool_call("test_agent", "web_search", "success")

    metrics_text = generate_prometheus_metrics()
    assert "agent_tool_calls_total" in metrics_text
    assert 'tool_name="web_search"' in metrics_text


def test_record_tokens():
    registry = MetricsRegistry()
    if not registry.enabled:
        return

    registry.record_tokens("test_agent", "gpt-4", 100, 50)

    metrics_text = generate_prometheus_metrics()
    assert "agent_tokens_total" in metrics_text
    assert 'model="gpt-4"' in metrics_text
    assert 'token_type="prompt"' in metrics_text
    assert 'token_type="completion"' in metrics_text
