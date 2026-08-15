"""Tests for context pipeline helper functions.

Covers request metadata parsing, tool schema canonicalization, cache usage
feedback resolution, and compression intent extraction — keeping the helper
layer fully exercised without middleware orchestration.
"""

from __future__ import annotations

from typing import ClassVar

import pytest
from langchain.agents.middleware import ModelRequest
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from myrm_agent_harness.agent.context_management.infra.schemas import (
    CacheUsageFeedback,
    CompressionIntent,
)
from myrm_agent_harness.agent.middlewares.context_pipeline.context_pipeline_helpers import (
    _canonical_json,
    _to_json_safe,
    estimate_request_context_tokens,
    extract_compression_intent,
    extract_tool_names_and_schemas,
    resolve_cache_usage_feedback,
    resolve_context_budget_metadata,
)


def _make_request(*, tools: list[object] | None = None) -> ModelRequest:
    return ModelRequest(
        messages=[HumanMessage(content="hi")], model=object(), tools=tools
    )


class _ArgsSchema(BaseModel):
    path: str


class _ToolWithSchema:
    name = "tool_a"
    description = "tool a description"
    args_schema = _ArgsSchema


class _ToolWithCallSchema:
    name = "tool_b"
    description = "tool b description"
    tool_call_schema: ClassVar[dict[str, object]] = {
        "name": "tool_b",
        "parameters": {"type": "object"},
    }


class _ToolFallback:
    name = "tool_c"
    description = "tool c description"
    args: ClassVar[dict[str, object]] = {"x": 1}


class TestExtractCompressionIntent:
    def test_with_intent_dict(self) -> None:
        result = extract_compression_intent(
            {
                "compression_intent": {
                    "focus_files": ["a.py"],
                    "user_goal_hint": "refactor",
                }
            }
        )
        assert result is not None
        assert result["focus_files"] == ["a.py"]
        assert result["user_goal_hint"] == "refactor"

    def test_with_typed_intent(self) -> None:
        intent = CompressionIntent(focus_modules=["m1"])
        result = extract_compression_intent({"compression_intent": intent})
        assert result is not None
        assert result["focus_modules"] == ["m1"]

    def test_without_intent(self) -> None:
        assert extract_compression_intent({}) is None


class TestResolveCacheUsageFeedback:
    def test_explicit_metadata_wins(self) -> None:
        feedback = resolve_cache_usage_feedback(
            {
                "cache_hit_rate": 0.9,
                "cached_tokens": 1000,
                "input_tokens": 2000,
                "cache_feedback_calls": 3,
            }
        )
        assert feedback is not None
        assert feedback.cache_hit_rate == pytest.approx(0.9)
        assert feedback.calls == 3

    def test_falls_back_to_collector(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import myrm_agent_harness.agent.middlewares.context_pipeline.context_pipeline_helpers as helpers

        fallback = CacheUsageFeedback(
            calls=5, input_tokens=100, cached_tokens=50, cache_hit_rate=0.5
        )
        monkeypatch.setattr(helpers, "get_cache_usage_feedback", lambda: fallback)
        assert resolve_cache_usage_feedback({}) is fallback

    def test_none_feedback_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import myrm_agent_harness.agent.middlewares.context_pipeline.context_pipeline_helpers as helpers

        monkeypatch.setattr(helpers, "get_cache_usage_feedback", lambda: None)
        assert resolve_cache_usage_feedback({}) is None


class TestResolveContextBudgetMetadata:
    def test_with_tools(self) -> None:
        request = _make_request(tools=[_ToolWithSchema()])
        metadata = resolve_context_budget_metadata(request)
        assert "bound_tool_overhead_tokens" in metadata
        assert metadata["bound_tool_overhead_tokens"] > 0

    def test_without_tools(self) -> None:
        request = _make_request(tools=[])
        assert resolve_context_budget_metadata(request) == {}

    def test_with_tracker_last_call(self, monkeypatch: pytest.MonkeyPatch) -> None:

        from myrm_agent_harness.utils.token_economics.tracker import (
            TokenTracker,
            TokenUsage,
        )

        tracker = TokenTracker()
        tracker.usage.last_call = TokenUsage(prompt_tokens=42000, completion_tokens=0)
        monkeypatch.setattr(
            "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
            lambda: tracker,
        )
        metadata = resolve_context_budget_metadata(_make_request(tools=[]))
        assert metadata["last_provider_prompt_tokens"] == 42000

    def test_tracker_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from myrm_agent_harness.utils.token_economics.tracker import get_token_tracker

        original = get_token_tracker
        monkeypatch.setattr(
            "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
            lambda: None,
        )
        request = _make_request(tools=[_ToolWithSchema()])
        metadata = resolve_context_budget_metadata(request)
        assert "last_provider_prompt_tokens" not in metadata
        assert "bound_tool_overhead_tokens" in metadata
        monkeypatch.setattr(
            "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
            original,
        )


class TestExtractToolNamesAndSchemas:
    def test_returns_none_without_tools(self) -> None:
        assert extract_tool_names_and_schemas(_make_request(tools=None)) is None
        assert extract_tool_names_and_schemas(_make_request(tools=[])) is None

    def test_dict_tool(self) -> None:
        request = _make_request(
            tools=[{"name": "dict_tool", "description": "d", "args": {}}]
        )
        result = extract_tool_names_and_schemas(request)
        assert result is not None
        assert result[0][0] == "dict_tool"
        assert "dict_tool" in result[0][1]

    def test_args_schema_tool(self) -> None:
        request = _make_request(tools=[_ToolWithSchema()])
        result = extract_tool_names_and_schemas(request)
        assert result is not None
        assert result[0][0] == "tool_a"
        assert '"path"' in result[0][1]

    def test_tool_call_schema_tool(self) -> None:
        request = _make_request(tools=[_ToolWithCallSchema()])
        result = extract_tool_names_and_schemas(request)
        assert result is not None
        assert result[0][0] == "tool_b"
        assert "tool_b" in result[0][1]

    def test_fallback_payload_tool(self) -> None:
        request = _make_request(tools=[_ToolFallback()])
        result = extract_tool_names_and_schemas(request)
        assert result is not None
        assert result[0][0] == "tool_c"
        assert "tool c description" in result[0][1]

    def test_unnamed_tool_skipped(self) -> None:
        request = _make_request(tools=[object()])
        assert extract_tool_names_and_schemas(request) is None

    def test_mixed_tools(self) -> None:
        request = _make_request(tools=[{"name": "dict_tool", "args": {}}, object()])
        result = extract_tool_names_and_schemas(request)
        assert result is not None
        assert len(result) == 1
        assert result[0][0] == "dict_tool"


class TestEstimateRequestContextTokens:
    def test_returns_positive_estimate(self, monkeypatch: pytest.MonkeyPatch) -> None:

        monkeypatch.setattr(
            "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
            lambda: None,
        )
        request = _make_request(tools=[_ToolWithSchema()])
        estimate = estimate_request_context_tokens(
            [HumanMessage(content="hi")], request
        )
        assert estimate > 0


class TestToJsonSafe:
    def test_primitives_passthrough(self) -> None:
        assert _to_json_safe(None) is None
        assert _to_json_safe("s") == "s"
        assert _to_json_safe(1) == 1
        assert _to_json_safe(1.5) == 1.5
        assert _to_json_safe(True) is True

    def test_mapping_and_sequence(self) -> None:
        assert _to_json_safe({"a": [1, 2]}) == {"a": [1, 2]}
        assert _to_json_safe([1, "x"]) == [1, "x"]

    def test_type_objects(self) -> None:
        assert _to_json_safe(str) == {"type": "str"}
        assert _to_json_safe(object()) == {"type": "object"}


class TestCanonicalJson:
    def test_sorted_keys(self) -> None:
        payload = _canonical_json({"b": 1, "a": 2})
        assert payload == '{"a": 2, "b": 1}'
