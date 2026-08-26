"""Tests for eval case loader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from myrm_agent_harness.eval.loader import load_cases, load_multi_turn_cases


class TestLoadCases:
    """Tests for single-turn case loading."""

    def test_basic_load(self, tmp_path: Path) -> None:
        data = [
            {
                "message": "Search for Python",
                "expected_tools": ["web_search"],
                "require_all": False,
                "metadata": {"category": "search"},
            },
            {
                "message": "Hello",
            },
        ]
        path = tmp_path / "cases.json"
        path.write_text(json.dumps(data))

        cases = load_cases(path)
        assert len(cases) == 2

        assert cases[0].message == "Search for Python"
        assert cases[0].expected_tools == ["web_search"]
        assert cases[0].require_all is False
        assert cases[0].metadata == {"category": "search"}

        assert cases[1].message == "Hello"
        assert cases[1].expected_tools == []

    def test_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError, match="not found"):
            load_cases("/nonexistent/path.json")

    def test_invalid_json_root(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text('{"not": "an array"}')

        with pytest.raises(ValueError, match="EvalCase requires non-empty 'message'"):
            load_cases(path)

    def test_missing_message(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text('[{"expected_tools": ["web_search"]}]')

        with pytest.raises(ValueError, match="message"):
            load_cases(path)

    def test_empty_message(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text('[{"message": ""}]')

        with pytest.raises(ValueError, match="message"):
            load_cases(path)

    def test_invalid_expected_tools_type(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text('[{"message": "test", "expected_tools": "not_a_list"}]')

        with pytest.raises(TypeError, match="expected_tools"):
            load_cases(path)

    def test_require_all_true(self, tmp_path: Path) -> None:
        path = tmp_path / "cases.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "message": "Do both",
                        "expected_tools": ["tool_a", "tool_b"],
                        "require_all": True,
                    }
                ]
            )
        )

        cases = load_cases(path)
        assert cases[0].require_all is True

    def test_string_path(self, tmp_path: Path) -> None:
        path = tmp_path / "cases.json"
        path.write_text(json.dumps([{"message": "test"}]))

        cases = load_cases(str(path))
        assert len(cases) == 1

    def test_load_cases_with_compaction_assertions(self, tmp_path: Path) -> None:
        data = [
            {
                "message": "Continue processing financial report",
                "expected_tools": ["read_file"],
                "compaction_assertions": [
                    {
                        "expected_constraints": ["USD currency", "no estimation"],
                        "forbidden_claims": ["task finished"],
                        "required_artifacts": ["reports/fin.csv"],
                        "expected_tools": ["read_file"],
                        "min_fidelity_score": 0.85,
                    }
                ],
            }
        ]
        path = tmp_path / "compaction_cases.json"
        path.write_text(json.dumps(data))

        cases = load_cases(path)
        assert len(cases) == 1
        assert len(cases[0].compaction_assertions) == 1
        comp = cases[0].compaction_assertions[0]
        assert comp.expected_constraints == ("USD currency", "no estimation")
        assert comp.forbidden_claims == ("task finished",)
        assert comp.required_artifacts == ("reports/fin.csv",)
        assert comp.expected_tools == ("read_file",)
        assert comp.min_fidelity_score == 0.85


class TestLoadMultiTurnCases:
    """Tests for multi-turn case loading."""

    def test_basic_multi_turn(self, tmp_path: Path) -> None:
        data = [
            {
                "turns": [
                    {"message": "Hello"},
                    {"message": "Search X", "expected_tools": ["web_search"]},
                ],
                "metadata": {"scenario": "greeting_search"},
            }
        ]
        path = tmp_path / "mt.json"
        path.write_text(json.dumps(data))

        cases = load_multi_turn_cases(path)
        assert len(cases) == 1
        assert len(cases[0].turns) == 2
        assert cases[0].turns[1].expected_tools == ["web_search"]
        assert cases[0].metadata == {"scenario": "greeting_search"}

    def test_multi_turn_with_on_turn_fail(self, tmp_path: Path) -> None:
        data = [
            {
                "turns": [
                    {"message": "t1"},
                    {"message": "t2", "expected_tools": ["web_search"]},
                ],
                "on_turn_fail": "abort",
                "metadata": {"scenario": "early_stop"},
            }
        ]
        path = tmp_path / "mt_abort.json"
        path.write_text(json.dumps(data))

        cases = load_multi_turn_cases(path)
        assert len(cases) == 1
        assert cases[0].on_turn_fail == "abort"

    def test_multi_turn_invalid_on_turn_fail(self, tmp_path: Path) -> None:
        data = [{"turns": [{"message": "t1"}], "on_turn_fail": "invalid"}]
        path = tmp_path / "mt_bad.json"
        path.write_text(json.dumps(data))

        with pytest.raises(ValueError, match="on_turn_fail"):
            load_multi_turn_cases(path)

    def test_multi_turn_default_on_turn_fail(self, tmp_path: Path) -> None:
        data = [{"turns": [{"message": "t1"}]}]
        path = tmp_path / "mt_default.json"
        path.write_text(json.dumps(data))

        cases = load_multi_turn_cases(path)
        assert cases[0].on_turn_fail == "continue"

    def test_empty_turns(self, tmp_path: Path) -> None:
        path = tmp_path / "mt.json"
        path.write_text(json.dumps([{"turns": []}]))

        cases = load_multi_turn_cases(path)
        assert len(cases) == 1
        assert len(cases[0].turns) == 0

    def test_mixed_single_and_multi_turn_cases(self, tmp_path: Path) -> None:
        """Test auto-upgrading single-turn cases into MultiTurnEvalCase format."""
        data = [
            {
                "message": "Single turn test",
                "semantic_assertions": [
                    {"type": "llm_judge", "expected": "friendly", "threshold": 0.9}
                ],
            },
            {"turns": [{"message": "Multi turn test"}]},
        ]
        path = tmp_path / "mixed.json"
        path.write_text(json.dumps(data))

        cases = load_multi_turn_cases(path)
        assert len(cases) == 2

        # First case was single-turn, upgraded to multi-turn with 1 turn
        assert len(cases[0].turns) == 1
        assert cases[0].turns[0].message == "Single turn test"
        assert len(cases[0].turns[0].semantic_assertions) == 1
        assert cases[0].turns[0].semantic_assertions[0].type == "llm_judge"
        assert cases[0].turns[0].semantic_assertions[0].threshold == 0.9

        # Second case was already multi-turn
        assert len(cases[1].turns) == 1
        assert cases[1].turns[0].message == "Multi turn test"


class TestLoaderEdgeCases:
    """Edge cases for the loader."""

    def test_utf8_chinese_message(self, tmp_path: Path) -> None:
        data = [{"message": "帮我搜索 Python 教程", "expected_tools": ["web_search"]}]
        path = tmp_path / "cn.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        cases = load_cases(path)
        assert cases[0].message == "帮我搜索 Python 教程"

    def test_many_cases(self, tmp_path: Path) -> None:
        data = [{"message": f"msg-{i}"} for i in range(200)]
        path = tmp_path / "big.json"
        path.write_text(json.dumps(data))

        cases = load_cases(path)
        assert len(cases) == 200

    def test_invalid_json_syntax(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{not valid json}")

        with pytest.raises(json.JSONDecodeError):
            load_cases(path)

    def test_expected_tools_non_string_elements(self, tmp_path: Path) -> None:
        """Non-string elements in expected_tools are coerced to strings."""
        data = [{"message": "test", "expected_tools": [123, True]}]
        path = tmp_path / "coerce.json"
        path.write_text(json.dumps(data))

        cases = load_cases(path)
        assert cases[0].expected_tools == ["123", "True"]

    def test_multi_turn_missing_turns_key(self, tmp_path: Path) -> None:
        path = tmp_path / "mt.json"
        path.write_text(json.dumps([{"metadata": {"x": "y"}}]))

        with pytest.raises(ValueError):
            load_multi_turn_cases(path)

    def test_metadata_values_coerced_to_string(self, tmp_path: Path) -> None:
        data = [{"message": "test", "metadata": {"count": 42, "flag": True}}]
        path = tmp_path / "meta.json"
        path.write_text(json.dumps(data))

        cases = load_cases(path)
        assert cases[0].metadata == {"count": "42", "flag": "True"}

    def test_load_cases_with_retrieval_and_post_episode_and_canary(
        self, tmp_path: Path
    ) -> None:
        data = [
            {
                "message": "Find doc and verify",
                "retrieval_assertions": [
                    {
                        "type": "retrieval_quality",
                        "expected_spans": ["Span A", "Span B"],
                        "expected_doc_ids": ["doc-1"],
                        "min_recall": 0.8,
                        "top_k": 3,
                    }
                ],
                "post_episode_assertions": [
                    {
                        "assertion_id": "post-1",
                        "assertion_type": "sandbox_state",
                        "command": "pytest",
                    }
                ],
                "canary_protected": True,
                "canary_token": "token-12345",
            }
        ]
        path = tmp_path / "full_cases.json"
        path.write_text(json.dumps(data))

        cases = load_cases(path)
        assert len(cases) == 1
        c = cases[0]
        assert len(c.retrieval_assertions) == 1
        assert c.retrieval_assertions[0].expected_spans == ("Span A", "Span B")
        assert len(c.post_episode_assertions) == 1
        assert c.post_episode_assertions[0].command == "pytest"
        assert c.canary_protected is True
        assert c.canary_token == "token-12345"
