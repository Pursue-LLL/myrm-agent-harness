"""Tests for commitment extraction engine — prompt building, parsing, validation."""

from __future__ import annotations

import json

import pytest

from myrm_agent_harness.toolkits.commitment.config import CommitmentConfig
from myrm_agent_harness.toolkits.commitment.extraction import (
    CommitmentExtractor,
    _detect_language,
    _parse_iso_to_ms,
    _parse_response,
    _truncate_head_tail,
    build_extraction_prompt,
    validate_candidates,
)
from myrm_agent_harness.toolkits.commitment.types import (
    CommitmentCandidate,
    CommitmentKind,
    CommitmentSensitivity,
)

NOW_ISO = "2026-05-19T14:00:00+00:00"
NOW_MS = 1779454800000
FUTURE_ISO = "2099-01-01T00:00:00+00:00"
FUTURE_MS = 4070908800000


def _make_messages(count: int = 5) -> list[dict[str, str]]:
    msgs = []
    for i in range(count):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append({"role": role, "content": f"Message {i}: " + "x" * 20})
    return msgs


class TestBuildExtractionPrompt:
    def test_basic_prompt_structure(self) -> None:
        msgs = _make_messages(3)
        prompt = build_extraction_prompt(msgs, now_iso=NOW_ISO, timezone="UTC")
        assert "Current time:" in prompt
        assert "Timezone: UTC" in prompt
        assert "## Conversation" in prompt
        assert "[USER]" in prompt

    def test_existing_pending_included(self) -> None:
        msgs = _make_messages(2)
        pending = [{"kind": "open_loop", "reason": "waiting", "dedupe_key": "wait:1"}]
        prompt = build_extraction_prompt(
            msgs, now_iso=NOW_ISO, existing_pending=pending
        )
        assert "Existing Pending Commitments" in prompt
        assert "wait:1" in prompt

    def test_chinese_language_instruction(self) -> None:
        prompt = build_extraction_prompt(
            _make_messages(2), now_iso=NOW_ISO, language="zh"
        )
        assert "中文" in prompt

    def test_english_has_no_chinese_instruction(self) -> None:
        prompt = build_extraction_prompt(
            _make_messages(2), now_iso=NOW_ISO, language="en"
        )
        assert "中文" not in prompt


class TestTruncateHeadTail:
    def test_short_messages_unchanged(self) -> None:
        msgs = [{"content": "a"}, {"content": "b"}]
        result = _truncate_head_tail(msgs, 1000)
        assert len(result) == 2

    def test_truncation_preserves_head(self) -> None:
        msgs = [{"content": "HEAD0"}, {"content": "HEAD1"}]
        for _i in range(20):
            msgs.append({"content": f"{'x' * 5000}"})
        result = _truncate_head_tail(msgs, 12000)
        assert result[0]["content"] == "HEAD0"
        assert result[1]["content"] == "HEAD1"
        assert len(result) < len(msgs)


class TestDetectLanguage:
    def test_english_text(self) -> None:
        msgs = [{"content": "Hello, how are you doing today?"}]
        assert _detect_language(msgs) == "en"

    def test_chinese_text(self) -> None:
        msgs = [{"content": "你好，今天天气怎么样？我想出去走走。"}]
        assert _detect_language(msgs) == "zh"

    def test_empty_messages(self) -> None:
        assert _detect_language([]) == "en"
        assert _detect_language([{"content": ""}]) == "en"

    def test_mixed_defaults_to_majority(self) -> None:
        msgs = [{"content": "Hello 你好世界今天很好 great"}]
        lang = _detect_language(msgs)
        assert lang in ("en", "zh")


class TestParseResponse:
    def test_valid_json(self) -> None:
        data = {
            "candidates": [
                {
                    "kind": "event_check_in",
                    "sensitivity": "personal",
                    "reason": "Interview on Friday",
                    "suggestedText": "Good luck!",
                    "dedupeKey": "interview:fri",
                    "confidence": 0.88,
                    "dueWindow": {
                        "earliest": FUTURE_ISO,
                        "latest": FUTURE_ISO,
                        "timezone": "UTC",
                    },
                }
            ]
        }
        result = _parse_response(json.dumps(data))
        assert len(result.candidates) == 1
        assert result.candidates[0].kind == CommitmentKind.EVENT_CHECK_IN
        assert result.candidates[0].confidence == 0.88

    def test_empty_candidates(self) -> None:
        result = _parse_response('{"candidates": []}')
        assert result.candidates == []

    def test_empty_string(self) -> None:
        result = _parse_response("")
        assert result.candidates == []

    def test_invalid_json(self) -> None:
        result = _parse_response("not json at all")
        assert result.candidates == []

    def test_json_in_markdown_block(self) -> None:
        raw = (
            '```json\n{"candidates": [{"kind": "open_loop", "sensitivity": "routine", "reason": "r", "suggestedText": "s", "dedupeKey": "d", "confidence": 0.7, "dueWindow": {"earliest": "'
            + FUTURE_ISO
            + '"}}]}\n```'
        )
        result = _parse_response(raw)
        assert len(result.candidates) == 1

    def test_max_3_candidates(self) -> None:
        candidates = []
        for i in range(6):
            candidates.append(
                {
                    "kind": "open_loop",
                    "sensitivity": "routine",
                    "reason": f"reason{i}",
                    "suggestedText": f"text{i}",
                    "dedupeKey": f"key{i}",
                    "confidence": 0.8,
                    "dueWindow": {"earliest": FUTURE_ISO},
                }
            )
        result = _parse_response(json.dumps({"candidates": candidates}))
        assert len(result.candidates) == 3

    def test_invalid_kind_skipped(self) -> None:
        data = {
            "candidates": [
                {
                    "kind": "invalid_kind",
                    "sensitivity": "routine",
                    "reason": "r",
                    "suggestedText": "s",
                    "dedupeKey": "d",
                    "confidence": 0.9,
                    "dueWindow": {"earliest": FUTURE_ISO},
                }
            ]
        }
        result = _parse_response(json.dumps(data))
        assert len(result.candidates) == 0

    def test_missing_earliest_skipped(self) -> None:
        data = {
            "candidates": [
                {
                    "kind": "open_loop",
                    "sensitivity": "routine",
                    "reason": "r",
                    "suggestedText": "s",
                    "dedupeKey": "d",
                    "confidence": 0.9,
                    "dueWindow": {},
                }
            ]
        }
        result = _parse_response(json.dumps(data))
        assert len(result.candidates) == 0


class TestValidateCandidates:
    @pytest.fixture()
    def config(self) -> CommitmentConfig:
        return CommitmentConfig(
            confidence_threshold=0.65,
            care_confidence_threshold=0.86,
        )

    def _make_candidate(
        self,
        kind: CommitmentKind = CommitmentKind.OPEN_LOOP,
        sensitivity: CommitmentSensitivity = CommitmentSensitivity.ROUTINE,
        confidence: float = 0.8,
        earliest: str = FUTURE_ISO,
    ) -> CommitmentCandidate:
        return CommitmentCandidate(
            kind=kind,
            sensitivity=sensitivity,
            reason="r",
            suggested_text="s",
            dedupe_key="d",
            confidence=confidence,
            due_window_earliest=earliest,
        )

    def test_passes_above_threshold(self, config: CommitmentConfig) -> None:
        c = self._make_candidate(confidence=0.70)
        result = validate_candidates([c], config, now_ms=NOW_MS, min_due_ms=NOW_MS)
        assert len(result) == 1

    def test_rejects_below_threshold(self, config: CommitmentConfig) -> None:
        c = self._make_candidate(confidence=0.50)
        result = validate_candidates([c], config, now_ms=NOW_MS, min_due_ms=NOW_MS)
        assert len(result) == 0

    def test_care_uses_higher_threshold(self, config: CommitmentConfig) -> None:
        c = self._make_candidate(
            kind=CommitmentKind.CARE_CHECK_IN,
            sensitivity=CommitmentSensitivity.CARE,
            confidence=0.80,
        )
        result = validate_candidates([c], config, now_ms=NOW_MS, min_due_ms=NOW_MS)
        assert len(result) == 0

    def test_care_passes_at_high_confidence(self, config: CommitmentConfig) -> None:
        c = self._make_candidate(
            kind=CommitmentKind.CARE_CHECK_IN,
            sensitivity=CommitmentSensitivity.CARE,
            confidence=0.90,
        )
        result = validate_candidates([c], config, now_ms=NOW_MS, min_due_ms=NOW_MS)
        assert len(result) == 1

    def test_past_due_rejected(self, config: CommitmentConfig) -> None:
        c = self._make_candidate(earliest="2020-01-01T00:00:00Z")
        result = validate_candidates([c], config, now_ms=NOW_MS, min_due_ms=NOW_MS)
        assert len(result) == 0

    def test_invalid_date_rejected(self, config: CommitmentConfig) -> None:
        c = self._make_candidate(earliest="not-a-date")
        result = validate_candidates([c], config, now_ms=NOW_MS, min_due_ms=NOW_MS)
        assert len(result) == 0


class TestParseIsoToMs:
    def test_valid_iso(self) -> None:
        ms = _parse_iso_to_ms("2026-05-19T14:00:00Z")
        assert ms is not None
        assert ms > 0

    def test_with_offset(self) -> None:
        ms = _parse_iso_to_ms("2026-05-19T14:00:00+08:00")
        assert ms is not None

    def test_invalid_returns_none(self) -> None:
        assert _parse_iso_to_ms("not a date") is None
        assert _parse_iso_to_ms("") is None


class TestCommitmentExtractor:
    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self) -> None:
        config = CommitmentConfig(enabled=False)
        extractor = CommitmentExtractor(config=config)

        async def mock_llm(system: str, user: str) -> str:
            pytest.fail("LLM should not be called when disabled")
            return ""

        result = await extractor.extract(_make_messages(5), mock_llm)
        assert result == []

    @pytest.mark.asyncio
    async def test_too_few_turns_returns_empty(self) -> None:
        config = CommitmentConfig(debounce_turns=5)
        extractor = CommitmentExtractor(config=config)

        async def mock_llm(system: str, user: str) -> str:
            pytest.fail("LLM should not be called for short conversations")
            return ""

        result = await extractor.extract(_make_messages(3), mock_llm)
        assert result == []

    @pytest.mark.asyncio
    async def test_llm_error_returns_empty(self) -> None:
        extractor = CommitmentExtractor()

        async def failing_llm(system: str, user: str) -> str:
            raise RuntimeError("LLM unavailable")

        result = await extractor.extract(_make_messages(5), failing_llm)
        assert result == []

    @pytest.mark.asyncio
    async def test_successful_extraction(self) -> None:
        extractor = CommitmentExtractor(
            config=CommitmentConfig(confidence_threshold=0.5)
        )

        response_data = {
            "candidates": [
                {
                    "kind": "open_loop",
                    "sensitivity": "routine",
                    "reason": "Waiting for reply",
                    "suggestedText": "Any update?",
                    "dedupeKey": "reply:001",
                    "confidence": 0.75,
                    "dueWindow": {
                        "earliest": "2099-01-01T00:00:00Z",
                        "latest": "2099-01-02T00:00:00Z",
                    },
                }
            ]
        }

        async def mock_llm(system: str, user: str) -> str:
            return json.dumps(response_data)

        result = await extractor.extract(_make_messages(5), mock_llm)
        assert len(result) == 1
        assert result[0].dedupe_key == "reply:001"
