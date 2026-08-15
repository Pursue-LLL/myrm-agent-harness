"""Integration test: approval-denied and hook-failure metrics reach Prometheus output.

Covers the real end-to-end link that was previously silently broken:
1. ``record_approval_denied`` (subagent auto-deny path in approval middleware)
2. ``record_hook_failure`` (post-tool hook failure path in tooling helpers)

Unlike unit tests that mock ``metrics_registry``, these tests drive the real
middleware/helper entry points and assert the recorded samples appear in the
actual Prometheus scrape text.
"""

from __future__ import annotations

import pytest

pytest.importorskip("prometheus_client")

from langchain_core.messages import AIMessage, ToolCall
from prometheus_client import REGISTRY, generate_latest

from myrm_agent_harness.agent.middlewares.approval.middleware import (
    ToolApprovalMiddleware,
)
from myrm_agent_harness.agent.middlewares.approval import (
    reset_denial_counter,
    set_approval_session,
    set_security_config,
    set_workspace_root,
)
from myrm_agent_harness.agent.middlewares.tooling._tool_helpers import (
    emit_hook_failure_event,
)
from myrm_agent_harness.agent.security.types import (
    PermissionAction,
    PermissionRule,
    SecurityConfig,
)


class _Runtime:
    pass


@pytest.fixture(autouse=True)
def _isolation() -> None:
    """Reset approval global state so the middleware runs in a clean context."""
    from myrm_agent_harness.agent.security.guards.taint_tracker import (
        reset_taint_tracker,
    )

    reset_taint_tracker()
    reset_denial_counter()


def _sample_value(name: str, labels: dict[str, str]) -> float:
    sample = REGISTRY.get_sample_value(name, labels)
    return sample if sample is not None else 0.0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_subagent_auto_deny_records_approval_denied_metric(monkeypatch) -> None:
    from myrm_agent_harness.observability.metrics.registry import metrics_registry

    assert metrics_registry.enabled

    labels = {
        "agent_id": "base_agent",
        "tool_name": "bash_code_execute_tool",
        "reason": "subagent_auto_deny",
    }
    before = _sample_value("agent_approval_denied_total", labels)

    monkeypatch.setattr(
        "myrm_agent_harness.agent.middlewares.approval.middleware.get_is_subagent",
        lambda: True,
    )
    monkeypatch.setattr(
        "myrm_agent_harness.agent.middlewares._session_context.get_subagent_task_id",
        lambda: None,
    )
    monkeypatch.setattr(
        "myrm_agent_harness.agent.middlewares.approval.middleware.get_is_shadow_agent",
        lambda: False,
    )

    set_security_config(
        SecurityConfig(
            ruleset=(
                PermissionRule("*", "*", PermissionAction.ALLOW),
                PermissionRule("code_interpreter", "*", PermissionAction.ASK),
            )
        )
    )
    set_approval_session("it-session")
    set_workspace_root("/tmp")

    middleware = ToolApprovalMiddleware()
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    ToolCall(
                        type="tool_call",
                        name="bash_code_execute_tool",
                        args={"command": "python3 setup.py install"},
                        id="c1",
                    )
                ],
            )
        ]
    }

    result = await middleware.aafter_model(state, _Runtime())
    assert result is not None

    after = _sample_value("agent_approval_denied_total", labels)
    assert after == before + 1.0, (
        f"agent_approval_denied_total did not increment for {labels}"
    )

    text = generate_latest().decode()
    assert "agent_approval_denied_total" in text
    assert 'reason="subagent_auto_deny"' in text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_hook_failure_records_hook_failure_metric() -> None:
    from myrm_agent_harness.agent.streaming.types import AgentEventType
    from myrm_agent_harness.core.hooks.types import AggregatedHookResult, HookResult
    from myrm_agent_harness.observability.metrics.registry import metrics_registry

    assert metrics_registry.enabled

    labels = {
        "agent_id": "base_agent",
        "tool_name": "bash_code_execute_tool",
        "hook_event": "post_tool_use",
    }
    before = _sample_value("agent_hook_failures_total", labels)

    hook_result = AggregatedHookResult(
        results=(
            HookResult(
                hook_type="callable",
                success=False,
                blocked=True,
                reason="Policy violation detected",
            ),
        )
    )

    await emit_hook_failure_event(
        "bash_code_execute_tool", hook_result, AgentEventType
    )

    after = _sample_value("agent_hook_failures_total", labels)
    assert after == before + 1.0, (
        f"agent_hook_failures_total did not increment for {labels}"
    )

    text = generate_latest().decode()
    assert "agent_hook_failures_total" in text
    assert 'hook_event="post_tool_use"' in text


@pytest.mark.integration
def test_new_metrics_present_in_scrape_surface() -> None:
    """Both newly-added counters must appear in the Prometheus scrape text."""
    from myrm_agent_harness.observability.metrics.registry import metrics_registry

    assert metrics_registry.enabled
    text = generate_latest().decode()
    assert "agent_approval_denied_total" in text
    assert "agent_hook_failures_total" in text
