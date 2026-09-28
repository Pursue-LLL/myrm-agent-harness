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


def test_path_remapper_edge_cases() -> None:
    from myrm_agent_harness.runtime.context.transcripts.path_remapper import remap_path_string

    # 1. No host_root configured (passthrough)
    noop_remapper = SandboxPathRemapper(host_root=None, sandbox_root="/workspace")
    assert noop_remapper.remap_text("sample /Users/dev/file.txt") == "sample /Users/dev/file.txt"
    assert noop_remapper.remap_text("") == ""
    assert noop_remapper.remap_arguments({"path": "/Users/dev/file.txt"}) == {"path": "/Users/dev/file.txt"}

    # 2. Nested dict, non-string list items, and pure functional utility
    active_remapper = SandboxPathRemapper(host_root="/host/dir", sandbox_root="/container/dir")
    complex_args: dict[str, object] = {
        "nested": {"deep_path": "/host/dir/config.json"},
        "mixed_list": ["/host/dir/1.py", 100, None, True],
        "number": 42,
    }
    remapped = active_remapper.remap_arguments(complex_args)
    nested_res = remapped["nested"]
    assert isinstance(nested_res, dict)
    assert nested_res["deep_path"] == "/container/dir/config.json"
    assert remapped["mixed_list"] == ["/container/dir/1.py", 100, None, True]
    assert remapped["number"] == 42

    functional_res = remap_path_string("/host/dir/app.py", host_prefix="/host/dir", sandbox_target="/sandbox")
    assert functional_res == "/sandbox/app.py"


def test_tool_compactor_edge_cases() -> None:
    from myrm_agent_harness.runtime.context.transcripts.tool_compactor import compact_tool_output
    from myrm_agent_harness.runtime.context.transcripts.types import CanonicalToolCall

    # None output passthrough
    call_none = CanonicalToolCall(call_id="c0", tool_name="bash", arguments={}, output=None)
    assert compact_tool_output(call_none).output is None

    # Single-line massive text exceeding threshold but with few lines
    huge_single_line = "A" * 3000
    call_huge_line = CanonicalToolCall(call_id="c1", tool_name="cat", arguments={}, output=huge_single_line)
    res_huge = ToolOutputCompactor(threshold_bytes=1000).compact(call_huge_line)
    assert res_huge.compacted
    assert "truncated" in (res_huge.output or "")


def test_claude_parser_edge_cases(tmp_path: object) -> None:
    from pathlib import Path

    parser = ClaudeTranscriptParser(sandbox_root="/workspace", host_root_hint="/custom/host")

    # Corrupted / empty lines / non-dict events / thought field extraction
    lines = [
        "",  # Empty line
        "{invalid-json}",  # Malformed JSON
        json.dumps(["not", "a", "dict"]),  # List instead of dict
        json.dumps({"type": "assistant", "thought": "Plan ahead carefully", "text": "Starting work"}),
        # Tool call with raw string input and orphaned tool result
        json.dumps({"type": "assistant", "tool_uses": [{"id": "tu-99", "name": "custom", "input": "raw-arg"}]}),
        json.dumps({"type": "tool_result", "tool_use_id": "orphan-id", "content": "orphan output"}),
    ]
    stream = io.StringIO("\n".join(lines))
    res = parser.parse_stream(stream, default_session_id="fallback-claude")
    assert res.title == "Claude Code Imported Session"
    assert len(res.turns) == 2
    assert res.turns[0].thinking_trace == "Plan ahead carefully"
    assert res.turns[1].tool_calls[0].arguments == {"raw": "raw-arg"}

    # File based parse_file
    p = Path(str(tmp_path)) / "claude_sample.jsonl"
    p.write_text(json.dumps({"type": "user", "message": "File based prompt"}))
    file_res = parser.parse_file(p)
    assert file_res.session_id == "claude_sample"
    assert file_res.title == "File based prompt"


def test_codex_parser_edge_cases(tmp_path: object) -> None:
    from pathlib import Path

    parser = CodexTranscriptParser(sandbox_root="/workspace")

    # 1. Invalid JSON string
    res_invalid_json = parser.parse_stream(io.StringIO("{bad json"))
    assert res_invalid_json.title == "Invalid Codex Session"
    assert len(res_invalid_json.turns) == 0

    # 2. JSON array instead of dict
    res_array = parser.parse_stream(io.StringIO(json.dumps([1, 2, 3])))
    assert res_array.title == "Invalid Codex Session"

    # 3. Non-dict message items, unparseable arguments, and default title fallback
    data = {
        "id": "codex-corrupt",
        "messages": [
            "not a dict msg",
            {
                "role": "assistant",
                "tool_calls": [
                    "not a dict tc",
                    {
                        "id": "tc-bad",
                        "function": {"name": "test_fn", "arguments": "{malformed json args"},
                    },
                    {
                        "id": "tc-non-str",
                        "function": {"name": "other_fn", "arguments": 12345},
                    },
                ],
            },
        ],
    }
    res_edge = parser.parse_stream(io.StringIO(json.dumps(data)))
    assert res_edge.title == "Codex CLI Imported Session"
    assert len(res_edge.turns) == 1
    assert len(res_edge.turns[0].tool_calls) == 2
    assert res_edge.turns[0].tool_calls[0].arguments == {"raw": "{malformed json args"}
    assert res_edge.turns[0].tool_calls[1].arguments == {}

    # 4. File-based parse_file
    p = Path(str(tmp_path)) / "codex_sample.json"
    p.write_text(json.dumps({"id": "codex-disk", "messages": [{"role": "user", "content": "Disk task"}]}))
    file_res = parser.parse_file(p)
    assert file_res.session_id == "codex-disk"
    assert file_res.title == "Disk task"

