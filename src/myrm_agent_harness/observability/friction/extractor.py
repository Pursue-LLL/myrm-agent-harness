"""Friction Extractor for deterministic zero-LLM task friction point mining.

[INPUT]
- myrm_agent_harness.observability.friction.types::(FrictionCategory, TaskFrictionEvent) (POS: 摩擦点基础契约)
- myrm_agent_harness.agent.errors.tool_error_category::ToolErrorCategory (POS: 工具错误分类枚举)

[OUTPUT]
- FrictionExtractor: Pure-rule extractor converting raw events, errors, or trace records into TaskFrictionEvent

[POS]
Zero-LLM extraction engine that maps execution anomalies and tool failures to structured TaskFrictionEvents.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from myrm_agent_harness.observability.friction.types import (
    FrictionCategory,
    TaskFrictionEvent,
)


class FrictionExtractor:
    """Extracts structured TaskFrictionEvents from raw event dictionaries or exceptions."""

    @staticmethod
    def classify_error_message(message: str) -> FrictionCategory:
        """Classify a raw error message string into a canonical FrictionCategory."""
        lower_msg = message.lower()
        if any(term in lower_msg for term in ("json", "parse", "format", "schema", "validation", "invalid argument")):
            return FrictionCategory.FORMAT_ERROR
        if any(term in lower_msg for term in ("timeout", "timed out", "deadline")):
            return FrictionCategory.TOOL_TIMEOUT
        if any(term in lower_msg for term in ("permission", "access denied", "forbidden", "blocked", "unauthorized")):
            return FrictionCategory.PERMISSION_DENIED
        if any(term in lower_msg for term in ("spill", "overflow", "too long", "truncated", "max token", "buffer full")):
            return FrictionCategory.SPILL_OVERFLOW
        if any(term in lower_msg for term in ("stuck", "loop", "cycle", "recursion", "max iterations")):
            return FrictionCategory.LOOP_STUCK
        return FrictionCategory.TOOL_FAULT

    @classmethod
    def from_tool_error(
        cls,
        *,
        session_id: str,
        tool_name: str,
        error_message: str,
        category: FrictionCategory | str | None = None,
        trace_id: str | None = None,
        fault_side: str = "MODEL",
        input_payload: object = None,
        retry_count: int = 0,
        metadata: dict[str, object] | None = None,
    ) -> TaskFrictionEvent:
        """Construct a TaskFrictionEvent from tool execution failure parameters."""
        resolved_category: FrictionCategory
        if isinstance(category, FrictionCategory):
            resolved_category = category
        elif isinstance(category, str):
            try:
                resolved_category = FrictionCategory(category)
            except ValueError:
                resolved_category = cls.classify_error_message(f"{category} {error_message}")
        else:
            resolved_category = cls.classify_error_message(error_message)

        str_input: str | None = None
        if input_payload is not None:
            if isinstance(input_payload, str):
                str_input = input_payload[:1000]
            else:
                try:
                    str_input = json.dumps(input_payload, default=str)[:1000]
                except Exception:
                    str_input = str(input_payload)[:1000]

        return TaskFrictionEvent(
            category=resolved_category,
            session_id=session_id,
            tool_name=tool_name,
            message=error_message,
            trace_id=trace_id,
            fault_side=fault_side,
            input_payload=str_input,
            retry_count=retry_count,
            metadata=metadata or {},
        )

    @classmethod
    def extract_from_event_stream(
        cls,
        events: Sequence[Mapping[str, object]],
        *,
        session_id: str,
        trace_id: str | None = None,
    ) -> list[TaskFrictionEvent]:
        """Scan an event log stream and extract all task friction events."""
        extracted: list[TaskFrictionEvent] = []

        for idx, event in enumerate(events):
            event_type = event.get("event_type") or event.get("type") or event.get("kind")
            if not isinstance(event_type, str):
                continue

            # Check for explicit tool failure / error events
            if event_type in ("tool_failure", "task_step_error", "agent_error"):
                tool_name = str(event.get("tool_name") or "system")
                error_msg = str(event.get("error") or event.get("message") or event.get("reason") or "Unknown error")
                cat_hint = event.get("error_category") or event.get("category")
                fault_side = str(event.get("fault_side") or "MODEL")

                friction = cls.from_tool_error(
                    session_id=session_id,
                    tool_name=tool_name,
                    error_message=error_msg,
                    category=str(cat_hint) if cat_hint else None,
                    trace_id=trace_id or (str(event.get("_trace_id")) if event.get("_trace_id") else None),
                    fault_side=fault_side,
                    input_payload=event.get("input_data") or event.get("input"),
                    metadata={"event_index": idx, "event_type": event_type},
                )
                extracted.append(friction)

        return extracted
