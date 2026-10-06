"""Orphaned tool call provider transform healing (Pi Harness v2 Item 21).

Implements the Pi Harness v2 mid-tool-batch healing architecture:
1. Mid-Tool-Batch Promptability:
   When a session tree fork, navigate, or abrupt abort leaves the active tip
   sitting in the middle of a multi-tool batch (some tool_calls emitted by the
   assistant without corresponding tool results), downstream provider APIs
   (OpenAI, Anthropic, Gemini) will fail with 400 Bad Request (tool_call_id
   unmatched).
2. Request-Build-Time Transform:
   Instead of mutating persistent storage, this transform injects synthetic empty
   results at request build time so any branch tip remains immediately promptable.
3. Transparent System Message Handling:
   System messages arriving mid-batch are temporarily buffered and emitted immediately
   after the synthetic results, preventing order disruption or duplicate responses.
4. Dual Interface:
   Supports both canonical framework-neutral turns and LangChain BaseMessage lists.

[INPUT]
- messages: Sequence of CanonicalMessageTurn or BaseMessage
- placeholder_template: Custom placeholder text for synthetic results

[OUTPUT]
- CanonicalMessageRole
- CanonicalToolCallDescriptor
- CanonicalMessageTurn
- HealingMetrics
- OrphanedToolCallHealingTransform
- heal_orphaned_tool_calls_canonical
- heal_orphaned_tool_calls_langchain

[POS]
Harness runtime context layer. Sits between session tree/history projection and
provider request transport. Guarantees 100% promptable invariant across forks.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from langchain_core.messages import BaseMessage


DEFAULT_ORPHAN_PLACEHOLDER = "[No result provided: resolved by navigation / mid-batch healing]"


class CanonicalMessageRole(StrEnum):
    """Normalized role definitions for prompt messages."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(slots=True, frozen=True)
class CanonicalToolCallDescriptor:
    """Descriptor for a tool call emitted within an assistant turn."""

    tool_call_id: str
    tool_name: str
    arguments: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class CanonicalMessageTurn:
    """Framework-neutral message turn representation."""

    role: CanonicalMessageRole | str
    content: str = ""
    tool_calls: tuple[CanonicalToolCallDescriptor, ...] = field(default_factory=tuple)
    tool_call_id: str | None = None
    tool_name: str | None = None
    is_error: bool = False
    timestamp_ms: int = 0
    details: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class HealingMetrics:
    """Auditing metrics produced by transform healing."""

    total_messages_in: int
    total_messages_out: int
    synthesized_count: int
    held_system_count: int
    synthesized_call_ids: tuple[str, ...]


class OrphanedToolCallHealingTransform:
    """Transform engine inserting synthetic empty results for orphaned tool calls."""

    def __init__(
        self,
        default_placeholder: str = DEFAULT_ORPHAN_PLACEHOLDER,
    ) -> None:
        self._default_placeholder = default_placeholder

    def heal_canonical_turns(
        self,
        messages: Sequence[CanonicalMessageTurn],
        *,
        placeholder: str | None = None,
    ) -> tuple[list[CanonicalMessageTurn], HealingMetrics]:
        """Heal canonical message stream ensuring every tool call has a result."""
        active_placeholder = placeholder or self._default_placeholder
        result: list[CanonicalMessageTurn] = []
        pending_calls: list[CanonicalToolCallDescriptor] = []
        existing_result_ids: set[str] = set()
        held_system_messages: list[CanonicalMessageTurn] = []
        synthesized_ids: list[str] = []
        held_count = 0

        def close_pending() -> None:
            nonlocal pending_calls, existing_result_ids
            if pending_calls:
                for tc in pending_calls:
                    if tc.tool_call_id not in existing_result_ids:
                        synth_turn = CanonicalMessageTurn(
                            role=CanonicalMessageRole.TOOL,
                            content=active_placeholder,
                            tool_call_id=tc.tool_call_id,
                            tool_name=tc.tool_name,
                            is_error=True,
                            timestamp_ms=int(time.time() * 1000),
                            details={"synthetic_healing": "mid_batch_fork_navigate"},
                        )
                        result.append(synth_turn)
                        synthesized_ids.append(tc.tool_call_id)
                pending_calls = []
                existing_result_ids = set()
            if held_system_messages:
                result.extend(held_system_messages)
                held_system_messages.clear()

        for msg in messages:
            role = str(msg.role).lower()
            if role == CanonicalMessageRole.ASSISTANT.value:
                close_pending()
                if msg.tool_calls:
                    pending_calls = list(msg.tool_calls)
                    existing_result_ids = set()
                result.append(msg)
            elif role in (CanonicalMessageRole.TOOL.value, "toolresult"):
                if msg.tool_call_id:
                    existing_result_ids.add(msg.tool_call_id)
                result.append(msg)
            elif role == CanonicalMessageRole.SYSTEM.value:
                if pending_calls:
                    held_system_messages.append(msg)
                    held_count += 1
                else:
                    result.append(msg)
            elif role == CanonicalMessageRole.USER.value:
                close_pending()
                result.append(msg)
            else:
                result.append(msg)

        close_pending()

        metrics = HealingMetrics(
            total_messages_in=len(messages),
            total_messages_out=len(result),
            synthesized_count=len(synthesized_ids),
            held_system_count=held_count,
            synthesized_call_ids=tuple(synthesized_ids),
        )
        return result, metrics

    def heal_langchain_messages(
        self,
        messages: Sequence[BaseMessage],
        *,
        placeholder: str | None = None,
    ) -> tuple[list[BaseMessage], HealingMetrics]:
        """Heal LangChain BaseMessage stream ensuring every tool call has a ToolMessage."""
        from langchain_core.messages import ToolMessage

        active_placeholder = placeholder or self._default_placeholder
        result: list[BaseMessage] = []
        pending_calls: list[dict[str, str]] = []  # id and name
        existing_result_ids: set[str] = set()
        held_system_messages: list[BaseMessage] = []
        synthesized_ids: list[str] = []
        held_count = 0

        def close_pending() -> None:
            nonlocal pending_calls, existing_result_ids
            if pending_calls:
                for tc in pending_calls:
                    tc_id = tc["id"]
                    tc_name = tc.get("name", "unknown")
                    if tc_id not in existing_result_ids:
                        synth_msg = ToolMessage(
                            content=active_placeholder,
                            tool_call_id=tc_id,
                            name=tc_name,
                            status="error",
                        )
                        result.append(synth_msg)
                        synthesized_ids.append(tc_id)
                pending_calls = []
                existing_result_ids = set()
            if held_system_messages:
                result.extend(held_system_messages)
                held_system_messages.clear()

        for msg in messages:
            msg_type = getattr(msg, "type", "").lower()

            if msg_type == "ai":
                close_pending()
                raw_tcs = getattr(msg, "tool_calls", None) or []
                extracted: list[dict[str, str]] = []
                for tc in raw_tcs:
                    if isinstance(tc, dict) and "id" in tc and tc["id"]:
                        extracted.append({
                            "id": str(tc["id"]),
                            "name": str(tc.get("name", "unknown")),
                        })
                # Check additional_kwargs for provider-raw calls
                add_kwargs = getattr(msg, "additional_kwargs", None)
                if isinstance(add_kwargs, dict):
                    raw_p = add_kwargs.get("tool_calls")
                    if isinstance(raw_p, list):
                        for p in raw_p:
                            if isinstance(p, dict) and "id" in p:
                                p_id = str(p["id"])
                                if not any(x["id"] == p_id for x in extracted):
                                    func = p.get("function")
                                    p_name = (
                                        func.get("name", "unknown")
                                        if isinstance(func, dict)
                                        else "unknown"
                                    )
                                    extracted.append({"id": p_id, "name": str(p_name)})

                if extracted:
                    pending_calls = extracted
                    existing_result_ids = set()
                result.append(msg)

            elif msg_type == "tool":
                tc_id = getattr(msg, "tool_call_id", None)
                if tc_id:
                    existing_result_ids.add(str(tc_id))
                result.append(msg)

            elif msg_type == "system":
                if pending_calls:
                    held_system_messages.append(msg)
                    held_count += 1
                else:
                    result.append(msg)

            elif msg_type in ("human", "user"):
                close_pending()
                result.append(msg)

            else:
                result.append(msg)

        close_pending()

        metrics = HealingMetrics(
            total_messages_in=len(messages),
            total_messages_out=len(result),
            synthesized_count=len(synthesized_ids),
            held_system_count=held_count,
            synthesized_call_ids=tuple(synthesized_ids),
        )
        return result, metrics


def heal_orphaned_tool_calls_canonical(
    messages: Sequence[CanonicalMessageTurn],
    *,
    placeholder: str | None = None,
) -> tuple[list[CanonicalMessageTurn], HealingMetrics]:
    """Convenience helper for healing canonical message turns."""
    engine = OrphanedToolCallHealingTransform()
    return engine.heal_canonical_turns(messages, placeholder=placeholder)


def heal_orphaned_tool_calls_langchain(
    messages: Sequence[BaseMessage],
    *,
    placeholder: str | None = None,
) -> tuple[list[BaseMessage], HealingMetrics]:
    """Convenience helper for healing LangChain BaseMessage sequences."""
    engine = OrphanedToolCallHealingTransform()
    return engine.heal_langchain_messages(messages, placeholder=placeholder)
