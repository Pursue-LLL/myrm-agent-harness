"""Protocol-safe context cut-point selector and tool pairing invariant guard.

[INPUT]
- langchain_core.messages::AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

[OUTPUT]
- CutPointAlignmentStrategy: Enum for cut point adjustment direction
- ToolPairingViolationType: Enum for tool-call invariant failure categories
- ToolPairingViolation: Structural record of a pairing defect
- ToolPairingValidationResult: Validation outcome and violations report
- is_permitted_cut_point: Whitelist predicate for safe cut points
- find_protocol_safe_cut_point: Shift candidate cut points to preserve atomic tool pairs
- validate_tool_pairing_invariants: O(N) validation verifying strict provider protocol invariants
- repair_tool_pairing_invariants: Deterministic repair eliminating orphan or unclosed tool calls

[POS]
Harness runtime context layer. Enforces tool call <-> tool result pairing invariants
preventing provider API 400 (Invalid Parameter) failures during context compaction.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)


class CutPointAlignmentStrategy(StrEnum):
    """Direction strategy to align cut point when landing mid-tool-group."""

    PULL_BACKWARD = "pull_backward"  # Pull entire tool group into retained tail
    PUSH_FORWARD = "push_forward"  # Push entire tool group into preceding history


class ToolPairingViolationType(StrEnum):
    """Categories of tool calling protocol violations."""

    ORPHAN_TOOL_RESULT = "orphan_tool_result"  # ToolMessage without preceding AIMessage tool_call
    UNCLOSED_TOOL_CALL = "unclosed_tool_call"  # AIMessage tool_call without following ToolMessage
    INTERLEAVED_MESSAGE = "interleaved_message"  # Foreign message inserted mid-tool-group


@dataclass(slots=True, frozen=True)
class ToolPairingViolation:
    """Record describing a specific tool protocol violation."""

    violation_type: ToolPairingViolationType
    message_index: int
    tool_call_id: str
    detail: str


@dataclass(slots=True, frozen=True)
class ToolPairingValidationResult:
    """Result of validating message sequence against tool pairing invariants."""

    is_valid: bool
    violations: list[ToolPairingViolation] = field(default_factory=list)


def _get_ai_tool_call_ids(msg: AIMessage) -> list[str]:
    """Extract ordered tool_call ids declared by an AIMessage."""
    ids: list[str] = []
    if not msg.tool_calls:
        return ids
    for tc in msg.tool_calls:
        if isinstance(tc, dict):
            tc_id = tc.get("id")
            if isinstance(tc_id, str) and tc_id:
                ids.append(tc_id)
    return ids


def is_permitted_cut_point(messages: Sequence[BaseMessage], cut_idx: int) -> bool:
    """Verify whether a candidate cut index falls on a permitted boundary.

    A cut point is permitted if:
    1. It is at the very beginning (0) or end (len(messages)).
    2. The message at cut_idx is a HumanMessage or SystemMessage.
    3. The message at cut_idx is an AIMessage that declared no tool_calls.
    4. It does not land on a ToolMessage.
    5. The preceding message (cut_idx - 1) is not an AIMessage with pending tool_calls.
    """
    n = len(messages)
    if cut_idx <= 0 or cut_idx >= n:
        return True

    curr = messages[cut_idx]
    prev = messages[cut_idx - 1]

    # Never split directly onto a ToolMessage
    if isinstance(curr, ToolMessage):
        return False

    # Never split right after an AIMessage that declared tool_calls (leaving tool results behind)
    if isinstance(prev, AIMessage) and bool(_get_ai_tool_call_ids(prev)):
        return False

    # Permitted cut points: HumanMessage, SystemMessage, or plain conversational AIMessage
    if isinstance(curr, (HumanMessage, SystemMessage)):
        return True
    if isinstance(curr, AIMessage) and not bool(_get_ai_tool_call_ids(curr)):
        return True

    # If curr is an AIMessage with tool_calls, it's safe to start a new tail from it
    return isinstance(curr, AIMessage) and bool(_get_ai_tool_call_ids(curr))


def find_protocol_safe_cut_point(
    messages: Sequence[BaseMessage],
    target_cut_idx: int,
    strategy: CutPointAlignmentStrategy = CutPointAlignmentStrategy.PULL_BACKWARD,
) -> int:
    """Calculate the nearest protocol-safe cut index preserving atomic tool pairs.

    If target_cut_idx lands inside a tool group (either on a ToolMessage or
    between an AIMessage and its ToolMessages), adjusts the cut point:
    - PULL_BACKWARD: shifts backwards to the AIMessage head, ensuring the entire
      tool call and its results are retained in the tail.
    - PUSH_FORWARD: shifts forwards past the last ToolMessage of the group,
      pushing the entire tool interaction into the preceding history.
    """
    n = len(messages)
    if n == 0 or target_cut_idx <= 0 or target_cut_idx >= n:
        return max(0, min(target_cut_idx, n))

    if is_permitted_cut_point(messages, target_cut_idx):
        return target_cut_idx

    curr = messages[target_cut_idx]

    # Case A: target lands on a ToolMessage
    if isinstance(curr, ToolMessage):
        # Walk backward to find the initiating AIMessage
        ai_idx = target_cut_idx - 1
        while ai_idx >= 0 and isinstance(messages[ai_idx], ToolMessage):
            ai_idx -= 1

        if ai_idx >= 0 and isinstance(messages[ai_idx], AIMessage):
            if strategy == CutPointAlignmentStrategy.PULL_BACKWARD:
                return ai_idx
            # PUSH_FORWARD: walk forward to find end of this tool group
            forward_idx = target_cut_idx
            while forward_idx < n and isinstance(messages[forward_idx], ToolMessage):
                forward_idx += 1
            return forward_idx

    # Case B: target lands right after an AIMessage with tool_calls
    prev = messages[target_cut_idx - 1]
    if isinstance(prev, AIMessage) and bool(_get_ai_tool_call_ids(prev)):
        if strategy == CutPointAlignmentStrategy.PULL_BACKWARD:
            return target_cut_idx - 1
        # PUSH_FORWARD: walk past all tool messages belonging to this AIMessage
        forward_idx = target_cut_idx
        while forward_idx < n and isinstance(messages[forward_idx], ToolMessage):
            forward_idx += 1
        return forward_idx

    return target_cut_idx


def validate_tool_pairing_invariants(messages: Sequence[BaseMessage]) -> ToolPairingValidationResult:
    """Validate message sequence against strict LLM provider tool calling invariants.

    Rules enforced:
    1. No orphan ToolMessages (every ToolMessage must match a pending tool_call_id
       declared by the immediately preceding AIMessage group).
    2. No unclosed tool calls (every tool_call_id declared in an AIMessage must be
       satisfied by an exact matching ToolMessage before any non-tool message appears).
    3. ToolMessages must directly follow their parent AIMessage without interleaving.
    """
    violations: list[ToolPairingViolation] = []
    idx = 0
    n = len(messages)

    while idx < n:
        msg = messages[idx]

        if isinstance(msg, ToolMessage):
            # An isolated ToolMessage with no active preceding AI tool call
            violations.append(
                ToolPairingViolation(
                    violation_type=ToolPairingViolationType.ORPHAN_TOOL_RESULT,
                    message_index=idx,
                    tool_call_id=getattr(msg, "tool_call_id", ""),
                    detail="ToolMessage found without active preceding AIMessage declaring its tool_call_id",
                )
            )
            idx += 1
            continue

        if isinstance(msg, AIMessage):
            expected_ids = _get_ai_tool_call_ids(msg)
            if not expected_ids:
                idx += 1
                continue

            expected_set = set(expected_ids)
            received_ids: set[str] = set()
            scan_idx = idx + 1

            while scan_idx < n and isinstance(messages[scan_idx], ToolMessage):
                t_msg = messages[scan_idx]
                t_id = getattr(t_msg, "tool_call_id", "")
                if t_id not in expected_set:
                    violations.append(
                        ToolPairingViolation(
                            violation_type=ToolPairingViolationType.ORPHAN_TOOL_RESULT,
                            message_index=scan_idx,
                            tool_call_id=t_id,
                            detail=f"ToolMessage ID '{t_id}' does not match any declared ID in AIMessage at index {idx}",
                        )
                    )
                else:
                    received_ids.add(t_id)
                scan_idx += 1

            # Check for unclosed tool calls
            missing = expected_set - received_ids
            for missing_id in missing:
                violations.append(
                    ToolPairingViolation(
                        violation_type=ToolPairingViolationType.UNCLOSED_TOOL_CALL,
                        message_index=idx,
                        tool_call_id=missing_id,
                        detail=f"AIMessage declared tool_call '{missing_id}' but received no matching ToolMessage",
                    )
                )

            idx = scan_idx
            continue

        idx += 1

    return ToolPairingValidationResult(is_valid=len(violations) == 0, violations=violations)


def repair_tool_pairing_invariants(messages: Sequence[BaseMessage]) -> list[BaseMessage]:
    """Deterministically repair message list to satisfy provider invariants.

    1. Drops orphan ToolMessages that have no preceding tool call.
    2. Drops or trims unclosed tool calls from AIMessages so they don't cause 400s.
    3. Guarantees the output passes validate_tool_pairing_invariants.
    """
    val = validate_tool_pairing_invariants(messages)
    if val.is_valid:
        return list(messages)

    orphan_indices = {v.message_index for v in val.violations if v.violation_type == ToolPairingViolationType.ORPHAN_TOOL_RESULT}
    missing_by_ai_idx: dict[int, set[str]] = {}
    for v in val.violations:
        if v.violation_type == ToolPairingViolationType.UNCLOSED_TOOL_CALL:
            missing_by_ai_idx.setdefault(v.message_index, set()).add(v.tool_call_id)

    repaired: list[BaseMessage] = []
    for idx, msg in enumerate(messages):
        if idx in orphan_indices and isinstance(msg, ToolMessage):
            logger.debug("[CutPointSelector] Dropped orphan ToolMessage at index %d", idx)
            continue

        if isinstance(msg, AIMessage) and idx in missing_by_ai_idx:
            missing_ids = missing_by_ai_idx[idx]
            # Keep only tool calls that actually received responses
            valid_tool_calls = [
                tc for tc in (msg.tool_calls or [])
                if isinstance(tc, dict) and tc.get("id") not in missing_ids
            ]
            if not valid_tool_calls:
                # No valid tool calls left; convert to plain conversational message or keep content
                cloned = msg.model_copy(deep=True)
                cloned.tool_calls = []
                if cloned.content or getattr(cloned, "text", ""):
                    repaired.append(cloned)
                logger.debug("[CutPointSelector] Cleaned unclosed tool calls from AIMessage at index %d", idx)
                continue

            cloned = msg.model_copy(deep=True)
            cloned.tool_calls = valid_tool_calls
            repaired.append(cloned)
            continue

        repaired.append(msg)

    return repaired
