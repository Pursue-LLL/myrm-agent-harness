"""Integration test: Prometheus metrics surface after dead-code cleanup.

Verifies the scraped output matches the ACTIVE metric surface end-to-end:
active metrics are present, removed dead metrics are absent.
"""

from __future__ import annotations

import pytest

pytest.importorskip("prometheus_client")

from prometheus_client import generate_latest

from myrm_agent_harness.observability.metrics import agent_metrics
from myrm_agent_harness.observability.metrics.registry import MetricsRegistry

# Dead metrics removed in the dead-code cleanup. None may reappear in the scrape.
_REMOVED_METRICS = (
    "myrm_llm_call_total",
    "myrm_llm_call_failed_total",
    "myrm_llm_token_usage_total",
    "myrm_llm_call_duration_seconds",
    "myrm_agent_run_total",
    "myrm_agent_run_failed_total",
    "myrm_agent_run_duration_seconds",
)

_ACTIVE_METRICS = (
    "agent_execution_duration_seconds",
    "agent_tool_calls_total",
    "agent_tokens_total",
    "agent_tool_arg_recovery_total",
    "agent_hook_failures_total",
    "agent_approval_denied_total",
    "myrm_time_to_first_action_seconds",
    "myrm_tool_execution_total",
    "myrm_tool_execution_failed_total",
)


@pytest.mark.integration
def test_scrape_output_matches_active_metric_surface() -> None:
    registry = MetricsRegistry()
    assert registry.enabled

    # Record real samples across the active surface so values are non-empty.
    registry.record_execution("it-agent", 2.5, "success")
    registry.record_tool_call("it-agent", "web_search", "success")
    registry.record_tokens("it-agent", "test-model", 10, 5)
    registry.record_tool_arg_recovery("it-agent", "web_search", "fallback", safe=False)
    registry.record_hook_failure("it-agent", "bash", "post_tool_use")
    registry.record_approval_denied("it-agent", "bash_code_execute_tool", "subagent_auto_deny")
    agent_metrics.record_ttfa_run_start()
    agent_metrics.record_ttfa_first_action("it-agent")
    agent_metrics.tool_execution_total.labels(tool_name="web_search").inc()
    agent_metrics.tool_execution_failed_total.labels(tool_name="bash", error_type="timeout").inc()

    output = generate_latest().decode()

    for active in _ACTIVE_METRICS:
        assert active in output, f"active metric missing from scrape: {active}"
    for removed in _REMOVED_METRICS:
        assert removed not in output, f"removed dead metric reappeared in scrape: {removed}"
