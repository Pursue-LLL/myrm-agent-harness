"""Detector and selector for safe context compaction boundaries.

[INPUT]
- agent.context_management.tool_safe_compaction.tool_safe_compaction_types::CutPointEvaluation,
  CutPointSafetyKind (POS: Data contracts for safe cut-point selection, file manifests extraction, and atomic
  tool compaction.)

[OUTPUT]
- evaluate_cut_point: Inspect a candidate index for atomic tool safety.
- find_valid_cut_points: Enumerate all safe cut point indices across a message list.
- select_optimal_safe_cut_point: Snap a desired cut target to the closest safe boundary.

[POS]
Detects safe compaction boundaries ensuring tool_call and tool_result pairs remain intact.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .tool_safe_compaction_types import CutPointEvaluation, CutPointSafetyKind


def evaluate_cut_point(
    messages: Sequence[Mapping[str, str]],
    index: int,
) -> CutPointEvaluation:
    """Evaluate whether slicing at the specified index preserves atomic tool-call pairing.

    A cut point index k splits messages into:
    - prefix: messages[:k] (to be compacted/summarized)
    - suffix: messages[k:] (to be preserved in context)

    Cutting at a toolResult splits an assistant tool_call from its tool_result,
    which triggers 400 Bad Request errors from LLM providers.
    """
    total = len(messages)
    if index < 0 or index > total:
        return CutPointEvaluation(
            index=index,
            safety=CutPointSafetyKind.OUT_OF_BOUNDS,
            is_valid=False,
            rejection_reason=f"Index {index} is out of bounds for {total} messages",
        )

    if index == 0 or index == total:
        return CutPointEvaluation(
            index=index,
            safety=CutPointSafetyKind.SAFE_USER_TURN,
            is_valid=True,
        )

    target_msg = messages[index]
    target_role = target_msg.get("role", "")

    # Rejection 1: Suffix must NEVER begin with a toolResult message
    if target_role == "tool":
        return CutPointEvaluation(
            index=index,
            safety=CutPointSafetyKind.UNSAFE_TOOL_RESULT,
            is_valid=False,
            rejection_reason="Cut point falls on a tool result, separating it from assistant tool_call",
        )

    # Rejection 2: Check if prefix ends on an assistant message with an unresolved tool call
    prev_msg = messages[index - 1]
    prev_role = prev_msg.get("role", "")
    prev_content = prev_msg.get("content", "")
    prev_has_tool_call = (
        "tool_call" in prev_content.lower()
        or prev_msg.get("has_tool_calls") == "true"
        or "tool_calls" in prev_msg
    )

    if prev_role == "assistant" and prev_has_tool_call:
        if target_role == "tool":
            return CutPointEvaluation(
                index=index,
                safety=CutPointSafetyKind.UNSAFE_ORPHAN_CALL,
                is_valid=False,
                rejection_reason="Prefix ends with tool_call while tool_result is left in suffix",
            )

    # Rejection 3: Cutting at an assistant message that initiates tool calls is invalid
    if target_role == "assistant":
        target_content = target_msg.get("content", "")
        target_has_tool_call = (
            "tool_call" in target_content.lower()
            or target_msg.get("has_tool_calls") == "true"
            or "tool_calls" in target_msg
            or target_msg.get("tool_name") is not None
        )
        if target_has_tool_call:
            return CutPointEvaluation(
                index=index,
                safety=CutPointSafetyKind.UNSAFE_ORPHAN_CALL,
                is_valid=False,
                rejection_reason="Cut point falls on an assistant message initiating tool calls",
            )
        # If assistant immediately follows a user turn without prior tool execution, cutting here splits user and answer
        if prev_role == "user":
            return CutPointEvaluation(
                index=index,
                safety=CutPointSafetyKind.UNSAFE_ORPHAN_CALL,
                is_valid=False,
                rejection_reason="Cut point falls on an assistant turn directly responding to a user turn",
            )

    # Valid Check: Cutting at the beginning of a user turn is cleanest
    if target_role == "user":
        return CutPointEvaluation(
            index=index,
            safety=CutPointSafetyKind.SAFE_USER_TURN,
            is_valid=True,
        )

    # Valid Check: Cutting at an assistant turn that has finished previous tool executions
    if target_role == "assistant":
        return CutPointEvaluation(
            index=index,
            safety=CutPointSafetyKind.SAFE_ASSISTANT_CLEAN,
            is_valid=True,
        )

    return CutPointEvaluation(
        index=index,
        safety=CutPointSafetyKind.SAFE_USER_TURN,
        is_valid=True,
    )


def find_valid_cut_points(
    messages: Sequence[Mapping[str, str]],
) -> tuple[int, ...]:
    """Find all safe cut point indices where compaction will not break tool pairs."""
    valid_points: list[int] = []
    for idx in range(len(messages) + 1):
        evaluation = evaluate_cut_point(messages, idx)
        if evaluation.is_valid:
            valid_points.append(idx)
    return tuple(valid_points)


def select_optimal_safe_cut_point(
    messages: Sequence[Mapping[str, str]],
    desired_index: int,
) -> int:
    """Snap a desired compaction index to the nearest safe boundary.

    If equidistant, prefers snapping forward to capture full turn operations.
    """
    valid_points = find_valid_cut_points(messages)
    if not valid_points:
        return 0

    if desired_index in valid_points:
        return desired_index

    # Find the closest safe cut point
    best_point = valid_points[0]
    min_distance = abs(desired_index - best_point)

    for pt in valid_points:
        dist = abs(desired_index - pt)
        if dist < min_distance or (dist == min_distance and pt > best_point):
            min_distance = dist
            best_point = pt

    return best_point

