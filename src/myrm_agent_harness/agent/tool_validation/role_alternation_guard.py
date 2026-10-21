"""Role alternation invariants verifier and interrupted sequence closing guard.

Guarantees strict compliance with modern LLM provider state machines:
(user -> assistant[tool_calls] -> tool[tool_call_id]* -> assistant).
Prevents fatal HTTP 400 Bad Request errors caused by illegal user insertions
or orphaned, unclosed tool calls during interruptions and partial exits.

[OUTPUT]
- RoleAlternationGuard: Invariant checker and sequence auto-closer.

[INPUT]
- __future__
- typing

[OUTPUT]
- RoleAlternationGuard

[POS]
Role alternation invariants verifier and interrupted sequence closing guard.
"""

from __future__ import annotations

from typing import cast

from myrm_agent_harness.agent.tool_validation.validation_types import (
    RoleAlternationViolationError,
    ToolCallResult,
)


class RoleAlternationGuard:
    """Enforces strict role alternation and closes open tool tails upon interruption."""

    @staticmethod
    def validate_conversation_invariants(
        messages: list[dict[str, object]] | tuple[dict[str, object], ...],
    ) -> None:
        """Verify that conversation history adheres strictly to tool alternation rules.

        Raises:
            RoleAlternationViolationError: If an invariant is violated.
        """
        pending_tool_call_ids: set[str] = set()

        for idx, msg in enumerate(messages):
            role = cast(str, msg.get("role", ""))

            # If there are pending tool calls, the next message MUST be a tool result
            if pending_tool_call_ids:
                if role != "tool":
                    raise RoleAlternationViolationError(
                        f"Message at index {idx} has role '{role}', but expected 'tool' "
                        f"to satisfy pending tool calls: {sorted(pending_tool_call_ids)}"
                    )
                tool_call_id = cast(str, msg.get("tool_call_id", ""))
                if tool_call_id in pending_tool_call_ids:
                    pending_tool_call_ids.remove(tool_call_id)
                continue

            # If an assistant message contains tool_calls, track them
            if role == "assistant":
                raw_tool_calls = msg.get("tool_calls")
                if isinstance(raw_tool_calls, (list, tuple)):
                    for tc in raw_tool_calls:
                        if isinstance(tc, dict):
                            call_id = cast(str, tc.get("id", ""))
                            if call_id:
                                pending_tool_call_ids.add(call_id)

            # A tool result cannot appear without an immediately preceding assistant tool_call
            elif role == "tool":
                raise RoleAlternationViolationError(
                    f"Orphaned 'tool' message at index {idx} with id '{msg.get('tool_call_id')}' "
                    "without corresponding active tool_calls."
                )

        if pending_tool_call_ids:
            raise RoleAlternationViolationError(
                f"Conversation ended with {len(pending_tool_call_ids)} open tool call(s) "
                f"lacking results: {sorted(pending_tool_call_ids)}"
            )

    @staticmethod
    def close_interrupted_tool_sequence(
        messages: list[dict[str, object]],
        abort_reason: str = "Execution interrupted by operator or watchdog",
    ) -> list[dict[str, object]]:
        """Synthesize missing role='tool' error results for any unclosed tool calls.

        Ensures that if a run terminates early (partial exit, timeout, cancel),
        the session persistence is not left with an illegal trailing tool_use.
        """
        if not messages:
            return messages

        # Scan backwards to find the last assistant message with tool calls
        target_assistant_idx: int | None = None
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "assistant" and messages[i].get("tool_calls"):
                target_assistant_idx = i
                break

        if target_assistant_idx is None:
            return messages

        assistant_msg = messages[target_assistant_idx]
        raw_tool_calls = assistant_msg.get("tool_calls")
        if not isinstance(raw_tool_calls, (list, tuple)):
            return messages

        expected_calls: dict[str, str] = {}
        for tc in raw_tool_calls:
            if isinstance(tc, dict):
                cid = cast(str, tc.get("id", ""))
                fn = tc.get("function")
                fn_name = ""
                if isinstance(fn, dict):
                    fn_name = cast(str, fn.get("name", ""))
                elif "name" in tc:
                    fn_name = cast(str, tc.get("name", ""))
                if cid:
                    expected_calls[cid] = fn_name

        # Identify which calls were already satisfied by existing tool messages
        satisfied_ids: set[str] = set()
        for msg in messages[target_assistant_idx + 1 :]:
            if msg.get("role") == "tool":
                satisfied_ids.add(cast(str, msg.get("tool_call_id", "")))

        # Append synthetic tool error responses for missing calls
        for cid, name in expected_calls.items():
            if cid not in satisfied_ids:
                synthetic = ToolCallResult(
                    tool_call_id=cid,
                    name=name,
                    content=f"Error: {abort_reason}",
                    role="tool",
                    is_error=True,
                )
                messages.append(
                    cast(dict[str, object], synthetic.to_message_dict())
                )

        return messages
