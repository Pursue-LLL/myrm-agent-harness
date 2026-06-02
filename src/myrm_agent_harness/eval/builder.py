"""TestCase Builder — extracts EvalCase from historical trajectories.

[INPUT]
- protocol::EvalCase, MultiTurnEvalCase (POS: Eval framework type system and AgentExecutor protocol.)

[OUTPUT]
- extract_case_from_trajectory: converts messages & tool calls to an EvalCase.

[POS]
Provides utility to seamlessly capture agent trajectories and transform them into reusable EvalCases.
"""

from __future__ import annotations

from typing import Any

from .protocols import EvalCase, MultiTurnEvalCase


def extract_case_from_trajectory(
    messages: list[dict[str, Any]],
    tools_called: list[str | dict[str, Any]],
    metadata: dict[str, str] | None = None,
) -> MultiTurnEvalCase:
    """Extract a multi-turn evaluation case from a conversation trajectory.

    Args:
        messages: A list of message dictionaries (e.g. [{"role": "user", "content": "..."}, ...])
        tools_called: A list of tool names or dictionaries that were called by the agent during the trajectory.
        metadata: Optional metadata to attach to the case (e.g., profile_id, chat_id).

    Returns:
        A MultiTurnEvalCase representing the conversation trajectory.
    """
    user_turns: list[str] = []

    # Collect all user inputs as sequential turns
    for msg in messages:
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
                # Handle multimodal or complex content block
                text_content = " ".join([str(part.get("text", "")) for part in content if part.get("type") == "text"])
                user_turns.append(text_content)
            elif isinstance(content, str):
                user_turns.append(content)

    # If no user messages, we can't create a valid case, but let's provide a fallback
    if not user_turns:
        user_turns = ["<empty trajectory>"]

    eval_cases: list[EvalCase] = []

    # All turns except the last one are purely conversational (no tools expected to simplify assertion)
    for i, turn_msg in enumerate(user_turns):
        is_last_turn = i == len(user_turns) - 1

        # Attach the expected tools to the final turn where we assert the outcome
        expected_tools = tools_called if is_last_turn else []
        require_all = bool(expected_tools)

        eval_case = EvalCase(
            message=turn_msg,
            expected_tools=expected_tools,
            require_all=require_all,
            metadata=metadata or {},
        )
        eval_cases.append(eval_case)

    return MultiTurnEvalCase(
        turns=eval_cases,
        metadata=metadata or {},
    )
