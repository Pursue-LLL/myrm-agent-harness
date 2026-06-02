"""Tests for deep_pii_detector — LLM-based non-structured PII detection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from myrm_agent_harness.agent.security.detection.deep_pii_detector import (
    DeepPIIItem,
    _apply_replacements,
    _build_replacements,
    _build_user_prompt,
    _parse_detection_response,
    _parse_items,
    detect_deep_pii,
    pseudonymize_deep_pii,
)
from myrm_agent_harness.agent.security.detection.pseudonym_store import PseudonymStore


@pytest.fixture
def store(tmp_path: Path) -> PseudonymStore:
    s = PseudonymStore(str(tmp_path / "test_deep_pii.db"))
    yield s  # type: ignore[misc]
    s.close()


class TestParseDetectionResponse:
    """Test JSON response parsing from LLM."""

    def test_empty_response(self) -> None:
        result = _parse_detection_response("", 2)
        assert result == [[], []]

    def test_single_text_flat_list(self) -> None:
        resp = json.dumps([
            {"original_text": "penicillin allergy", "privacy_type": "Medical Health", "privacy_level": "PL3"}
        ])
        result = _parse_detection_response(resp, 1)
        assert len(result) == 1
        assert len(result[0]) == 1
        assert result[0][0].original_text == "penicillin allergy"
        assert result[0][0].privacy_type == "Medical Health"
        assert result[0][0].privacy_level == "PL3"

    def test_batch_nested_list(self) -> None:
        resp = json.dumps([
            [{"original_text": "depression", "privacy_type": "Medical Health", "privacy_level": "PL3"}],
            [],
            [{"original_text": "张三", "privacy_type": "Real Name", "privacy_level": "PL2"}],
        ])
        result = _parse_detection_response(resp, 3)
        assert len(result) == 3
        assert len(result[0]) == 1
        assert len(result[1]) == 0
        assert len(result[2]) == 1

    def test_think_tags_stripped(self) -> None:
        resp = "<think>analyzing...</think>" + json.dumps([
            [{"original_text": "asthma", "privacy_type": "Medical Health", "privacy_level": "PL3"}]
        ])
        result = _parse_detection_response(resp, 1)
        assert len(result[0]) == 1
        assert result[0][0].original_text == "asthma"

    @pytest.mark.parametrize("tag_name", [
        "think", "thinking", "thought", "antthinking", "reasoning", "REASONING_SCRATCHPAD",
    ])
    def test_all_thinking_tags_stripped(self, tag_name: str) -> None:
        inner = json.dumps([[
            {"original_text": "asthma", "privacy_type": "Medical Health", "privacy_level": "PL3"}
        ]])
        resp = f"<{tag_name}>internal reasoning</{tag_name}>{inner}"
        result = _parse_detection_response(resp, 1)
        assert len(result[0]) == 1
        assert result[0][0].original_text == "asthma"

    def test_invalid_json_returns_empty(self) -> None:
        result = _parse_detection_response("not valid json at all", 2)
        assert result == [[], []]

    def test_invalid_privacy_level_filtered(self) -> None:
        resp = json.dumps([
            {"original_text": "likes coffee", "privacy_type": "Preference", "privacy_level": "PL1"}
        ])
        result = _parse_detection_response(resp, 1)
        assert len(result[0]) == 0

    def test_fewer_results_than_expected(self) -> None:
        resp = json.dumps([[]])
        result = _parse_detection_response(resp, 3)
        assert len(result) == 3
        assert all(r == [] for r in result)


class TestParseItems:
    def test_valid_items(self) -> None:
        items = _parse_items([
            {"original_text": "心脏支架", "privacy_type": "Medical Health", "privacy_level": "PL3"},
            {"original_text": "301医院", "privacy_type": "Precise Location", "privacy_level": "PL3"},
        ])
        assert len(items) == 2

    def test_missing_fields_skipped(self) -> None:
        items = _parse_items([
            {"original_text": "test"},
            {"privacy_type": "test", "privacy_level": "PL2"},
            {},
        ])
        assert len(items) == 0

    def test_non_dict_skipped(self) -> None:
        items = _parse_items(["string", 42, None])
        assert len(items) == 0


class TestBuildUserPrompt:
    def test_single_text(self) -> None:
        prompt = _build_user_prompt(["Hello, I have diabetes"], real_name="张三")
        assert "张三" in prompt
        assert "TEXT #1" in prompt
        assert "diabetes" in prompt

    def test_batch_texts(self) -> None:
        prompt = _build_user_prompt(["text1", "text2", "text3"], real_name="")
        assert "TEXT #1" in prompt
        assert "TEXT #2" in prompt
        assert "TEXT #3" in prompt
        assert "(unknown)" in prompt


class TestReplacements:
    def test_build_replacements_sorted_by_length(self, store: PseudonymStore) -> None:
        items = [
            DeepPIIItem("ab", "T1", "PL2"),
            DeepPIIItem("abcde", "T2", "PL3"),
            DeepPIIItem("abc", "T3", "PL2"),
        ]
        replacements = _build_replacements(items, store)
        assert len(replacements) == 3
        assert len(replacements[0][0]) >= len(replacements[1][0]) >= len(replacements[2][0])

    def test_apply_replacements_longest_first(self) -> None:
        text = "I live at Zhongguancun Software Park Building 8"
        replacements = [
            ("Zhongguancun Software Park Building 8", "<ADDR_1>"),
            ("Zhongguancun", "<ADDR_2>"),
        ]
        result = _apply_replacements(text, replacements)
        assert result == "I live at <ADDR_1>"

    def test_apply_replacements_no_matches(self) -> None:
        text = "no PII here"
        result = _apply_replacements(text, [("xxx", "<X_1>")])
        assert result == "no PII here"


class TestDetectDeepPII:
    @pytest.mark.asyncio
    async def test_empty_input(self) -> None:
        result = await detect_deep_pii([], llm_func=_mock_llm_noop)
        assert result == []

    @pytest.mark.asyncio
    async def test_llm_failure_returns_empty(self) -> None:
        async def _fail(_s: str, _u: str) -> str:
            raise RuntimeError("LLM unavailable")

        result = await detect_deep_pii(["test text"], llm_func=_fail)
        assert result == [[]]

    @pytest.mark.asyncio
    async def test_successful_detection(self) -> None:
        detection_response = json.dumps([[
            {"original_text": "penicillin allergy", "privacy_type": "Medical Health", "privacy_level": "PL3"},
        ]])

        async def _mock(_s: str, _u: str) -> str:
            return detection_response

        result = await detect_deep_pii(["User has penicillin allergy"], llm_func=_mock)
        assert len(result) == 1
        assert len(result[0]) == 1
        assert result[0][0].privacy_type == "Medical Health"


class TestPseudonymizeDeepPII:
    @pytest.mark.asyncio
    async def test_empty_input(self, store: PseudonymStore) -> None:
        result = await pseudonymize_deep_pii([], store, llm_func=_mock_llm_noop)
        assert result == []

    @pytest.mark.asyncio
    async def test_no_pii_detected(self, store: PseudonymStore) -> None:
        async def _mock(_s: str, _u: str) -> str:
            return json.dumps([[]])

        result = await pseudonymize_deep_pii(["clean text"], store, llm_func=_mock)
        assert len(result) == 1
        assert result[0].pseudonymized_text == "clean text"
        assert result[0].items == []

    @pytest.mark.asyncio
    async def test_pii_replaced_with_pseudonyms(self, store: PseudonymStore) -> None:
        async def _mock(_s: str, _u: str) -> str:
            return json.dumps([[
                {"original_text": "penicillin allergy", "privacy_type": "Medical Health", "privacy_level": "PL3"},
                {"original_text": "Building 301", "privacy_type": "Precise Location", "privacy_level": "PL3"},
            ]])

        result = await pseudonymize_deep_pii(
            ["User has penicillin allergy, visited Building 301"],
            store,
            llm_func=_mock,
        )
        assert len(result) == 1
        text = result[0].pseudonymized_text
        assert "penicillin allergy" not in text
        assert "Building 301" not in text
        assert "<MEDICAL_HEALTH_1>" in text
        assert "<PRECISE_LOCATION_1>" in text

    @pytest.mark.asyncio
    async def test_idempotent_across_calls(self, store: PseudonymStore) -> None:
        async def _mock(_s: str, _u: str) -> str:
            return json.dumps([[
                {"original_text": "diabetes", "privacy_type": "Medical Health", "privacy_level": "PL3"},
            ]])

        r1 = await pseudonymize_deep_pii(["has diabetes"], store, llm_func=_mock)
        r2 = await pseudonymize_deep_pii(["has diabetes"], store, llm_func=_mock)
        assert r1[0].pseudonymized_text == r2[0].pseudonymized_text

    @pytest.mark.asyncio
    async def test_batch_texts(self, store: PseudonymStore) -> None:
        async def _mock(_s: str, _u: str) -> str:
            return json.dumps([
                [{"original_text": "asthma", "privacy_type": "Medical Health", "privacy_level": "PL3"}],
                [],
                [{"original_text": "John Doe", "privacy_type": "Real Name", "privacy_level": "PL2"}],
            ])

        result = await pseudonymize_deep_pii(
            ["has asthma", "clean text", "name is John Doe"],
            store,
            llm_func=_mock,
        )
        assert len(result) == 3
        assert "<MEDICAL_HEALTH_1>" in result[0].pseudonymized_text
        assert result[1].pseudonymized_text == "clean text"
        assert "<REAL_NAME_1>" in result[2].pseudonymized_text


class TestParseEdgeCases:
    """Edge cases for response parsing."""

    def test_malformed_json_fallback(self) -> None:
        resp = '[{"original_text": "diabetes", "privacy_type": "Medical Health", "privacy_level": "PL3",}]'
        result = _parse_detection_response(resp, 1)
        assert len(result) == 1
        try:
            import json_repair  # noqa: F401
            assert len(result[0]) == 1
            assert result[0][0].original_text == "diabetes"
        except ImportError:
            assert result[0] == []

    def test_non_list_top_level_returns_empty(self) -> None:
        resp = '{"original_text": "test", "privacy_type": "T", "privacy_level": "PL2"}'
        result = _parse_detection_response(resp, 1)
        assert result == [[]]

    def test_markdown_wrapped_json(self) -> None:
        inner = json.dumps([[
            {"original_text": "asthma", "privacy_type": "Medical Health", "privacy_level": "PL3"}
        ]])
        resp = f"```json\n{inner}\n```"
        result = _parse_detection_response(resp, 1)
        assert len(result[0]) == 1


async def _mock_llm_noop(_s: str, _u: str) -> str:
    return "[]"
