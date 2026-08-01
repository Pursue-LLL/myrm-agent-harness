"""Tests for eval/builder.py — trajectory extraction & skill eval case generation."""

from __future__ import annotations

from myrm_agent_harness.eval.builder import (
    build_skill_eval_cases,
    extract_case_from_trajectory,
)
from myrm_agent_harness.eval.protocols import EvalCase, MultiTurnEvalCase


class TestExtractCaseFromTrajectory:
    def test_basic_single_turn(self) -> None:
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        result = extract_case_from_trajectory(messages, tools_called=["search"])
        assert isinstance(result, MultiTurnEvalCase)
        assert len(result.turns) == 1
        assert result.turns[0].message == "Hello"
        assert result.turns[0].expected_tools == ["search"]
        assert result.turns[0].require_all is True

    def test_multi_turn(self) -> None:
        messages = [
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": "First answer"},
            {"role": "user", "content": "Follow up"},
            {"role": "assistant", "content": "Second answer"},
        ]
        result = extract_case_from_trajectory(messages, tools_called=["read_file"])
        assert len(result.turns) == 2
        assert result.turns[0].message == "First question"
        assert result.turns[0].expected_tools == []
        assert result.turns[0].require_all is False
        assert result.turns[1].message == "Follow up"
        assert result.turns[1].expected_tools == ["read_file"]

    def test_empty_trajectory(self) -> None:
        result = extract_case_from_trajectory([], tools_called=[])
        assert len(result.turns) == 1
        assert result.turns[0].message == "<empty trajectory>"

    def test_multipart_content(self) -> None:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Hello"},
                    {"type": "image", "url": "test.png"},
                    {"type": "text", "text": "world"},
                ],
            },
        ]
        result = extract_case_from_trajectory(messages, tools_called=[])
        assert result.turns[0].message == "Hello world"

    def test_metadata_propagated(self) -> None:
        messages = [{"role": "user", "content": "test"}]
        meta = {"chat_id": "c1", "profile_id": "default"}
        result = extract_case_from_trajectory(messages, tools_called=[], metadata=meta)
        assert result.metadata == meta
        assert result.turns[0].metadata == meta

    def test_no_user_messages(self) -> None:
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "assistant", "content": "Hello"},
        ]
        result = extract_case_from_trajectory(messages, tools_called=[])
        assert result.turns[0].message == "<empty trajectory>"

    def test_dict_tool_calls(self) -> None:
        messages = [{"role": "user", "content": "test"}]
        tools = [{"name": "search", "args": {"q": "test"}}]
        result = extract_case_from_trajectory(messages, tools_called=tools)
        assert result.turns[0].expected_tools == tools
        assert result.turns[0].require_all is True

    def test_empty_tools_no_require_all(self) -> None:
        messages = [{"role": "user", "content": "test"}]
        result = extract_case_from_trajectory(messages, tools_called=[])
        assert result.turns[0].require_all is False

    def test_non_string_content_skipped(self) -> None:
        messages = [
            {"role": "user", "content": 12345},
            {"role": "user", "content": "valid"},
        ]
        result = extract_case_from_trajectory(messages, tools_called=[])
        assert len(result.turns) == 1
        assert result.turns[0].message == "valid"


class TestBuildSkillEvalCases:
    def test_basic_generation(self) -> None:
        cases = build_skill_eval_cases(
            skill_content="def hello(): pass",
            skill_name="test_skill",
        )
        assert len(cases) == 1
        assert cases[0]["message"] == "Use skill: test_skill"
        assertions = cases[0]["sandbox_assertions"]
        assert any(a["type"] == "ast_valid" for a in assertions)

    def test_custom_trigger_message(self) -> None:
        cases = build_skill_eval_cases(
            skill_content="pass",
            skill_name="my_skill",
            trigger_message="Do something special",
        )
        assert cases[0]["message"] == "Do something special"

    def test_required_patterns(self) -> None:
        cases = build_skill_eval_cases(
            skill_content="import os",
            skill_name="os_skill",
            required_patterns=["import os", "def main"],
        )
        assertions = cases[0]["sandbox_assertions"]
        contains = [a for a in assertions if a["type"] == "code_contains"]
        assert len(contains) == 2
        assert contains[0]["target"] == "import os"
        assert contains[1]["target"] == "def main"

    def test_forbidden_patterns(self) -> None:
        cases = build_skill_eval_cases(
            skill_content="safe code",
            skill_name="safe_skill",
            forbidden_patterns=["eval(", "exec("],
        )
        assertions = cases[0]["sandbox_assertions"]
        not_contains = [a for a in assertions if a["type"] == "code_not_contains"]
        assert len(not_contains) == 2
        assert not_contains[0]["target"] == "eval("
        assert not_contains[1]["target"] == "exec("

    def test_combined_patterns(self) -> None:
        cases = build_skill_eval_cases(
            skill_content="import os\ndef main(): pass",
            skill_name="combined",
            required_patterns=["import os"],
            forbidden_patterns=["eval("],
        )
        assertions = cases[0]["sandbox_assertions"]
        assert len(assertions) == 3  # ast_valid + code_contains + code_not_contains

    def test_empty_patterns(self) -> None:
        cases = build_skill_eval_cases(
            skill_content="pass",
            skill_name="minimal",
            required_patterns=[],
            forbidden_patterns=[],
        )
        assertions = cases[0]["sandbox_assertions"]
        assert len(assertions) == 1  # only ast_valid

    def test_return_type(self) -> None:
        cases = build_skill_eval_cases(skill_content="pass", skill_name="t")
        assert isinstance(cases, list)
        assert isinstance(cases[0], dict)
        assert "message" in cases[0]
        assert "sandbox_assertions" in cases[0]
