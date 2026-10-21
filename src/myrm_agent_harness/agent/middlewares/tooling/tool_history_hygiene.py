"""Tool history hygiene middleware.

Sanitizes outbound message history before LLM invocation:
1. Re-id duplicate tool_call_ids within a single AIMessage (deterministic ``id@n`` suffix).
2. Deduplicate ToolMessages with identical tool_call_ids (keep last).
3. Re-id duplicate tool_call_ids across AIMessages (deterministic ``id@n`` suffix).

Strict providers (Anthropic tool_use, some OpenAI-compatible gateways) reject
duplicate tool_call_ids anywhere in the request payload. This middleware runs
before dangling repair so duplicate IDs are not mistaken for missing results.

[INPUT]
- langchain.agents.middleware::ModelRequest (POS: LangChain agent middleware request envelope carrying outbound messages for LLM invocation.)

[OUTPUT]
- ModelRequest with sanitized messages
- sanitize_tool_history(): pure function for grace-call / oneshot retry paths
- tool_history_hygiene_middleware: AgentMiddleware singleton

[POS]
Tool history hygiene middleware. Runs BEFORE dangling_tool_call_middleware.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from copy import deepcopy

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import BaseMessage, ToolMessage

logger = logging.getLogger(__name__)

__all__ = [
    "ToolHistoryHygieneMiddleware",
    "sanitize_tool_history",
    "tool_history_hygiene_middleware",
]


def _has_tool_content(messages: list[BaseMessage]) -> bool:
    for msg in messages:
        if isinstance(msg, ToolMessage):
            return True
        if getattr(msg, "type", None) != "ai":
            continue
        if getattr(msg, "tool_calls", None):
            return True
        if getattr(msg, "invalid_tool_calls", None):
            return True
        additional_kwargs = getattr(msg, "additional_kwargs", None)
        if isinstance(additional_kwargs, dict) and additional_kwargs.get("tool_calls"):
            return True
    return False


def _dedup_tool_messages(messages: list[BaseMessage]) -> list[BaseMessage] | None:
    """Deduplicate ToolMessages with identical tool_call_ids (keep last)."""
    seen_ids: dict[str, int] = {}
    drop_indices: list[int] = []

    for i, msg in enumerate(messages):
        if not isinstance(msg, ToolMessage) or not msg.tool_call_id:
            continue
        tool_call_id = msg.tool_call_id
        if tool_call_id in seen_ids:
            old_idx = seen_ids[tool_call_id]
            logger.warning(
                "Duplicate tool_call_id detected: %s (indices: %d, %d). Keeping last.",
                tool_call_id,
                old_idx,
                i,
            )
            drop_indices.append(old_idx)
        seen_ids[tool_call_id] = i

    if not drop_indices:
        return None

    deduped = [msg for i, msg in enumerate(messages) if i not in drop_indices]
    logger.warning(
        "Deduplicated %d tool message(s) with duplicate IDs: %s",
        len(drop_indices),
        list(seen_ids.keys()),
    )
    return deduped


def _tool_call_entry_id(entry: object) -> str | None:
    if isinstance(entry, dict):
        tc_id = entry.get("id")
        return tc_id if isinstance(tc_id, str) and tc_id else None
    tc_id = getattr(entry, "id", None)
    return tc_id if isinstance(tc_id, str) and tc_id else None


def _reid_duplicate_tool_call_entries(
    entries: list[object],
) -> tuple[list[object], list[str], bool]:
    """Re-id duplicate tool_call ids within one serialized list (keep-first, suffix @n)."""
    counts: dict[str, int] = {}
    updated: list[object] = []
    final_ids: list[str] = []
    changed = False

    for entry in entries:
        tc_id = _tool_call_entry_id(entry)
        if not tc_id:
            updated.append(entry)
            continue

        counts[tc_id] = counts.get(tc_id, 0) + 1
        if counts[tc_id] == 1:
            final_ids.append(tc_id)
            updated.append(entry)
            continue

        new_id = f"{tc_id}@{counts[tc_id]}"
        final_ids.append(new_id)
        if isinstance(entry, dict):
            copy = dict(entry)
            copy["id"] = new_id
            updated.append(copy)
        else:
            updated.append(entry)
        changed = True

    return updated, final_ids, changed


def _apply_within_message_tool_call_reid(msg: BaseMessage) -> tuple[bool, list[str]]:
    """Re-id duplicate tool_call ids inside one AIMessage; return ordered final ids."""
    changed = False
    expected_ids: list[str] = []

    tool_calls = getattr(msg, "tool_calls", None) or []
    if tool_calls:
        updated, final_ids, list_changed = _reid_duplicate_tool_call_entries(tool_calls)
        if list_changed:
            msg.tool_calls = updated
            changed = True
        expected_ids.extend(final_ids)

    invalid_tool_calls = getattr(msg, "invalid_tool_calls", None) or []
    if invalid_tool_calls:
        updated, final_ids, list_changed = _reid_duplicate_tool_call_entries(invalid_tool_calls)
        if list_changed:
            msg.invalid_tool_calls = updated
            changed = True
        expected_ids.extend(final_ids)

    additional_kwargs = getattr(msg, "additional_kwargs", None)
    if isinstance(additional_kwargs, dict) and "tool_calls" in additional_kwargs:
        raw_calls = additional_kwargs.get("tool_calls")
        if isinstance(raw_calls, list) and raw_calls:
            updated, final_ids, list_changed = _reid_duplicate_tool_call_entries(raw_calls)
            if list_changed:
                updated_kwargs = dict(additional_kwargs)
                updated_kwargs["tool_calls"] = updated
                msg.additional_kwargs = updated_kwargs
                changed = True
            expected_ids.extend(final_ids)

    return changed, expected_ids


def _uniquify_within_ai_tool_call_ids(
    messages: list[BaseMessage],
) -> list[BaseMessage] | None:
    """Re-id duplicate tool_call_ids that occur within a single AIMessage."""
    working = deepcopy(messages)
    changed = False

    for i, msg in enumerate(working):
        if getattr(msg, "type", None) != "ai":
            continue

        msg_changed, expected_ids = _apply_within_message_tool_call_reid(msg)
        if not msg_changed:
            continue

        changed = True
        logger.warning(
            "Within-AIMessage duplicate tool_call_id re-id (%d slot(s))",
            len(expected_ids),
        )

        slot = 0
        for follower in working[i + 1 :]:
            if getattr(follower, "type", None) == "ai":
                break
            if not isinstance(follower, ToolMessage):
                continue
            if slot >= len(expected_ids):
                break
            expected_id = expected_ids[slot]
            if follower.tool_call_id != expected_id:
                follower.tool_call_id = expected_id
            slot += 1

    return working if changed else None


def _iter_ai_tool_call_ids_in_order(msg: BaseMessage) -> list[str]:
    """Collect tool_call ids from all AIMessage sources in serialization order."""
    ids: list[str] = []
    seen: set[str] = set()

    for tc in getattr(msg, "tool_calls", None) or []:
        tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
        if isinstance(tc_id, str) and tc_id and tc_id not in seen:
            ids.append(tc_id)
            seen.add(tc_id)

    for itc in getattr(msg, "invalid_tool_calls", None) or []:
        itc_id = itc.get("id") if isinstance(itc, dict) else getattr(itc, "id", None)
        if isinstance(itc_id, str) and itc_id and itc_id not in seen:
            ids.append(itc_id)
            seen.add(itc_id)

    if not ids:
        raw_tool_calls = (getattr(msg, "additional_kwargs", None) or {}).get("tool_calls") or []
        for raw_tc in raw_tool_calls:
            if not isinstance(raw_tc, dict):
                continue
            tc_id = raw_tc.get("id")
            if isinstance(tc_id, str) and tc_id and tc_id not in seen:
                ids.append(tc_id)
                seen.add(tc_id)

    return ids


def _has_cross_turn_duplicate_ids(messages: list[BaseMessage]) -> bool:
    seen: set[str] = set()
    for msg in messages:
        if getattr(msg, "type", None) != "ai":
            continue
        for tc_id in _iter_ai_tool_call_ids_in_order(msg):
            if tc_id in seen:
                return True
            seen.add(tc_id)
    return False


def _replace_id_in_dict_list(
    items: list[object],
    old_id: str,
    new_id: str,
) -> tuple[list[object], bool]:
    updated: list[object] = []
    replaced = False
    for item in items:
        if replaced:
            updated.append(item)
            continue
        if isinstance(item, dict) and item.get("id") == old_id:
            copy = dict(item)
            copy["id"] = new_id
            updated.append(copy)
            replaced = True
            continue
        updated.append(item)
    return updated, replaced


def _replace_first_tool_call_id(
    msg: BaseMessage,
    old_id: str,
    new_id: str,
) -> bool:
    """Replace the first occurrence of *old_id* across AIMessage tool_call sources."""
    changed = False

    tool_calls = getattr(msg, "tool_calls", None) or []
    updated_tool_calls, replaced = _replace_id_in_dict_list(tool_calls, old_id, new_id)
    if replaced:
        msg.tool_calls = updated_tool_calls
        changed = True

    invalid_tool_calls = getattr(msg, "invalid_tool_calls", None) or []
    updated_invalid, replaced = _replace_id_in_dict_list(invalid_tool_calls, old_id, new_id)
    if replaced:
        msg.invalid_tool_calls = updated_invalid
        changed = True

    additional_kwargs = getattr(msg, "additional_kwargs", None)
    if isinstance(additional_kwargs, dict) and "tool_calls" in additional_kwargs:
        raw_calls = additional_kwargs.get("tool_calls")
        if isinstance(raw_calls, list):
            updated_raw, replaced = _replace_id_in_dict_list(raw_calls, old_id, new_id)
            if replaced:
                updated_kwargs = dict(additional_kwargs)
                updated_kwargs["tool_calls"] = updated_raw
                msg.additional_kwargs = updated_kwargs
                changed = True

    return changed


def _uniquify_cross_turn_tool_call_ids(
    messages: list[BaseMessage],
) -> list[BaseMessage] | None:
    """Re-id later AIMessage occurrences of duplicate tool_call_ids."""
    if not _has_cross_turn_duplicate_ids(messages):
        return None

    working = deepcopy(messages)
    seen_global: set[str] = set()
    id_counters: dict[str, int] = {}
    pending_tool_remap: dict[str, str] = {}
    changed = False

    for msg in working:
        if getattr(msg, "type", None) == "ai":
            pending_tool_remap = {}
            for old_id in _iter_ai_tool_call_ids_in_order(msg):
                if old_id not in seen_global:
                    seen_global.add(old_id)
                    id_counters[old_id] = 1
                    continue
                next_count = id_counters.get(old_id, 1) + 1
                id_counters[old_id] = next_count
                new_id = f"{old_id}@{next_count}"
                if _replace_first_tool_call_id(msg, old_id, new_id):
                    pending_tool_remap[old_id] = new_id
                    changed = True
                    logger.warning(
                        "Cross-turn duplicate tool_call_id re-id: %s -> %s",
                        old_id,
                        new_id,
                    )
            continue

        if isinstance(msg, ToolMessage) and msg.tool_call_id:
            remapped = pending_tool_remap.get(msg.tool_call_id)
            if remapped:
                msg.tool_call_id = remapped
                changed = True

    return working if changed else None


def sanitize_tool_history(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Sanitize tool history for direct LLM invocations outside agent middleware."""
    if not _has_tool_content(messages):
        return messages

    changed = False
    current = list(messages)
    within_uniquified = _uniquify_within_ai_tool_call_ids(current)
    if within_uniquified is not None:
        current = within_uniquified
        changed = True

    deduped = _dedup_tool_messages(current)
    if deduped is not None:
        current = deduped
        changed = True

    uniquified = _uniquify_cross_turn_tool_call_ids(current)
    if uniquified is not None:
        current = uniquified
        changed = True

    return current if changed else messages


class ToolHistoryHygieneMiddleware(AgentMiddleware):  # type: ignore[type-arg]
    """Sanitize tool message history before LLM invocation."""

    name = "tool_history_hygiene_middleware"

    def _maybe_sanitize_request(self, request: ModelRequest) -> ModelRequest:
        original = list(request.messages)
        sanitized = sanitize_tool_history(original)
        if sanitized is original:
            return request
        return request.override(messages=sanitized)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return handler(self._maybe_sanitize_request(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(self._maybe_sanitize_request(request))


tool_history_hygiene_middleware = ToolHistoryHygieneMiddleware()
