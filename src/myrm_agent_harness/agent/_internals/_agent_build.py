"""Agent build utilities — middleware chain, tool registry, tool building.

[INPUT]
- agent.middlewares (POS: Various middleware implementations)
- agent.tool_management (POS: ToolRegistry, ToolSource)

[OUTPUT]
- build_middlewares: Build the full middleware chain for a BaseAgent.
- create_registry: Create a fresh ToolRegistry for one build cycle.
- build_tools: Build the resolved tool list via ToolRegistry.
- emit_tools_snapshot: Return Turn1-bound tools for GUI availability view.

[POS]
Agent build utilities — middleware chain construction, tool registry, tool building.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain.agents.middleware import ToolCallLimitMiddleware
from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.middlewares import (
    debug_logger_middleware,
    tool_interceptor_middleware,
)
from myrm_agent_harness.agent.middlewares.approval import ToolApprovalMiddleware
from myrm_agent_harness.agent.middlewares.completion_guard import CompletionGuard
from myrm_agent_harness.agent.middlewares.dangling_tool_call_middleware import (
    dangling_tool_call_middleware,
)
from myrm_agent_harness.agent.middlewares.safety_dispatcher import (
    create_safety_dispatcher,
)
from myrm_agent_harness.agent.middlewares.security_boundary_middleware import (
    SecurityBoundaryMiddleware,
)
from myrm_agent_harness.agent.middlewares.security_guardrail_middleware import (
    SecurityGuardrailMiddleware,
)
from myrm_agent_harness.agent.middlewares.subagent_limit_middleware import (
    subagent_limit_middleware,
)
from myrm_agent_harness.agent.middlewares.tool_call_dedup_middleware import (
    tool_call_dedup_middleware,
)
from myrm_agent_harness.agent.streaming.utils import normalize_tool_names
from myrm_agent_harness.agent.tool_management import ToolBindMode, ToolRegistry, ToolSource
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from myrm_agent_harness.agent.types import EngineParams

logger = get_agent_logger(__name__)

__all__ = ["build_middlewares", "build_tools", "create_registry", "emit_tools_snapshot"]


def build_middlewares(
    registry: ToolRegistry,
    user_middlewares: list[object],
    engine_params: EngineParams | None = None,
) -> list[Any]:
    """Build the full middleware chain for a BaseAgent.

    The ordering matters: dedup -> dangling -> subagent-limit -> interceptor ->
    clarification-guard -> approval -> completion -> replan -> call-limits -> budget -> security -> user -> safety -> debug.
    """
    from myrm_agent_harness.agent.middlewares.clarification_guard_middleware import (
        ClarificationGuardMiddleware,
    )
    from myrm_agent_harness.agent.middlewares.deferred_tool_middleware import (
        DeferredToolMiddleware,
    )
    from myrm_agent_harness.agent.middlewares.deferred_index_middleware import (
        DeferredIndexMiddleware,
    )
    from myrm_agent_harness.agent.middlewares.progress_middleware import (
        progress_middleware,
    )
    from myrm_agent_harness.agent.middlewares.replan_middleware import ReplanMiddleware
    from myrm_agent_harness.agent.types import EngineParams as _EngineParams
    from myrm_agent_harness.utils.token_economics.budget_boundary_middleware import (
        BudgetBoundaryMiddleware,
    )

    params = engine_params or _EngineParams()

    middlewares: list[object] = [
        DeferredToolMiddleware(registry),
        DeferredIndexMiddleware(registry),
        tool_call_dedup_middleware,
        dangling_tool_call_middleware,
        subagent_limit_middleware,
        tool_interceptor_middleware,
        ClarificationGuardMiddleware(),
        ToolApprovalMiddleware(),
        CompletionGuard(),
    ]

    async def get_current_todos(workspace_root: str | None = None):
        if not workspace_root:
            return None
        try:
            from myrm_agent_harness.agent.meta_tools.progress.storage import read_todos_sync_from_workspace

            return read_todos_sync_from_workspace(workspace_root)
        except Exception as e:
            logger.warning("Failed to load todos for middleware: %s", e)
            return None

    middlewares.append(progress_middleware(get_current_todos))

    if params.enable_replan:
        middlewares.append(ReplanMiddleware(max_attempts=params.max_replan_attempts))

    middlewares.extend(
        [
            ToolCallLimitMiddleware(run_limit=params.max_tool_calls, exit_behavior="continue"),
            ToolCallLimitMiddleware(
                tool_name="bash_code_execute_tool",
                run_limit=params.max_bash_calls,
                exit_behavior="continue",
            ),
            BudgetBoundaryMiddleware(),
            SecurityBoundaryMiddleware(),
            SecurityGuardrailMiddleware(),
        ]
    )

    middlewares.extend(user_middlewares)
    middlewares.append(create_safety_dispatcher())
    middlewares.append(debug_logger_middleware)

    return middlewares


def create_registry() -> ToolRegistry:
    """Create a fresh ToolRegistry for one build cycle."""
    return ToolRegistry()


def _weave_dynamic_schemas(resolved_tools: list[BaseTool]) -> list[BaseTool]:
    """Dynamically modify tool schemas based on the available tools context.

    This is the "Schema Weaver" anti-hallucination mechanism.
    If a tool implements `dynamic_schema_modifier(available_names)`, it can return
    a new BaseTool copy with stripped out cross-references (e.g. removing
    'prefer web_search_tool' when web_search_tool is disabled by sandbox/quota).

    Note: Tools should typically use the `with_dynamic_hints` decorator from
    `myrm_agent_harness.agent.tool_management` instead of manually implementing
    the `dynamic_schema_modifier` hook to avoid string replacement fragility.
    """
    available_names = {t.name for t in resolved_tools}
    weaved_tools = []

    for tool in resolved_tools:
        if hasattr(tool, "dynamic_schema_modifier") and callable(tool.dynamic_schema_modifier):
            try:
                modified_tool = tool.dynamic_schema_modifier(available_names)
                weaved_tools.append(modified_tool)
                continue
            except Exception as e:
                logger.warning(
                    f"Tool '{tool.name}' failed to run dynamic_schema_modifier: {e}. Falling back to original schema."
                )
        weaved_tools.append(tool)

    return weaved_tools


async def build_tools(
    registry: ToolRegistry,
    user_tools: list[BaseTool],
    discoverable_tools: list[BaseTool],
    cached_middlewares: list[object],
) -> list[BaseTool]:
    """Build the resolved tool list via ToolRegistry.

    Registers user tools first, then collects any tools exposed by
    middlewares (e.g. ``get_tools()``).
    """
    from myrm_agent_harness.agent.meta_tools.discover_capability.discover_capability_tool import (
        sync_discover_capability_tool,
    )

    registry.register_many(
        normalize_tool_names(user_tools),
        source=ToolSource.USER,
    )

    if discoverable_tools:
        for tool in normalize_tool_names(discoverable_tools):
            registry.register(tool, source=ToolSource.USER, bind_mode=ToolBindMode.DISCOVERABLE)

    for mw in cached_middlewares:
        if hasattr(mw, "get_tools") and callable(mw.get_tools):  # type: ignore[attr-defined]
            try:
                mw_tools = mw.get_tools()  # type: ignore[attr-defined]
                if mw_tools:
                    for t in mw_tools:
                        is_internal = t.name.startswith("_")
                        bind_mode = ToolBindMode.RUNTIME_ONLY if is_internal else ToolBindMode.TURN1
                        registry.register(t, source=ToolSource.MIDDLEWARE, bind_mode=bind_mode)  # type: ignore[arg-type]
                    logger.info(
                        " Loaded %d tools from middleware: %s",
                        len(mw_tools),
                        mw.__class__.__name__,
                    )
            except Exception as exc:
                logger.warning(
                    "Failed to load tools from middleware %s: %s",
                    mw.__class__.__name__,
                    exc,
                )

    sync_discover_capability_tool(registry)

    resolved_tools = registry.resolve()
    return _weave_dynamic_schemas(resolved_tools)


def emit_tools_snapshot(registry: ToolRegistry) -> list[dict[str, object]] | None:
    """Return Turn1-bound tools for GUI availability view.

    Excludes DISCOVERABLE and RUNTIME_ONLY entries so the panel matches
    ``registry.resolve()`` (what the model can call on the current turn).
    """
    try:
        snapshots = registry.snapshot()
        turn1_snapshots = [
            s for s in snapshots if s.bind_mode == ToolBindMode.TURN1.value
        ]
        if not turn1_snapshots:
            return None
        from dataclasses import asdict

        return [asdict(s) for s in turn1_snapshots]
    except Exception as exc:
        logger.warning("Failed to serialize tools snapshot: %s", exc)
        return None
