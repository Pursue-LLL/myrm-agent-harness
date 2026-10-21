"""Tests for tool_recovery module."""

from __future__ import annotations

import json
from unittest.mock import patch

from myrm_agent_harness.toolkits.llms.adapters.tool_recovery import (
    build_final_tool_call_chunk,
    is_stream_complete,
    recover_tool_call_payloads,
)


class TestIsStreamComplete:
    """Fail-safe mapping: only a normal tool-call completion is treated as complete."""

    def test_normal_tool_calls_complete(self) -> None:
        assert is_stream_complete("tool_calls") is True

    def test_abnormal_ends_incomplete(self) -> None:
        for reason in (None, "", "length", "max_tokens", "content_filter", "SAFETY", "refusal"):
            assert is_stream_complete(reason) is False

    def test_stop_defaults_safe(self) -> None:
        # "stop" without parsed tool calls: args would be malformed if any, so
        # repairing them is not a false positive (a complete parse short-circuits).
        assert is_stream_complete("stop") is True

    def test_stream_the_provider_never_finished_is_incomplete(self) -> None:
        # The stream layer synthesizes "stop" when a connection closes mid-call; only the provider's own marker counts.
        assert is_stream_complete("stop", provider_finish=False) is False
        assert is_stream_complete("tool_calls", provider_finish=False) is False

    def test_unknown_or_confirmed_provider_finish_changes_nothing(self) -> None:
        assert is_stream_complete("stop", provider_finish=None) is True
        assert is_stream_complete("stop", provider_finish=True) is True
        assert is_stream_complete("length", provider_finish=True) is False


def _build_tool_schema(
    name: str, properties: dict[str, object], required: list[str] | None = None
) -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "parameters": {"type": "object", "properties": properties, "required": required or []},
        },
    }


class TestRecoverToolCallPayloads:
    def test_standard_json(self) -> None:
        raw = [
            {"id": "call_1", "type": "function", "function": {"name": "search", "arguments": '{"query": "test"}'}},
        ]
        recovered, metadata = recover_tool_call_payloads(raw)
        assert len(recovered) == 1
        assert recovered[0]["function"]["name"] == "search"
        assert json.loads(recovered[0]["function"]["arguments"]) == {"query": "test"}
        assert metadata[0]["safe"] is True

    def test_skips_no_function(self) -> None:
        raw = [{"id": "call_1", "type": "function"}]
        recovered, _metadata = recover_tool_call_payloads(raw)
        assert len(recovered) == 0

    def test_skips_empty_name(self) -> None:
        raw = [{"id": "call_1", "type": "function", "function": {"name": "", "arguments": "{}"}}]
        recovered, _metadata = recover_tool_call_payloads(raw)
        assert len(recovered) == 0

    def test_with_schema_and_colon_name(self) -> None:
        schema = _build_tool_schema("write", {"content": {"type": "string"}})
        raw = [
            {"id": "call_1", "type": "function", "function": {"name": "ns:write", "arguments": '{"content": "hi"}'}},
        ]
        recovered, metadata = recover_tool_call_payloads(raw, tool_schemas={"write": schema})
        assert len(recovered) == 1
        assert metadata[0]["tool_name"] == "write"

    def test_html_entity_decoding(self) -> None:
        raw = [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "bash", "arguments": json.dumps({"cmd": "echo &amp; hello"})},
            },
        ]
        recovered, _metadata = recover_tool_call_payloads(raw, decode_html_entities=True)
        assert len(recovered) == 1
        args = json.loads(recovered[0]["function"]["arguments"])
        assert "& hello" in args["cmd"]

    def test_degraded_recovery_records_metric(self) -> None:
        raw = [
            {"id": "call_1", "type": "function", "function": {"name": "t", "arguments": "invalid json garbage"}},
        ]
        with patch("myrm_agent_harness.observability.metrics.registry.metrics_registry") as mock_reg:
            recovered, metadata = recover_tool_call_payloads(raw)
        # Unrecoverable arguments are withheld (not dispatched) and reported unsafe.
        assert recovered == []
        assert metadata[0]["safe"] is False
        assert metadata[0]["strategy"] == "failed"
        mock_reg.record_tool_arg_recovery.assert_called_once()

    def test_truncated_stream_withholds_repairable_args(self) -> None:
        """A truncated stream must not close a partial JSON into a valid object."""
        raw = [
            {"id": "call_1", "type": "function", "function": {"name": "write", "arguments": '{"path": "/tmp/x"'}},
        ]
        recovered, metadata = recover_tool_call_payloads(raw, stream_complete=False)
        assert recovered == []
        assert metadata[0]["safe"] is False
        assert metadata[0]["strategy"] == "truncated_stream_unverified"
        assert metadata[0]["raw_arguments"] == '{"path": "/tmp/x"'

    def test_empty_finish_reason_withholds_partial_args(self) -> None:
        """A dropped stream leaves an empty finish_reason; partial args must be withheld."""
        raw = [
            {"id": "call_1", "type": "function", "function": {"name": "write", "arguments": '{"path": "/tmp/x"'}},
        ]
        recovered, metadata = recover_tool_call_payloads(raw, stream_complete=is_stream_complete(""))
        assert recovered == []
        assert metadata[0]["safe"] is False

    def test_complete_stream_repairs_truncated_args(self) -> None:
        """When the stream ended normally, the same partial JSON is repaired."""
        raw = [
            {"id": "call_1", "type": "function", "function": {"name": "write", "arguments": '{"path": "/tmp/x"'}},
        ]
        recovered, metadata = recover_tool_call_payloads(raw, stream_complete=True)
        assert len(recovered) == 1
        assert metadata[0]["safe"] is True
        assert json.loads(recovered[0]["function"]["arguments"]) == {"path": "/tmp/x"}

    def test_multiple_tool_calls(self) -> None:
        raw = [
            {"id": "call_1", "type": "function", "function": {"name": "a", "arguments": '{"x": 1}'}},
            {"id": "call_2", "type": "function", "function": {"name": "b", "arguments": '{"y": 2}'}},
        ]
        recovered, metadata = recover_tool_call_payloads(raw)
        assert len(recovered) == 2
        assert len(metadata) == 2

    def test_auto_generated_id(self) -> None:
        raw = [{"type": "function", "function": {"name": "t", "arguments": '{"k": "v"}'}}]
        recovered, metadata = recover_tool_call_payloads(raw)
        assert recovered[0]["id"] == "call_0"
        assert metadata[0]["tool_call_id"] == "call_0"


class TestBuildFinalToolCallChunk:
    def test_empty_returns_none(self) -> None:
        chunk, recovered, _metadata = build_final_tool_call_chunk([])
        assert chunk is None
        assert recovered == []

    def test_single_tool_call(self) -> None:
        raw = [
            {"id": "call_1", "type": "function", "function": {"name": "search", "arguments": '{"q": "hello"}'}},
        ]
        chunk, _recovered, _metadata = build_final_tool_call_chunk(raw)
        assert chunk is not None
        assert len(chunk.message.tool_call_chunks) == 1
        tc = chunk.message.tool_call_chunks[0]
        assert tc["name"] == "search"
        assert tc["id"] == "call_1"

    def test_multiple_tool_calls(self) -> None:
        raw = [
            {"id": "call_1", "type": "function", "function": {"name": "a", "arguments": '{"x": 1}'}},
            {"id": "call_2", "type": "function", "function": {"name": "b", "arguments": '{"y": 2}'}},
        ]
        chunk, _recovered, _metadata = build_final_tool_call_chunk(raw)
        assert chunk is not None
        assert len(chunk.message.tool_call_chunks) == 2

    def test_recovery_metadata_in_kwargs(self) -> None:
        raw = [
            {"id": "call_1", "type": "function", "function": {"name": "t", "arguments": "broken json {"}},
        ]
        chunk, _, metadata = build_final_tool_call_chunk(raw)
        assert chunk is not None
        if any(m["strategy"] != "standard_json" or m["degraded"] or not m["safe"] for m in metadata):
            assert "tool_call_recovery" in chunk.message.additional_kwargs

    def test_with_schema(self) -> None:
        schema = _build_tool_schema(
            "file_write", {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]
        )
        raw = [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "file_write", "arguments": '{"path": "a.py", "content": "print(1)"}'},
            },
        ]
        chunk, _recovered, metadata = build_final_tool_call_chunk(raw, {"file_write": schema})
        assert chunk is not None
        assert metadata[0]["safe"] is True
