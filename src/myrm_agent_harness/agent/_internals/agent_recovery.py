"""Agent recovery strategies — context overflow, LLM failover, structured error context.

Shared recovery functions used by ``base_agent.py``, ``streaming/stream_recovery.py``,
and ``middlewares/replan_middleware.py``.

[INPUT]
- agent.base_agent::BaseAgent (POS: Base Agent — lightweight agent with streaming, token tracking, and artifacts.)
- agent.context_management.infra.schemas::ContextConfig (POS: Planner Schema Definitions)
- agent.errors.diagnostics::ErrorContext, (POS: Agent)

[OUTPUT]
- emergency_compact: Aggressively compact *messages* in-place after a context ...
- truncate_oldest_rounds: Drop the oldest API-round groups from *messages* in-place.
- rebuild_agent_with_llm: Rebuild agent graph with a different LLM for failover.
- build_error_context: Build structured error context for LLM prompt injection.
- diagnose_llm_error: Diagnose an LLM error and return (enhanced_message, diagn...

[POS]
Agent recovery strategies — context overflow, LLM failover, structured error context.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from myrm_agent_harness.agent.base_agent import BaseAgent

logger = get_agent_logger(__name__)


# ============================================================================
# Context Overflow Recovery
# ============================================================================

async def emergency_compact(messages: list[BaseMessage]) -> int:
    """Aggressively compact *messages* in-place after a context overflow.

    Uses ``compress_messages_async`` with zeroed thresholds so that all
    eligible tool-call pairs are compressed regardless of normal batch
    heuristics.  Returns the number of tokens saved.
    """
    from myrm_agent_harness.agent.context_management.infra.schemas import ContextConfig
    from myrm_agent_harness.agent.context_management.strategies.compactor import compress_messages_async

    emergency_cfg = ContextConfig(
        max_context_tokens=1,
        compress_min_save=0,
        keep_recent_calls=2,
    )
    _, saved = await compress_messages_async(
        messages,
        dynamic_min_save=0,
        config=emergency_cfg,
    )
    logger.warning(f" Emergency compaction: saved {saved} tokens from {len(messages)} messages")
    return saved


_TRUNCATION_MARKER = "[earlier conversation truncated for context recovery]"
_TRUNCATE_RATIO = 0.2


def truncate_oldest_rounds(messages: list[BaseMessage]) -> int:
    """Drop the oldest API-round groups from *messages* in-place.

    Keeps SystemMessages at the front intact. Groups non-system messages
    into API rounds (Human → AI → Tool*) and drops the oldest ~20 %
    (minimum 1 group). Inserts a synthetic HumanMessage marker at the
    truncation point so the LLM knows context was lost.

    Returns estimated tokens freed.
    """
    from myrm_agent_harness.utils.token_estimation import estimate_messages_tokens

    system_prefix: list[BaseMessage] = []
    rest_start = 0
    for i, msg in enumerate(messages):
        if isinstance(msg, SystemMessage):
            system_prefix.append(msg)
            rest_start = i + 1
        else:
            break

    rest = messages[rest_start:]
    if not rest:
        return 0

    groups: list[list[BaseMessage]] = []
    current: list[BaseMessage] = []
    for msg in rest:
        if isinstance(msg, HumanMessage) and current:
            groups.append(current)
            current = [msg]
        else:
            current.append(msg)
    if current:
        groups.append(current)

    if len(groups) < 2:
        return 0

    drop_count = max(1, int(len(groups) * _TRUNCATE_RATIO))
    drop_count = min(drop_count, len(groups) - 1)

    dropped_msgs: list[BaseMessage] = []
    for g in groups[:drop_count]:
        dropped_msgs.extend(g)
    freed = estimate_messages_tokens(dropped_msgs)

    kept = groups[drop_count:]
    marker = HumanMessage(content=_TRUNCATION_MARKER)

    messages.clear()
    messages.extend(system_prefix)
    messages.append(marker)
    for g in kept:
        messages.extend(g)

    logger.warning(
        f" Head truncation: dropped {drop_count}/{len(groups)} round groups, "
        f"freed ~{freed} tokens, {len(messages)} messages remaining"
    )
    return freed


# ============================================================================
# LLM Failover
# ============================================================================

def rebuild_agent_with_llm(agent: BaseAgent, new_llm: BaseChatModel) -> None:
    """Rebuild agent graph with a different LLM for failover.

    Reuses the cached tools / middlewares / system prompt so the only
    change is the LLM itself.
    """
    from langchain.agents import create_agent

    agent.llm = new_llm
    model = agent._apply_parallel_tool_calls(new_llm)

    agent._agent = create_agent(
        model=model,
        tools=agent._cached_tools,
        system_prompt=agent._cached_system_prompt,
        middleware=cast(list, agent._cached_middlewares),
        context_schema=agent.context_schema,
        checkpointer=agent.checkpointer,
    )


# ============================================================================
# Structured Error Context
# ============================================================================

ERROR_RECOVERY_HINTS: dict[str, list[str]] = {
    "FileNotFoundError": [
        "Verify the file path is correct and the file exists",
        "Check if the file was moved or deleted recently",
        "Ensure you have read permissions for the directory",
    ],
    "PermissionError": [
        "Check if you have sufficient permissions to access the resource",
        "Try running with appropriate user permissions",
        "Verify file/directory ownership and permissions",
    ],
    "ConnectionError": [
        "Check your network connection",
        "Verify the remote server is accessible",
        "Check if firewall rules are blocking the connection",
    ],
    "TimeoutError": [
        "The operation took too long — try increasing the timeout",
        "Check if the remote service is responding",
        "Verify network latency and bandwidth",
    ],
    "ValidationError": [
        "Check if input data matches the expected schema",
        "Verify all required fields are provided",
        "Ensure data types are correct",
    ],
    "SyntaxError": [
        "Check for typos or missing punctuation in the code",
        "Verify the code follows the correct syntax for the language",
        "Look for mismatched brackets or quotes",
    ],
    "ImportError": [
        "Verify the module/package is installed",
        "Check for circular import dependencies",
        "Ensure the import path is correct",
    ],
    "KeyError": [
        "Verify the key exists in the dictionary before accessing",
        "Check for typos in the key name",
        "Use .get() with a default value for optional keys",
    ],
    "TypeError": [
        "Check that argument types match the function signature",
        "Verify you're not passing None where a value is expected",
        "Ensure operand types are compatible",
    ],
}


def build_error_context(
    operation: str,
    target: str,
    error: str,
    previous_attempts: list[str] | None = None,
) -> str:
    """Build structured error context for LLM prompt injection.

    Providing the LLM with explicit error details, prior attempts, and
    actionable hints reduces blind retry loops.  Based on patterns
    documented at AgentPatterns.ai.
    """
    error_type = _extract_error_type(error)
    hints = ERROR_RECOVERY_HINTS.get(error_type, [
        "Analyse the error message carefully for clues",
        "Consider alternative approaches to achieve the goal",
        "Check if prerequisites or dependencies are missing",
    ])

    parts = [
        "## Error Recovery Context",
        "",
        f"**Operation**: {operation}",
        f"**Target**: {target}",
        f"**Error**: {error}",
        "",
    ]

    if previous_attempts:
        parts.append(f"**Previous Attempts** ({len(previous_attempts)}):")
        parts.extend(f" {i + 1}. {a}" for i, a in enumerate(previous_attempts))
        parts.append("")

    parts.append("**Recovery Hints**:")
    parts.extend(f" - {h}" for h in hints)
    parts.append("")
    parts.append("Please analyse the error and determine the best recovery strategy.")

    return "\n".join(parts)


_ERROR_TYPE_RE = re.compile(r"^(\w+Error)")


def _extract_error_type(error: str) -> str:
    """Extract the error class name from the head of *error*."""
    match = _ERROR_TYPE_RE.search(error)
    return match.group(1) if match else "UnknownError"


# ============================================================================
# Error Diagnostics
# ============================================================================

def diagnose_llm_error(
    exc: Exception,
    llm: BaseChatModel,
    locale: str | None,
) -> tuple[str, dict[str, object] | None]:
    """Diagnose an LLM error and return (enhanced_message, diagnostic_dict).

    Returns the original error string and ``None`` if diagnostics fail.
    """
    from myrm_agent_harness.agent.errors.diagnostics import ErrorContext, LLMErrorDiagnostic

    error_msg = str(exc)
    diagnostic_dict: dict[str, object] | None = None
    try:
        model_name = getattr(llm, "model_name", getattr(llm, "model", "unknown"))
        base_url = getattr(llm, "base_url", None)
        ctx = ErrorContext(
            model_name=str(model_name),
            is_custom_endpoint=base_url is not None,
            base_url=str(base_url) if base_url else None,
        )
        diagnostic = LLMErrorDiagnostic.diagnose(exc, ctx, locale=locale)
        diagnostic_dict = {
            "error_type": diagnostic.error_type,
            "user_message": diagnostic.user_message,
            "resolution_steps": diagnostic.resolution_steps,
            "locale": diagnostic.locale,
        }
        resolution_steps = "\n".join(f" - {step}" for step in diagnostic.resolution_steps)
        error_msg = f"{diagnostic.user_message}\n\nResolution steps:\n{resolution_steps}"
        logger.error(f" {diagnostic.user_message}")
        logger.error(f"Resolution steps:\n{resolution_steps}")
    except Exception:
        logger.error("Diagnostic failed for %s: %s", type(exc).__name__, str(exc)[:300], exc_info=True)

    return error_msg, diagnostic_dict
