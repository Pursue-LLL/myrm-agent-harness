"""Unit tests for HermesTranscriptParser in myrm_agent_harness."""

from __future__ import annotations

import io
import json

from myrm_agent_harness.runtime.context.transcripts.hermes_parser import HermesTranscriptParser
from myrm_agent_harness.runtime.context.transcripts.types import CanonicalTurnRole


def test_hermes_parser_single_json_document() -> None:
    doc = {
        "id": "hermes-session-999",
        "title": "Investigate CPU Spike",
        "created_at": 1720000000.0,
        "workspace_root": "/Users/developer/backend",
        "messages": [
            {"role": "user", "content": "Why is the server CPU spiking?"},
            {
                "role": "assistant",
                "content": "Analyzing process top output",
                "thinking": "Need to check top and logs",
                "tool_calls": [
                    {
                        "id": "tc-1",
                        "function": {
                            "name": "exec_cmd",
                            "arguments": json.dumps({"cmd": "top -b -n 1"}),
                        },
                        "output": "PID USER PR NI VIRT RES SHR S %CPU %MEM TIME+ COMMAND\n1001 dev 20 0 10G 8G 50M R 99.8 50.0 10:20 worker\n",
                    }
                ],
            },
        ],
    }

    parser = HermesTranscriptParser(sandbox_root="/workspace")
    stream = io.StringIO(json.dumps(doc))
    result = parser.parse_stream(stream)

    assert result.source_platform == "hermes"
    assert result.session_id == "hermes-session-999"
    assert result.title == "Investigate CPU Spike"
    assert len(result.turns) == 2

    u_turn = result.turns[0]
    assert u_turn.role == CanonicalTurnRole.USER
    assert u_turn.content == "Why is the server CPU spiking?"

    a_turn = result.turns[1]
    assert a_turn.role == CanonicalTurnRole.ASSISTANT
    assert a_turn.content == "Analyzing process top output"
    assert a_turn.thinking_trace == "Need to check top and logs"
    assert len(a_turn.tool_calls) == 1
    assert a_turn.tool_calls[0].tool_name == "exec_cmd"


def test_hermes_parser_jsonl_stream() -> None:
    lines = [
        json.dumps({"role": "user", "content": "Setup redis cache", "id": "hermes-jl-1"}),
        json.dumps({"role": "assistant", "content": "Redis cache setup complete."}),
    ]

    parser = HermesTranscriptParser()
    stream = io.StringIO("\n".join(lines))
    result = parser.parse_stream(stream)

    assert result.source_platform == "hermes"
    assert len(result.turns) == 2
    assert result.turns[0].content == "Setup redis cache"
    assert result.turns[1].content == "Redis cache setup complete."


def test_hermes_parser_empty() -> None:
    parser = HermesTranscriptParser()
    stream = io.StringIO("")
    result = parser.parse_stream(stream)
    assert len(result.turns) == 0
