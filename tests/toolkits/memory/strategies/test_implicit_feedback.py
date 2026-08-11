"""Tests for implicit_feedback robust JSON parsing."""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.strategies.implicit_feedback import (
    _parse_plan_response,
)


class TestParsePlanResponse:
    def test_plain_array(self) -> None:
        proposals = _parse_plan_response('[{"action": "add", "content": "works at X"}]')
        assert len(proposals) == 1
        assert proposals[0].action == "add"
        assert proposals[0].content == "works at X"

    def test_prose_with_trailing_comma(self) -> None:
        raw = (
            'Plan:\n'
            '[{"action": "update", "content": "works at X", "memory_type": '
            '"semantic", "confidence": 0.9,},]\nThanks!'
        )
        proposals = _parse_plan_response(raw)
        assert len(proposals) == 1
        assert proposals[0].action == "update"
        assert proposals[0].memory_type == "semantic"

    def test_empty_array(self) -> None:
        assert _parse_plan_response("[]") == []

    def test_invalid_returns_empty(self) -> None:
        assert _parse_plan_response("no json here") == []

    def test_non_list_object_returns_empty(self) -> None:
        # detection-shaped object must not be misread as a plan array
        assert _parse_plan_response('{"has_contradiction": true, "signals": []}') == []
