"""Dangling tool call repair middleware.

When a user interrupts (/stop) or a request times out, the message history
may contain AIMessages with tool_calls that have no corresponding ToolMessages.
This violates the LLM API contract (OpenAI/Anthropic require every tool_call
to have a matching ToolMessage), causing all subsequent LLM calls to fail.

This middleware scans the message history before each LLM invocation and
inserts synthetic error ToolMessages for any dangling tool_calls, restoring
a well-formed conversation that the LLM can process.

Covers the tool_call sources that langchain_openai serializes:
1. msg.tool_calls (standard parsed calls, including calls promoted by quarantine
   and args-recovery withholding so they receive an invalid-args ToolMessage)
2. msg.additional_kwargs["tool_calls"] (raw provider-level payloads)

Uses wrap_model_call (not before_model) to insert patches at the correct
position — immediately after the dangling AIMessage — rather than appending
to the end via the add_messages reducer.

[INPUT]
- langchain.agents.middleware (POS: Agent middleware framework — ModelRequest/ModelResponse pipeline)
- langchain_core.messages (POS: Core message types — AIMessage/ToolMessage/AnyMessage)
- tool_management.tool_layers (POS: Tool replay-safety registry)
- utils.json_args_repair (POS: Tool-call args repair and outbound invalid-call quarantine)

[OUTPUT]
- dangling_tool_call_middleware: Repair dangling tool_calls in message history before LLM ...
- repair_dangling_tool_calls: Patch dangling tool_calls for direct LLM invocations outside agent middleware.

[POS]
Dangling tool call repair middleware.
"""

import logging
from collections.abc import Awaitable, Callable
from copy import deepcopy
from json import JSONDecodeError, loads
from typing import cast

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AnyMessage, BaseMessage, ToolMessage

from myrm_agent_harness.agent.tool_management.tool_layers import get_tool_replay_safety
from myrm_agent_harness.agent.tool_management.types import ReplaySafety
from myrm_agent_harness.utils.json_args_repair import quarantine_invalid_tool_calls

logger = logging.getLogger(__name__)

_INTERRUPTED_MUTATION_CONTENT = (
    "[Tool call was interrupted before completion. "
    "Action has external side-effects; cancelled by safety policy to prevent duplicate side effects. "
    "Please adapt your plan to user instructions.]"
)
_INTERRUPTED_SAFE_CONTENT = (
    "[Tool execution was interrupted during recovery. Read-only action safely completed without side effects.]"
)
_INVALID_ARGS_CONTENT = "[Tool call could not be executed because its arguments were invalid.]"
_MAX_ERROR_DETAIL_LEN = 500


def _synthetic_content(
    tool_name: str = "unknown",
    error: str | None = None,
) -> tuple[str, str]:
    """Generate appropriate synthetic ToolMessage content and status.

    An ``error`` diagnosis means the call was quarantined as unrepairable —
    surface it with invalid-args semantics; otherwise the call was valid or
    repaired, and replay safety decides interrupted semantics.
    """
    if error:
        truncated = error[:_MAX_ERROR_DETAIL_LEN]
        return f"{_INVALID_ARGS_CONTENT[:-1]}: {truncated}]", "error"

    safety = get_tool_replay_safety(tool_name)
    if safety == ReplaySafety.SAFE:
        return _INTERRUPTED_SAFE_CONTENT, "success"
    return _INTERRUPTED_MUTATION_CONTENT, "error"


def _sanitize_tool_name(name: object) -> str:
    if isinstance(name, str) and name.strip():
        return name.strip()
    return "unknown"


def _coerce_tool_args_object(args: object) -> dict[str, object]:
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        stripped = args.strip()
        if len(stripped) >= 2 and stripped[0] in ("{", "["):
            try:
                parsed = loads(stripped)
                if isinstance(parsed, dict):
                    return {str(k): v for k, v in parsed.items()}
                if isinstance(parsed, list):
                    return {"items": parsed}
            except (ValueError, JSONDecodeError):
                return {}
    return {}


def _sanitize_tool_calls_list(
    raw_calls: object,
) -> tuple[list[dict[str, object]], bool]:
    if not isinstance(raw_calls, list):
        return [], bool(raw_calls)
    sanitized: list[dict[str, object]] = []
    changed = False
    for tc in raw_calls:
        if not isinstance(tc, dict):
            changed = True
            continue
        tc_id = tc.get("id")
        if not isinstance(tc_id, str) or not tc_id.strip():
            changed = True
            continue
        clean: dict[str, object] = dict(tc)
        clean["id"] = tc_id.strip()
        clean["name"] = _sanitize_tool_name(tc.get("name"))
        clean["args"] = _coerce_tool_args_object(tc.get("args"))
        if clean != tc:
            changed = True
        sanitized.append(clean)
    return sanitized, changed


def _sanitize_invalid_tool_calls_list(
    raw_calls: object,
) -> tuple[list[dict[str, object]], bool]:
    if not isinstance(raw_calls, list):
        return [], bool(raw_calls)
    sanitized: list[dict[str, object]] = []
    changed = False
    for tc in raw_calls:
        if not isinstance(tc, dict):
            changed = True
            continue
        tc_id = tc.get("id")
        if not isinstance(tc_id, str) or not tc_id.strip():
            changed = True
            continue
        clean: dict[str, object] = dict(tc)
        clean["id"] = tc_id.strip()
        clean["name"] = _sanitize_tool_name(tc.get("name"))
        error = tc.get("error")
        clean["error"] = error if isinstance(error, str) else None
        args = tc.get("args")
        clean["args"] = args if isinstance(args, str) else "{}"
        if clean != tc:
            changed = True
        sanitized.append(clean)
    return sanitized, changed


def _sanitize_raw_tool_calls_list(
    raw_calls: object,
) -> tuple[list[dict[str, object]], bool]:
    if not isinstance(raw_calls, list):
        return [], bool(raw_calls)
    sanitized: list[dict[str, object]] = []
    changed = False
    for tc in raw_calls:
        if not isinstance(tc, dict):
            changed = True
            continue
        tc_id = tc.get("id")
        if not isinstance(tc_id, str) or not tc_id.strip():
            changed = True
            continue

        function = tc.get("function")
        fn_dict = function if isinstance(function, dict) else {}
        fn_name = _sanitize_tool_name(tc.get("name") or fn_dict.get("name"))
        fn_arguments = fn_dict.get("arguments")
        if not isinstance(fn_arguments, str):
            fn_arguments = "{}"

        clean_function = dict(fn_dict)
        clean_function["name"] = fn_name
        clean_function["arguments"] = fn_arguments

        clean: dict[str, object] = dict(tc)
        clean["id"] = tc_id.strip()
        clean["type"] = clean.get("type") or "function"
        clean["function"] = clean_function
        if clean != tc:
            changed = True
        sanitized.append(clean)
    return sanitized, changed


def _sanitize_ai_message(msg: BaseMessage) -> bool:
    if getattr(msg, "type", None) != "ai":
        return False

    changed = False

    tool_calls, tc_changed = _sanitize_tool_calls_list(getattr(msg, "tool_calls", None))
    if tc_changed:
        changed = True
    if hasattr(msg, "tool_calls"):
        msg.tool_calls = tool_calls

    invalid_tool_calls, itc_changed = _sanitize_invalid_tool_calls_list(getattr(msg, "invalid_tool_calls", None))
    if itc_changed:
        changed = True
    if hasattr(msg, "invalid_tool_calls"):
        msg.invalid_tool_calls = invalid_tool_calls

    additional_kwargs = getattr(msg, "additional_kwargs", None)
    if isinstance(additional_kwargs, dict) and "tool_calls" in additional_kwargs:
        raw_calls = additional_kwargs.get("tool_calls")
        sanitized_raw_calls, raw_changed = _sanitize_raw_tool_calls_list(raw_calls)
        if raw_changed:
            changed = True
            updated_kwargs = dict(additional_kwargs)
            updated_kwargs["tool_calls"] = sanitized_raw_calls
            msg.additional_kwargs = updated_kwargs

    return changed


def _extract_tool_calls(msg: BaseMessage) -> list[tuple[str, str]]:
    """Extract all tool call (id, name) pairs from an AIMessage.

    Quarantine runs upstream in _build_patched_messages, so invalid calls
    are already upgraded into ``tool_calls`` (or dropped); extraction covers
    the remaining sources that langchain_openai/_convert_message_to_dict
    serializes into the API request:
    1. msg.tool_calls — standard parsed calls (includes quarantined upgrades)
    2. msg.additional_kwargs["tool_calls"] — raw provider payloads (fallback)
    """
    results: list[tuple[str, str]] = []
    seen_ids: set[str] = set()

    for tc in getattr(msg, "tool_calls", None) or []:
        tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
        if tc_id and tc_id not in seen_ids:
            name = tc.get("name", "unknown") if isinstance(tc, dict) else getattr(tc, "name", "unknown")
            results.append((tc_id, name))
            seen_ids.add(tc_id)

    if not results:
        raw_tool_calls = (getattr(msg, "additional_kwargs", None) or {}).get("tool_calls") or []
        for raw_tc in raw_tool_calls:
            if not isinstance(raw_tc, dict):
                continue
            tc_id = raw_tc.get("id")
            if not tc_id or tc_id in seen_ids:
                continue
            function = raw_tc.get("function")
            name = raw_tc.get("name") or (function.get("name") if isinstance(function, dict) else None) or "unknown"
            results.append((tc_id, name))
            seen_ids.add(tc_id)

    return results


def _promote_withheld_tool_calls(msg: BaseMessage) -> dict[str, str]:
    """Promote args-recovery-withheld calls into well-formed declarations.

    Streaming aggregation cannot carry ``invalid_tool_calls`` across chunk
    merges (LangChain ``add_ai_message_chunks`` drops the field), so the adapter
    records calls it refused to execute in
    ``additional_kwargs["tool_call_recovery"]`` with ``safe=False``. Those calls
    never became executable tool calls; this step re-declares each as an
    empty-args call (with a structured diagnosis keyed by id) so the dangling
    pipeline pairs it with an informative invalid-args ``ToolMessage`` and the
    model retries, instead of the turn silently losing its tool call.

    Idempotent: ids already present in ``tool_calls`` (already promoted or
    quarantined) are skipped, so repeated runs produce identical output.
    """
    if getattr(msg, "type", None) != "ai":
        return {}
    additional_kwargs = getattr(msg, "additional_kwargs", None)
    recovery_items = additional_kwargs.get("tool_call_recovery") if isinstance(additional_kwargs, dict) else None
    if not isinstance(recovery_items, list) or not recovery_items:
        return {}

    known_ids = {tc.get("id") for tc in (getattr(msg, "tool_calls", None) or []) if isinstance(tc, dict)}
    declarations: list[dict[str, object]] = []
    errors: dict[str, str] = {}
    for item in recovery_items:
        if not isinstance(item, dict) or item.get("safe") is not False:
            continue
        tc_id = item.get("tool_call_id")
        if not isinstance(tc_id, str) or not tc_id.strip() or tc_id in known_ids:
            continue
        tool_name = item.get("tool_name")
        name = tool_name if isinstance(tool_name, str) and tool_name.strip() else "unknown"
        declarations.append({"name": name, "args": {}, "id": tc_id, "type": "tool_call"})
        error = item.get("error")
        errors[tc_id] = (
            error if isinstance(error, str) and error else "Tool call arguments could not be safely parsed"
        )
        known_ids.add(tc_id)

    if declarations:
        msg.tool_calls = [*(getattr(msg, "tool_calls", None) or []), *declarations]  # type: ignore[attr-defined]
    return errors


def _build_patched_messages(messages: list[BaseMessage]) -> list[BaseMessage] | None:
    """Scan messages and insert synthetic ToolMessages for dangling tool_calls.

    For each AIMessage whose tool_calls (standard calls, withheld-recovery
    promotions, quarantined upgrades, additional_kwargs raw payloads) lack a
    corresponding ToolMessage, a synthetic error ToolMessage is inserted
    immediately after that AIMessage.

    Returns a new list with patches, or None if no patching is needed.
    """
    working = deepcopy(messages)
    changed = False
    ai_tool_calls_by_msg: dict[int, list[tuple[str, str]]] = {}
    invalid_errors_by_msg: dict[int, dict[str, str]] = {}
    referenced_ids: set[str] = set()

    for msg in working:
        if _sanitize_ai_message(msg):
            changed = True
        if getattr(msg, "type", None) != "ai":
            continue
        # Withheld calls (args refused by safe recovery) are re-declared first so
        # they receive an invalid-args ToolMessage instead of being lost.
        withheld_errors = _promote_withheld_tool_calls(msg)
        if withheld_errors:
            changed = True
        # Replay-poisoning isolation: upgrade invalid calls (malformed args)
        # into well-formed declarations before extraction, so malformed raw
        # text never reaches the provider. Unrepairable ones carry a
        # structured diagnosis keyed by call id.
        quarantine_errors, quarantine_changed = quarantine_invalid_tool_calls(msg)
        if quarantine_changed:
            changed = True
        tool_calls = _extract_tool_calls(msg)
        ai_tool_calls_by_msg[id(msg)] = tool_calls
        invalid_errors_by_msg[id(msg)] = {**withheld_errors, **quarantine_errors}
        for tc_id, _ in tool_calls:
            referenced_ids.add(tc_id)

    # Count per-id ToolMessage availability. A tool_call_id declared N times needs
    # N matching ToolMessages; anything beyond the available count is dangling.
    tool_count: dict[str, int] = {}
    for msg in working:
        if not isinstance(msg, ToolMessage) or not msg.tool_call_id:
            continue
        tool_count[msg.tool_call_id] = tool_count.get(msg.tool_call_id, 0) + 1

    patched: list[BaseMessage] = []
    consumed_so_far: dict[str, int] = {}
    patched_names: list[str] = []
    dropped_orphan_ids: list[str] = []

    for msg in working:
        if isinstance(msg, ToolMessage) and msg.tool_call_id not in referenced_ids:
            changed = True
            dropped_orphan_ids.append(msg.tool_call_id)
            continue

        patched.append(msg)
        if getattr(msg, "type", None) != "ai":
            continue
        tool_calls = ai_tool_calls_by_msg.get(id(msg), [])
        invalid_errors = invalid_errors_by_msg.get(id(msg), {})
        for tc_id, tool_name in tool_calls:
            consumed_so_far[tc_id] = consumed_so_far.get(tc_id, 0) + 1
            if consumed_so_far[tc_id] > tool_count.get(tc_id, 0):
                # Quarantined calls upgraded from invalid_tool_calls keep a
                # diagnosis here; they must retain invalid-args semantics so
                # the synthetic ToolMessage explains the failure instead of
                # replaying the malformed text.
                error = invalid_errors.get(tc_id)
                content, status = _synthetic_content(tool_name=tool_name, error=error)
                patched.append(
                    ToolMessage(
                        content=content,
                        tool_call_id=tc_id,
                        name=tool_name,
                        status=status,
                    )
                )
                patched_names.append(tool_name)
                changed = True

    if not changed:
        return None

    if patched_names:
        logger.warning(
            "Patched %d dangling tool call(s): %s",
            len(patched_names),
            ", ".join(patched_names),
        )
    if dropped_orphan_ids:
        logger.warning(
            "Dropped %d orphan tool message(s): %s",
            len(dropped_orphan_ids),
            ", ".join(dropped_orphan_ids),
        )
    return patched


def repair_dangling_tool_calls(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Patch dangling tool_calls for direct LLM invocations outside agent middleware."""
    patched = _build_patched_messages(messages)
    return patched if patched is not None else messages


class DanglingToolCallMiddleware(AgentMiddleware):
    """Repair dangling tool_calls in message history before LLM invocation.

    Scans request.messages for AIMessages whose tool_calls have no matching
    ToolMessage, and inserts synthetic error responses at the correct position.
    """

    name = "dangling_tool_call_middleware"

    def _maybe_patch_request(self, request: ModelRequest) -> ModelRequest:
        patched = _build_patched_messages(list(request.messages))
        if patched is not None:
            return request.override(messages=cast("list[AnyMessage]", patched))
        return request

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return handler(self._maybe_patch_request(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(self._maybe_patch_request(request))


dangling_tool_call_middleware = DanglingToolCallMiddleware()
