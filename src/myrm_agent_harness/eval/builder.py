"""TestCase Builder — extracts EvalCase from historical trajectories.

[INPUT]
- protocol::EvalCase, MultiTurnEvalCase (POS: Eval framework type system and AgentExecutor protocol.)

[OUTPUT]
- extract_case_from_trajectory: converts messages & tool calls to a MultiTurnEvalCase.
- build_skill_eval_cases: generates lightweight EvalCase dicts suitable for SkillRecord binding.

[POS]
Provides utilities to capture agent trajectories and transform them into reusable
EvalCases, and to build lightweight regression test cases for skill evolution.
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

    for msg in messages:
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
                text_content = " ".join([str(part.get("text", "")) for part in content if part.get("type") == "text"])
                user_turns.append(text_content)
            elif isinstance(content, str):
                user_turns.append(content)

    if not user_turns:
        user_turns = ["<empty trajectory>"]

    eval_cases: list[EvalCase] = []

    for i, turn_msg in enumerate(user_turns):
        is_last_turn = i == len(user_turns) - 1
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


def build_skill_eval_cases(
    skill_content: str,
    skill_name: str,
    trigger_message: str | None = None,
    required_patterns: list[str] | None = None,
    forbidden_patterns: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Build lightweight EvalCase dicts suitable for SkillRecord.eval_cases binding.

    Generates objective sandbox_assertions that can be checked without agent
    execution — purely static code-level checks.

    Args:
        skill_content: The skill's full content (used to extract invariant patterns).
        skill_name: The skill name (used as default trigger message).
        trigger_message: An example user message that should trigger this skill.
        required_patterns: Strings that must appear in any valid variant of this skill.
        forbidden_patterns: Strings that must NOT appear in any valid variant.

    Returns:
        A list of EvalCase dicts ready for SkillRecord.eval_cases.
    """
    cases: list[dict[str, Any]] = []
    assertions: list[dict[str, str]] = []

    assertions.append({"type": "ast_valid", "target": ""})

    if required_patterns:
        for pattern in required_patterns:
            assertions.append({"type": "code_contains", "target": pattern})

    if forbidden_patterns:
        for pattern in forbidden_patterns:
            assertions.append({"type": "code_not_contains", "target": pattern})

    cases.append(
        {
            "message": trigger_message or f"Use skill: {skill_name}",
            "sandbox_assertions": assertions,
        }
    )

    return cases
