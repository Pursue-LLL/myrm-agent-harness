"""Tool Interceptor Helpers

[INPUT]
- langchain_core.messages::ToolMessage (POS: Core message type definitions)
- agent.errors.tool_error_category::ToolErrorCategory (POS: Canonical tool error categories for structured error classification.)
- agent.security.guards.estop (POS: Global guard)
- agent.security.types (POS: Security type definitions)
- agent.security.audit::record_decision (POS: Cross-cutting security audit)
- agent.security.detection.content_boundary::sanitize (POS: Structural framing token stripping for tool error messages)
- agent.security.detection.tool_result_validator (POS: Tool result content validation)
- core.security.guards.privacy_tracker::get_privacy_policy (POS: Per-turn privacy state tracker. ContextVar-based privacy policy access.)
- utils.errors::ToolError (POS: Framework-level tool errors)
- toolkits.browser.exceptions::BrowserError (POS: Browser tool exceptions)
- toolkits.web_search.core.exceptions::WebSearchError (POS: Web search exceptions)
- toolkits.web_search.core.exceptions::SearchAPIError, SearchConfigError (POS: Structured config/auth search errors for terminal classification)

[OUTPUT]
- NON_RETRYABLE_ERRORS: Tuple of exception types that should not be retried
- TERMINAL_CONFIG_OR_AUTH: Terminal error category prefix for config/auth failures
- _CONFIG_OR_AUTH_FAMILY_SEARCH / _CONFIG_OR_AUTH_FAMILY_BROWSER: Family-scoped terminal categories
- classify_terminal_error(): Classify non-recoverable terminal errors (config/auth, family-scoped)
- smart_truncate_output(): Keep first/last N lines, truncate middle
- get_tool_timeout(): Zero-config timeout by tool name pattern
- is_non_retryable(): Check if exception should not be retried
- is_semantic_business_error(): Check if tool payload represents a business error under HTTP 200
- check_semantic_failure_retryable(): Check if tool payload is a transient, retryable business failure
- make_error_msg(): Build a ToolMessage with error status and structured metadata
- format_tool_error(): Format exception for LLM consumption
- apply_validation_result(): Append validation warning to ToolMessage
- check_trust_attenuation(): Check if tool is blocked by trust policy
- extract_text_content(): Extract plain text from ToolMessage content
- check_tool_params_pii(): Check tool parameters for PII
- check_tool_result_pii(): Check and optionally redact PII in tool results

[POS]
Stateless helper functions for tool_interceptor_middleware. Extracted to keep the
main middleware file focused on orchestration logic.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import ToolException

from myrm_agent_harness.agent.errors.tool_error_category import ToolErrorCategory
from myrm_agent_harness.agent.security.audit import record_decision
from myrm_agent_harness.agent.security.detection.tool_result_validator import (
    should_apply_validation,
    validate_tool_result,
)
from myrm_agent_harness.agent.security.redact import redact_sensitive_text
from myrm_agent_harness.agent.security.types import PIIAction, SensitivityLevel
from myrm_agent_harness.core.security.guards.privacy_tracker import get_privacy_policy
from myrm_agent_harness.toolkits.browser.exceptions import BrowserError
from myrm_agent_harness.toolkits.web_search.core.exceptions import (
    SearchAPIError,
    SearchConfigError,
    WebSearchError,
)
from myrm_agent_harness.utils.errors import ToolError
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from myrm_agent_harness.agent.security.detection.tool_result_validator import (
        ValidationResult,
    )

logger = get_agent_logger(__name__)

NON_RETRYABLE_ERRORS = (
    ToolError,
    BrowserError,
    WebSearchError,
    asyncio.CancelledError,
    ToolException,
)


def smart_truncate_output(text: str, max_lines: int = 20) -> str:
    """Keep first N/2 and last N/2 lines, truncate middle.

    Prevents token inflation when including large tool outputs in error messages.
    """
    lines = text.split("\n")
    if len(lines) <= max_lines:
        return text

    keep = max_lines // 2
    truncated_count = len(lines) - max_lines
    return "\n".join(
        [
            *lines[:keep],
            f"... [truncated {truncated_count} lines for token optimization] ...",
            *lines[-keep:],
        ]
    )


def get_tool_timeout(tool_name: str, tool_args: dict[str, object] | None = None) -> float:
    """Get timeout for tool based on name pattern matching (zero-config).

    When a tool's input schema declares an explicit ``timeout`` argument (e.g.
    ``bash_code_execute_tool``), the caller supplies ``tool_args`` so the executor
    honors it for long-running commands instead of silently killing them at the
    zero-config default.

    Returns:
        Timeout in seconds: 300s for media generation, 120s for shell/browser/mcp,
        30s for file I/O, 60s default. An explicit ``tool_args["timeout"]`` on
        shell/browser/mcp floats the floor up to it (clamped to 600s, matching the
        ``BashInput.timeout`` max).
    """
    base = 60.0
    if tool_name.startswith(("image_tool", "video_tool")):
        base = 300.0
    elif tool_name.startswith(("bash", "browser", "mcp_")):
        base = 120.0
    elif tool_name.startswith(("file_read", "file_write", "file_edit", "glob", "grep")):
        base = 30.0

    explicit = tool_args and tool_args.get("timeout")
    if tool_name.startswith(("bash", "browser", "mcp_")):
        if isinstance(explicit, int) and not isinstance(explicit, bool) and explicit > 0:
            return min(float(explicit), 600.0)
    return base


def is_non_retryable(e: Exception, tool_name: str) -> bool:
    """Check if exception should not be retried."""
    from langgraph.errors import GraphInterrupt

    if isinstance(e, NON_RETRYABLE_ERRORS):
        return True
    if isinstance(e, (GraphInterrupt, InterruptedError)):
        return True

    # HTTP Status Error Classification
    # 400 Bad Request, 401 Unauthorized, 403 Forbidden, 404 Not Found -> Non-retryable
    # 429 Too Many Requests, 5xx Server Errors -> Retryable
    response = getattr(e, "response", None)
    if response is not None:
        status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int) and status_code in (400, 401, 403, 404):
            return True

    return tool_name == "bash_code_execute_tool"


def is_semantic_business_error(content: object, tool_name: str) -> bool:
    """Check if tool return payload represents a business error under HTTP 200."""
    from myrm_agent_harness.agent.middlewares.tooling.semantic_failure_sniffer import (
        sniff_semantic_failure,
    )

    return sniff_semantic_failure(content, tool_name=tool_name).is_failure


def check_semantic_failure_retryable(
    content: object,
    tool_name: str,
    *,
    tool_args: dict[str, object] | None = None,
) -> tuple[bool, str]:
    """Check if tool payload is a transient, retryable business failure.

    Returns (is_retryable, failure_reason).
    """
    from myrm_agent_harness.agent.middlewares.tooling.semantic_failure_sniffer import (
        SemanticFailureType,
        should_skip_semantic_sniff,
        sniff_semantic_failure,
    )

    if should_skip_semantic_sniff(tool_name, tool_args=tool_args):
        return False, ""

    sniff_res = sniff_semantic_failure(content, tool_name=tool_name, tool_args=tool_args)
    if sniff_res.is_failure and sniff_res.failure_type == SemanticFailureType.RETRYABLE:
        return True, sniff_res.reason
    return False, ""


# ---------------------------------------------------------------------------
# Non-recoverable (terminal) error classification
# ---------------------------------------------------------------------------

# Terminal error category registered into TerminalErrorRegistry so the
# circuit breaker blocks subsequent calls of the same class within the turn.
# Model can never fix these by retrying a different query / different args.
#
# config_or_auth is scoped per tool family so a broken search configuration
# does not disable browser tools (independent infrastructure) and vice versa.
TERMINAL_CONFIG_OR_AUTH = "config_or_auth"
_CONFIG_OR_AUTH_FAMILY_SEARCH = f"{TERMINAL_CONFIG_OR_AUTH}:search"
_CONFIG_OR_AUTH_FAMILY_BROWSER = f"{TERMINAL_CONFIG_OR_AUTH}:browser"


def classify_terminal_error(e: Exception) -> str | None:
    """Classify an exception as a non-recoverable terminal error.

    Returns the terminal error category (e.g. ``"config_or_auth:search"``)
    when the error is a configuration / authentication failure that no
    amount of parameter variation can fix, otherwise ``None``.

    These errors are structurally distinct from retryable failures:
    - ``SearchConfigError`` — missing/invalid provider configuration (no API key).
    - ``SearchAPIError`` with HTTP 401/403 — provider rejects credentials.
    - ``BrowserLaunchError`` — browser environment is broken and cannot be
      fixed by retrying.

    The returned category is scoped to the tool family (``:search`` /
    ``:browser``) so the circuit breaker only blocks tools of the same
    family, never unrelated network tooling.
    """
    if isinstance(e, SearchConfigError):
        return _CONFIG_OR_AUTH_FAMILY_SEARCH

    if isinstance(e, SearchAPIError):
        ctx = getattr(e, "context", None)
        status_code = getattr(ctx, "status_code", None)
        if isinstance(status_code, int) and status_code in (401, 403):
            return _CONFIG_OR_AUTH_FAMILY_SEARCH

    if isinstance(e, BrowserError):
        from myrm_agent_harness.toolkits.browser.exceptions import (
            BrowserLaunchError,
        )

        if isinstance(e, BrowserLaunchError):
            return _CONFIG_OR_AUTH_FAMILY_BROWSER

    return None


def make_error_msg(
    tool_name: str,
    tool_call_id: str,
    content: str,
    error_category: str | None = None,
    error_hint: str | None = None,
    loop_kind: str | None = None,
) -> ToolMessage:
    """Build a ToolMessage with error status."""
    kwargs: dict[str, Any] = {}
    if error_category:
        kwargs["error_category"] = error_category
    if error_hint:
        from myrm_agent_harness.agent.security.redact import redact_sensitive_text

        kwargs["error_hint"] = redact_sensitive_text(error_hint)
    if loop_kind:
        kwargs["loop_kind"] = loop_kind
    return ToolMessage(
        content=content,
        name=tool_name,
        tool_call_id=tool_call_id,
        status="error",
        additional_kwargs=kwargs,
    )


def format_tool_error(e: Exception, tool_name: str) -> str:
    """Format tool exception for LLM consumption.

    All output is passed through ``redact_sensitive_text`` (credential masking)
    and ``sanitize`` (structural framing token stripping) to prevent both
    credential leaks and prompt injection via exception messages.
    """
    from myrm_agent_harness.agent.security.detection.content_boundary import sanitize

    format_fn = getattr(e, "format_for_llm", None)
    if callable(format_fn):
        formatted = format_fn()
        raw = formatted if isinstance(formatted, str) else str(formatted)
        return sanitize(redact_sensitive_text(raw))
    content = f"{tool_name} execution failed: {e}"
    user_hint = getattr(e, "user_hint", None)
    if user_hint:
        content = f"{content}\n\nHint: {user_hint}"
    return sanitize(redact_sensitive_text(content))


def apply_validation_result(
    result: ToolMessage, validation: ValidationResult, tool_name: str
) -> ToolMessage:
    """Append validation warning to a ToolMessage."""
    severity = validation.severity
    prefix = " Warning" if severity == "error" else " Notice"
    warning_text = f"\n\n{prefix}: {validation.reason}"

    original = result.content
    new_content: str | list[object]
    if isinstance(original, list):
        new_content = [*original, {"type": "text", "text": warning_text}]
    else:
        new_content = f"{original}{warning_text}"

    additional_kwargs = dict(result.additional_kwargs)
    if severity == "error":
        additional_kwargs["error_category"] = ToolErrorCategory.CONTEXT_VALIDATION

    return ToolMessage(
        content=new_content,
        name=getattr(result, "name", tool_name),
        tool_call_id=result.tool_call_id,
        status="error" if severity == "error" else result.status,
        additional_kwargs=additional_kwargs,
    )


def check_trust_attenuation(tool_name: str) -> str | None:
    """Check if the tool is blocked by turn policy or trust attenuation."""
    from myrm_agent_harness.agent.middlewares._session_context import (
        get_turn_allowed_tool_names,
    )

    allowed = get_turn_allowed_tool_names()
    if allowed is not None:
        if tool_name in allowed:
            return None
        logger.warning("Turn tool policy blocked: %s", tool_name)
        if not allowed:
            return (
                f"Error: '{tool_name}' is restricted by the active turn tool policy.\n"
                "No tools are available under the current read-only analysis mode. "
                "Enable read-only tools such as file_read_tool or web_fetch_tool "
                "in the agent profile."
            )
        return (
            f"Error: '{tool_name}' is restricted by the active turn tool policy.\n"
            f"Available tools: {', '.join(sorted(allowed))}"
        )

    from myrm_agent_harness.agent.skill_agent.context import get_loaded_skills
    from myrm_agent_harness.agent.skills.runtime.attenuator import (
        READ_ONLY_TOOLS,
        attenuate_tools,
    )

    loaded = get_loaded_skills()
    if not loaded:
        return None

    result = attenuate_tools([tool_name], loaded)
    if tool_name in result.tool_names:
        return None

    logger.warning("Trust attenuation blocked: %s (%s)", tool_name, result.explanation)
    return (
        f"Error: '{tool_name}' is restricted due to trust attenuation.\n"
        f"Reason: {result.explanation}\n"
        f"Available tools: {', '.join(sorted(READ_ONLY_TOOLS))}"
    )


def extract_text_content(content: str | list[dict[str, str]]) -> str:
    """Extract plain text from ToolMessage content (str or list of dicts)."""
    if isinstance(content, str):
        return content
    return "".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )


# ---------------------------------------------------------------------------
# PII guard helpers
# ---------------------------------------------------------------------------


def check_tool_params_pii(tool_name: str, tool_args: dict[str, object]) -> str | None:
    """Check tool parameters for PII. Returns error message if blocked, None otherwise."""
    policy = get_privacy_policy()
    if not policy.enabled:
        return None

    from myrm_agent_harness.agent.security.detection.pii_classifier import (
        classify_tool_params,
    )
    from myrm_agent_harness.agent.security.guards.privacy_tracker import (
        get_privacy_tracker,
    )
    from myrm_agent_harness.agent.security.guards.taint_tracker import (
        TaintLabel,
        get_taint_tracker,
    )

    result = classify_tool_params(tool_name, tool_args, policy)
    if result.level == SensitivityLevel.S1:
        return None

    tracker = get_privacy_tracker()
    tracker.record(result.level, "tool_params", result.patterns)
    get_taint_tracker().record(TaintLabel.PII_SENSITIVE)
    record_decision(
        tool_name,
        "PII_DETECTED",
        f"level={result.level.value} patterns={','.join(result.patterns)}",
    )

    action = (
        policy.s3_action if result.level == SensitivityLevel.S3 else policy.s2_action
    )
    if action == PIIAction.BLOCK:
        return (
            f"Error: Tool call blocked due to PII detection ({result.level.value}).\n"
            f"Detected: {', '.join(result.patterns)}\n"
            f"Hint: Remove personal information from the tool parameters."
        )
    # PSEUDONYMIZE and REDACT for tool params are handled upstream
    # (before_model layer), so tool params reaching here are already
    # sanitized. No action needed.
    return None


def check_tool_result_pii(
    result: ToolMessage, result_text: str, tool_name: str
) -> tuple[ToolMessage, str]:
    """Check tool result for PII, optionally redacting. Returns (result, text)."""
    policy = get_privacy_policy()
    if not policy.enabled:
        return result, result_text

    from myrm_agent_harness.agent.security.detection.pii_classifier import (
        classify_tool_result,
    )
    from myrm_agent_harness.agent.security.detection.pii_redactor import redact_pii
    from myrm_agent_harness.agent.security.guards.privacy_tracker import (
        get_privacy_tracker,
    )
    from myrm_agent_harness.agent.security.guards.taint_tracker import (
        TaintLabel,
        get_taint_tracker,
    )

    classification = classify_tool_result(result_text, tool_name, policy)
    if classification.level == SensitivityLevel.S1:
        return result, result_text

    tracker = get_privacy_tracker()
    tracker.record(classification.level, "tool_result", classification.patterns)
    get_taint_tracker().record(TaintLabel.PII_SENSITIVE)
    record_decision(
        tool_name,
        "PII_DETECTED",
        f"level={classification.level.value} patterns={','.join(classification.patterns)}",
    )

    from myrm_agent_harness.agent.middlewares.security.security_guardrail_middleware import (
        _apply_pii_actions,
        _levels_to_process,
    )

    levels = _levels_to_process(classification.level, policy)
    processed = _apply_pii_actions(result_text, levels, policy, f"tool:{tool_name}")
    if processed is None:
        redacted_text, count = redact_pii(result_text)
        if count > 0:
            record_decision(tool_name, "PII_BLOCKED_REDACTED", f"count={count}")
        result = ToolMessage(
            content=redacted_text if count > 0 else "[BLOCKED]",
            name=tool_name,
            tool_call_id=result.tool_call_id,
            status=result.status,
        )
        result_text = result.content
    elif processed != result_text:
        result = ToolMessage(
            content=processed,
            name=tool_name,
            tool_call_id=result.tool_call_id,
            status=result.status,
        )
        result_text = processed

    return result, result_text


# ---------------------------------------------------------------------------
# Context poisoning + validation
# ---------------------------------------------------------------------------


def run_content_validation(result_text: str, tool_name: str) -> ValidationResult | None:
    """Run context poisoning detection. Returns validation result or None."""
    if not should_apply_validation(tool_name):
        return None
    validation = validate_tool_result(result_text, tool_name)
    if validation is not None and not validation.is_valid:
        return validation
    return None


# ---------------------------------------------------------------------------
# Hook failure helpers
# ---------------------------------------------------------------------------


def build_hook_failure_result(
    result: ToolMessage,
    post_hook_result: Any,
    tool_name: str,
    tool_call_id: str,
    post_result_text: str,
) -> ToolMessage:
    """Build error ToolMessage from hook validation failure."""
    error_details = []
    for hook_result in post_hook_result.results:
        if hook_result.blocked or not hook_result.success:
            if hook_result.output:
                error_details.append(hook_result.output)
            elif hook_result.reason:
                error_details.append(hook_result.reason)

    hook_error_msg = (
        "\n".join(error_details) if error_details else "Hook validation failed"
    )
    truncated_output = smart_truncate_output(post_result_text, max_lines=20)
    error_content = (
        f"[HOOK_VALIDATION_FAILED] Post-execution hook detected critical issues:\n\n"
        f"{hook_error_msg}\n\n"
        f"Original tool output:\n{truncated_output}"
    )

    record_decision(tool_name, "POST_HOOK_BLOCKED", post_hook_result.reason)
    logger.warning(
        "POST_TOOL_USE hook blocked: %s -- %s", tool_name, post_hook_result.reason
    )

    return ToolMessage(
        content=error_content,
        name=tool_name,
        tool_call_id=result.tool_call_id,
        status="error",
        additional_kwargs={"error_category": ToolErrorCategory.POST_HOOK_BLOCKED},
    )


async def emit_hook_failure_event(
    tool_name: str, post_hook_result: Any, agent_event_type: Any
) -> None:
    """Emit observability events for hook failures."""
    try:
        from myrm_agent_harness.observability.metrics.registry import (
            metrics_registry,
        )

        if metrics_registry and metrics_registry.enabled:
            metrics_registry.record_hook_failure(
                agent_id="base_agent", tool_name=tool_name, hook_event="post_tool_use"
            )
    except ImportError:
        pass

    try:
        from myrm_agent_harness.utils.runtime.progress_sink import (
            get_tool_progress_sink,
        )

        sink = get_tool_progress_sink()
        if sink:
            await sink.emit(
                {
                    "type": agent_event_type.TOOL_FAILURE.value,
                    "data": {
                        "tool_name": tool_name,
                        "hook_event": "post_tool_use",
                        "error": post_hook_result.reason or "Hook validation failed",
                        "reason": post_hook_result.reason,
                        "blocked": post_hook_result.blocked,
                    },
                }
            )
    except (ImportError, AttributeError):
        pass


async def emit_archive_restore_block_status(result_text: str, tool_name: str) -> None:
    """Emit status event when archive restore is blocked."""
    from myrm_agent_harness.agent.meta_tools.file_ops.core.archive_restore_guard import (
        parse_archive_restore_block_payload,
    )

    payload = parse_archive_restore_block_payload(result_text)
    if payload is None:
        return

    suggested_action = payload.get("suggested_action")
    items: list[dict[str, str]] = []
    if isinstance(suggested_action, str) and suggested_action:
        items.append({"text": suggested_action})

    try:
        from myrm_agent_harness.utils.event_utils import dispatch_custom_event

        await dispatch_custom_event(
            "agent_status",
            {
                "step_key": "archive_restore_blocked",
                "tool_name": tool_name,
                "status": "warning",
                "items": items,
                "archive_restore_block": payload,
            },
        )
    except Exception as exc:
        logger.debug("Failed to emit archive restore block status: %s", exc)
