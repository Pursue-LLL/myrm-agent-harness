"""Unit tests for cross-tool transcript parsers, path remapper, and tool compactor."""

from __future__ import annotations

import io
import json

from myrm_agent_harness.runtime.context.transcripts import (
    CanonicalTurnRole,
    ClaudeTranscriptParser,
    CodexTranscriptParser,
    SandboxPathRemapper,
    ToolOutputCompactor,
)


def test_sandbox_path_remapper() -> None:
    host_root = "/Users/yululiu/projects/AI/open-perplexity"
    remapper = SandboxPathRemapper(host_root=host_root, sandbox_root="/workspace")

    original_text = "I modified /Users/yululiu/projects/AI/open-perplexity/src/main.py successfully."
    remapped_text = remapper.remap_text(original_text)
    assert remapped_text == "I modified /workspace/src/main.py successfully."

    args = {
        "file_path": "/Users/yululiu/projects/AI/open-perplexity/README.md",
        "commands": ["cat /Users/yululiu/projects/AI/open-perplexity/package.json"],
        "count": 5,
    }
    remapped_args = remapper.remap_arguments(args)
    assert remapped_args["file_path"] == "/workspace/README.md"
    assert remapped_args["commands"] == ["cat /workspace/package.json"]
    assert remapped_args["count"] == 5


def test_tool_output_compactor() -> None:
    from myrm_agent_harness.runtime.context.transcripts.types import CanonicalToolCall

    compactor = ToolOutputCompactor(threshold_bytes=100, head_lines=2, tail_lines=2)

    # Short output: not compacted
    short_call = CanonicalToolCall(
        call_id="call-1",
        tool_name="view_file",
        arguments={"path": "a.txt"},
        output="Line 1\nLine 2\nLine 3",
    )
    res_short = compactor.compact(short_call)
    assert not res_short.compacted
    assert res_short.output == "Line 1\nLine 2\nLine 3"

    # Giant output: compacted
    giant_lines = [f"Log line {i} with lots of characters to exceed threshold quickly" for i in range(50)]
    giant_text = "\n".join(giant_lines)
    giant_call = CanonicalToolCall(
        call_id="call-2",
        tool_name="run_shell",
        arguments={"cmd": "build"},
        output=giant_text,
    )
    res_giant = compactor.compact(giant_call)
    assert res_giant.compacted
    assert res_giant.original_size_bytes > 100
    assert "omitted" in (res_giant.output or "")
    assert res_giant.output.startswith(f"{giant_lines[0]}\n{giant_lines[1]}")


def test_claude_transcript_parser() -> None:
    events = [
        {"type": "user", "message": "Can you check <system-reminder>secret</system-reminder> distributed rpc timeout?", "timestamp": 1700000000.0, "cwd": "/Users/dev/order-svc"},
        {
            "type": "assistant",
            "text": "<thinking>Let me search the logs first.</thinking>Running grep to locate timeout occurrences.",
            "tool_uses": [
                {
                    "id": "tu-1",
                    "name": "Bash",
                    "input": {"command": "grep -rn 'Timeout' /Users/dev/order-svc/logs/"},
                }
            ],
            "timestamp": 1700000005.0,
        },
        {
            "type": "tool_result",
            "tool_use_id": "tu-1",
            "content": "Found 3 matching lines in /Users/dev/order-svc/logs/app.log",
            "exit_code": 0,
        },
        {
            "type": "assistant",
            "text": "The error shows HikariCP pool exhaustion.",
            "timestamp": 1700000010.0,
        },
    ]

    jsonl_stream = io.StringIO("\n".join(json.dumps(e) for e in events))
    parser = ClaudeTranscriptParser(sandbox_root="/workspace")
    result = parser.parse_stream(jsonl_stream, default_session_id="session-rpc-timeout")

    assert result.session_id == "session-rpc-timeout"
    assert "distributed rpc timeout" in result.title.lower()
    assert result.source_platform == "claude_code"
    assert len(result.turns) == 3

    # Turn 0: User (system-reminder stripped)
    t0 = result.turns[0]
    assert t0.role == CanonicalTurnRole.USER
    assert "<system-reminder>" not in t0.content
    assert "distributed rpc timeout" in t0.content

    # Turn 1: Assistant with thinking and remapped tool call
    t1 = result.turns[1]
    assert t1.role == CanonicalTurnRole.ASSISTANT
    assert t1.thinking_trace == "Let me search the logs first."
    assert len(t1.tool_calls) == 1
    tc = t1.tool_calls[0]
    assert tc.tool_name == "Bash"
    # Host root remapped to /workspace
    assert tc.arguments["command"] == "grep -rn 'Timeout' /workspace/logs/"
    assert tc.output == "Found 3 matching lines in /workspace/logs/app.log"

    # Turn 2: Assistant follow-up
    t2 = result.turns[2]
    assert t2.role == CanonicalTurnRole.ASSISTANT
    assert "HikariCP" in t2.content


def test_codex_transcript_parser() -> None:
    data = {
        "id": "codex-test-1",
        "created_at": 1700000000.0,
        "workspace_root": "/Users/dev/repo",
        "messages": [
            {"role": "user", "content": "Refactor the payment controller"},
            {
                "role": "assistant",
                "content": "I will examine the controller first.",
                "tool_calls": [
                    {
                        "id": "tc-10",
                        "function": {"name": "read_file", "arguments": '{"path": "/Users/dev/repo/pay.py"}'},
                        "output": "class PaymentController:\n    pass\n",
                    }
                ],
            },
        ],
    }

    stream = io.StringIO(json.dumps(data))
    parser = CodexTranscriptParser(sandbox_root="/workspace")
    result = parser.parse_stream(stream)

    assert result.session_id == "codex-test-1"
    assert result.title == "Refactor the payment controller"
    assert len(result.turns) == 2
    assert result.turns[0].role == CanonicalTurnRole.USER
    assert result.turns[1].role == CanonicalTurnRole.ASSISTANT
    assert len(result.turns[1].tool_calls) == 1
    assert result.turns[1].tool_calls[0].arguments["path"] == "/workspace/pay.py"
