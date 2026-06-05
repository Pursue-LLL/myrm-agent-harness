"""Subagent construction helpers — tool filtering, model resolution, token merge.

Pure functions and utilities used by SubagentManager to prepare child agents.

[INPUT]
- agent.base_agent::BaseAgent (POS: Base Agent — lightweight agent with streaming, token tracking, and artifacts.)
- utils.token_economics.tracker::TokenTracker, (POS: Skill quality tracking and FIX evolution triggering.)
- agent.types::AgentRuntimeConfig (POS: Provides ArtifactInfo, infer_language, infer_artifact_type.)
- agent.sub_agents.types::DelegationCapabilityManifest (POS: Subagent subsystem core type definitions. Defines all subagent-related data types, enums, and protocols.)

[OUTPUT]
- filter_tools: Apply tool safety isolation after catalog admission.
- resolve_llm: Resolve child LLM with optional complexity-tier routing.
- truncate_result: Truncate text to approximate token limit (4 chars per token).
- merge_child_stats: Merge child agent's token usage into the parent tracker.
- build_child_agent: Build a child agent with filtered tools, inherited budget state, and a stable system prompt.

[POS]
Subagent construction helpers. Prepare child agents without business-layer dependencies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from langchain_core.tools import BaseTool

from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .budget import DelegationBudgetState
from .types import DELEGATION_CAPABILITY_MANIFEST, SubagentConfig

if TYPE_CHECKING:
    from myrm_agent_harness.agent.base_agent import BaseAgent

logger = get_agent_logger(__name__)


_HANDOVER_PROTOCOL_PROMPT = (
    "[Handover Protocol]\n"
    "When you have completed your task, you MUST output a structured handover state before finishing.\n"
    "Format your handover state exactly like this XML block:\n"
    "<handover>\n"
    "{\n"
    '  "task_completed": ["list of completed items"],\n'
    '  "pending_todos": ["list of items left for the next agent"],\n'
    '  "risks_or_notes": ["any risks, warnings, or pitfalls"],\n'
    '  "relevant_files": ["files that are relevant to this task"]\n'
    "}\n"
    "</handover>"
)


def filter_tools(config: SubagentConfig, parent_tools: list[BaseTool]) -> list[BaseTool]:
    """Apply tool safety isolation (L1-L3; L0 is enforced by delegate_task).

    L1: DelegationCapabilityManifest.leaf_blocked_tools (always blocked)
    L2: config.tools (allowlist) + config.disallowed_tools (blocklist)
    L3: child ⊆ parent intersection
    """
    parent_tool_names = {t.name for t in parent_tools}
    leaf_blocked_tools = DELEGATION_CAPABILITY_MANIFEST.leaf_blocked_tools
    blocked = leaf_blocked_tools | config.disallowed_tools

    blocked_by_l1: list[str] = []
    blocked_by_l2: list[str] = []
    filtered: list[BaseTool] = []
    for tool in parent_tools:
        if tool.name in blocked:
            if tool.name in leaf_blocked_tools:
                blocked_by_l1.append(tool.name)
            else:
                blocked_by_l2.append(tool.name)
            continue
        if config.tools and tool.name not in config.tools:
            blocked_by_l2.append(tool.name)
            continue
        filtered.append(tool)

    if blocked_by_l1 or blocked_by_l2:
        logger.debug(
            "[subagent] Tool filter: L1(global)=%s, L2(config)=%s, passed=%d/%d",
            sorted(blocked_by_l1),
            sorted(blocked_by_l2),
            len(filtered),
            len(parent_tools),
        )

    if config.tools:
        missing = set(config.tools) - parent_tool_names - blocked
        if missing:
            logger.warning("[subagent] Tools not available in parent: %s", sorted(missing))

    return filtered


async def resolve_llm(
    config: SubagentConfig,
    parent_agent: BaseAgent,
    complexity_tier: str | None = None,
    task_description: str | None = None,
) -> object:
    """Resolve LLM via 4-level chain: config.llm → model_resolver → config.model log → parent LLM.

    Level 1: config.llm — pre-built LLM instance (set by business layer)
    Level 2: config.model + config.model_resolver — string name resolved to LLM via injected resolver
    Level 3: config.model without resolver — logged, falls through to parent
    Level 4: parent LLM — inherited from parent agent (default)
    """
    if config.llm is not None:
        logger.info("[subagent] Using config.llm override (type=%s)", type(config.llm).__name__)
        return config.llm
    if config.model:
        if config.model_resolver is not None:
            try:
                # Pass complexity_tier and task_description to model_resolver if it supports it
                import inspect

                sig = inspect.signature(config.model_resolver.resolve)
                kwargs = {}
                if "complexity_tier" in sig.parameters:
                    kwargs["complexity_tier"] = complexity_tier
                if "task_description" in sig.parameters:
                    kwargs["task_description"] = task_description
                resolved = await config.model_resolver.resolve(config.model, **kwargs)
                logger.info("[subagent] Resolved model '%s' via model_resolver", config.model)
                return resolved
            except Exception as e:
                logger.warning(
                    "[subagent] model_resolver failed for '%s', falling back to parent LLM: %s", config.model, e
                )
        else:
            logger.info(
                "[subagent] Model '%s' requested but no model_resolver provided; "
                "falling back to parent LLM. Set config.llm or config.model_resolver.",
                config.model,
            )
    return parent_agent.llm


def truncate_result(text: str, max_tokens: int | None) -> str:
    """Truncate text to approximate token limit (4 chars ≈ 1 token)."""
    if not max_tokens or not text:
        return text
    char_limit = max_tokens * 4
    if len(text) <= char_limit:
        return text
    return text[:char_limit] + f"\n\n[Truncated: output exceeded {max_tokens} token limit]"


def merge_child_stats(parent_tracker: object, child_stats: object) -> None:
    """Merge child agent's token usage into the parent tracker.

    child_agent.run() manages its own TokenTracker via ContextVar internally,
    so we retrieve the actual usage from child_stats (AgentRunStatistics)
    instead of relying on a shared ContextVar scope.
    """
    from myrm_agent_harness.utils.token_economics.tracker import _TOKEN_USAGE_FIELDS, TokenTracker, TokenUsage

    if not isinstance(parent_tracker, TokenTracker):
        return

    child_usage = getattr(child_stats, "token_usage", None)
    if not isinstance(child_usage, TokenUsage):
        return

    for field_name in _TOKEN_USAGE_FIELDS:
        current = getattr(parent_tracker.usage, field_name)
        child_val = getattr(child_usage, field_name)
        setattr(parent_tracker.usage, field_name, current + child_val)

    child_model_usage: dict[str, object] | None = getattr(child_stats, "model_usage", None)
    if child_model_usage:
        for model, model_data in child_model_usage.items():
            if model not in parent_tracker.model_usage:
                parent_tracker.model_usage[model] = TokenUsage()
            target = parent_tracker.model_usage[model]
            if isinstance(model_data, dict):
                for f in _TOKEN_USAGE_FIELDS:
                    setattr(target, f, getattr(target, f) + model_data.get(f, 0))
                cost_usd = model_data.get("cost_usd", 0.0)
                if isinstance(cost_usd, (int, float)):
                    parent_tracker.model_cost[model] = parent_tracker.model_cost.get(model, 0.0) + cost_usd

    cost_usd = getattr(child_stats, "cost_usd", 0.0)
    if isinstance(cost_usd, (int, float)):
        parent_tracker.total_cost_usd += cost_usd

    child_cost_status = getattr(child_stats, "cost_status", "unknown")
    if child_cost_status == "actual" or (parent_tracker.cost_status == "unknown" and child_cost_status != "unknown"):
        parent_tracker.cost_status = child_cost_status


async def build_child_agent(
    config: SubagentConfig,
    tools: list[BaseTool],
    task_description: str,
    parent_agent: BaseAgent,
    current_depth: int,
    complexity_tier: str | None = None,
) -> BaseAgent:
    """Build a child agent with filtered tools and resolved LLM.

    When config.agent_factory is set, delegates full construction to the
    business-layer factory (e.g., creating a SkillAgent with memory, skills,
    MCP). Otherwise, creates a bare BaseAgent.

    checkpointer is intentionally omitted for bare BaseAgent: child agents are
    ephemeral and sharing the parent's checkpoint thread would pollute its
    message history. AgentFactory implementations may provide their own.
    """
    if config.agent_factory is not None:
        logger.info("[subagent] Using AgentFactory for child agent construction")
        child = cast(
            "BaseAgent",
            await config.agent_factory.build(
                config=config,
                tools=tools,
                task_description=task_description,
                parent_agent=parent_agent,
                current_depth=current_depth,
                complexity_tier=complexity_tier,
            ),
        )
        _inherit_child_runtime_limits(child, parent_agent, current_depth, config)
        return child

    from langchain_core.language_models import BaseChatModel

    from myrm_agent_harness.agent.base_agent import BaseAgent
    from myrm_agent_harness.agent.middlewares import create_context_pipeline_middleware

    # 10/10 Scheme: If context is forked, we MUST drop the system_prompt entirely.
    # Otherwise, LangGraph prepends a new SystemMessage, shifting the array and breaking Prefix Cache!
    if config.context_mode == "fork":
        system_prompt = ""
    else:
        system_prompt = config.system_prompt
        system_prompt = (
            f"{system_prompt}\n\n{_HANDOVER_PROTOCOL_PROMPT}" if system_prompt else _HANDOVER_PROTOCOL_PROMPT
        )

    llm = cast(
        BaseChatModel,
        await resolve_llm(config, parent_agent, complexity_tier=complexity_tier, task_description=task_description),
    )

    from myrm_agent_harness.agent.types import AgentRuntimeConfig

    middlewares = []
    if parent_agent.config.engine_params.enable_context_compression:
        middlewares.append(create_context_pipeline_middleware(llm=llm))

    child = BaseAgent(
        llm=llm,
        executor=parent_agent.executor,
        system_prompt=system_prompt,
        tools=tools,
        middlewares=middlewares,
        checkpointer=None,
        config=AgentRuntimeConfig(
            recursion_limit=min(config.max_turns * 2, parent_agent.config.recursion_limit),
            timeout_seconds=parent_agent.config.engine_params.timeout_seconds or config.timeout_seconds,
            parallel_tool_calls=parent_agent.config.engine_params.enable_parallel_tool_calls,
            collect_artifacts=False,
            security_config=parent_agent.config.security_config,
            engine_params=parent_agent.config.engine_params,
        ),
    )
    _inherit_child_runtime_limits(child, parent_agent, current_depth, config)
    return child


def _inherit_child_runtime_limits(
    child: BaseAgent,
    parent_agent: BaseAgent,
    current_depth: int,
    config: SubagentConfig,
) -> None:
    """Attach parent-scoped delegation limits to the child manager."""
    parent_manager = getattr(parent_agent, "_subagent_manager", None)
    budget_state = getattr(parent_manager, "budget_state", None)
    if not isinstance(budget_state, DelegationBudgetState):
        budget_state = DelegationBudgetState(max_descendants=config.max_descendants_per_run)

    parent_limit = getattr(parent_manager, "_max_children_per_agent", config.max_children_per_agent)
    max_children = min(
        max(1, int(parent_limit)),
        max(1, config.max_children_per_agent),
    )
    child._subagent_manager.inherit_runtime_limits(
        current_depth=current_depth + 1,
        budget_state=budget_state,
        max_children_per_agent=max_children,
    )


def build_standalone_agent(
    llm: object, config: SubagentConfig, tools: list[BaseTool], task_description: str, executor: object | None = None
) -> BaseAgent:
    """Build an independent BaseAgent without a parent agent context.

    Unlike build_child_agent, this does not require a parent BaseAgent.
    Designed for orchestrators (e.g. Deep Research) that manage agents
    directly rather than through the BaseAgent tree.
    """
    from langchain_core.language_models import BaseChatModel

    from myrm_agent_harness.agent.base_agent import BaseAgent
    from myrm_agent_harness.agent.middlewares import create_context_pipeline_middleware
    from myrm_agent_harness.agent.types import AgentRuntimeConfig

    system_prompt = config.system_prompt
    if task_description:
        system_prompt = f"{task_description}\n\n{system_prompt}" if system_prompt else task_description

    if system_prompt:
        system_prompt += f"\n\n{_HANDOVER_PROTOCOL_PROMPT}"

    llm_instance = cast(BaseChatModel, llm)

    return BaseAgent(
        llm=llm_instance,
        executor=executor,
        system_prompt=system_prompt,
        tools=tools,
        middlewares=[create_context_pipeline_middleware(llm=llm_instance)],
        config=AgentRuntimeConfig(
            recursion_limit=config.max_turns * 2, timeout_seconds=config.timeout_seconds, collect_artifacts=False
        ),
    )
