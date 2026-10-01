"""Unit tests for CleanTranscriptReducer in myrm_agent_harness."""

from __future__ import annotations

import json

from myrm_agent_harness.toolkits.memory.strategies.clean_reducer import (
    CleanTranscriptReducer,
    clean_reduce_transcript,
    scrub_secrets,
)


def test_scrub_secrets() -> None:
    raw = "Here is my key sk-abcdef1234567890abcdef123 and ghp_123456789012345678901234567890123456 and Bearer eyJhbGciOiJIUzI1NiJ9"
    scrubbed = scrub_secrets(raw)
    assert "sk-abcdef" not in scrubbed
    assert "[REDACTED_API_KEY]" in scrubbed
    assert "ghp_12345" not in scrubbed
    assert "[REDACTED_GH_TOKEN]" in scrubbed
    assert "Bearer [REDACTED_TOKEN]" in scrubbed


def test_clean_reduce_claude_code_transcript() -> None:
    lines = [
        json.dumps({"type": "system", "content": "You are Claude Code engineer"}),
        json.dumps({
            "type": "user",
            "cwd": "/Users/dev/project",
            "sessionId": "claude-session-001",
            "message": {"content": "Fix the bug in auth.py"},
        }),
        json.dumps({
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "<thinking>I need to inspect auth.py</thinking>Let me check auth.py"},
                    {"type": "tool_use", "name": "bash", "input": {"command": "git diff auth.py"}},
                ]
            },
        }),
        json.dumps({
            "type": "tool_result",
            "name": "bash",
            "content": "+ def check_token(t): return True\n" * 15,
        }),
        json.dumps({
            "type": "assistant",
            "message": {"content": "I fixed the auth bug by updating check_token."},
        }),
    ]

    res = clean_reduce_transcript(lines)
    assert res.source_tool == "claude_code"
    assert res.session_id == "claude-session-001"
    assert res.cwd == "/Users/dev/project"
    assert len(res.turns) == 1

    turn = res.turns[0]
    assert turn.user_content == "Fix the bug in auth.py"
    assert "<thinking>" not in turn.assistant_content
    assert "[Tool] [Executed: bash" in turn.assistant_content
    assert "I fixed the auth bug" in turn.assistant_content
    assert res.reduction_ratio > 0.0


def test_clean_reduce_codex_transcript() -> None:
    lines = [
        json.dumps({"role": "developer", "content": "Internal developer prompt"}),
        json.dumps({
            "role": "user",
            "content": "Run tests on api module",
            "session_id": "codex-session-777",
            "working_directory": "/app",
        }),
        json.dumps({
            "role": "assistant",
            "content": "Running pytest now.",
            "tool_calls": [
                {
                    "function": {
                        "name": "exec_cmd",
                        "arguments": json.dumps({"cmd": "pytest tests/api"}),
                    }
                }
            ],
        }),
        json.dumps({
            "role": "tool",
            "name": "exec_cmd",
            "content": "================ 5 passed in 0.42s ================",
        }),
        json.dumps({"role": "assistant", "content": "All 5 tests in api passed successfully."}),
    ]

    res = CleanTranscriptReducer.reduce(lines)
    assert res.source_tool == "codex_cli"
    assert res.session_id == "codex-session-777"
    assert len(res.turns) == 1
    t = res.turns[0]
    assert "Run tests on api module" in t.user_content
    assert "All 5 tests in api passed" in t.assistant_content
    assert "[Tool]" in t.assistant_content


def test_clean_reduce_multiple_turns_and_truncation() -> None:
    # 2 turns with large tool stdout
    huge_stdout = "line\n" * 50
    lines = [
        json.dumps({"role": "user", "content": "Step 1"}),
        json.dumps({"role": "assistant", "content": "Working on step 1"}),
        json.dumps({"role": "tool", "name": "bash", "content": huge_stdout}),
        json.dumps({"role": "user", "content": "Step 2"}),
        json.dumps({"role": "assistant", "content": "Step 2 done."}),
    ]

    res = clean_reduce_transcript(lines)
    assert len(res.turns) == 2
    assert res.turns[0].user_content == "Step 1"
    assert "... [" in res.turns[0].assistant_content  # Truncation marker
    assert res.turns[1].user_content == "Step 2"


def test_empty_and_malformed_input() -> None:
    empty_res = clean_reduce_transcript([])
    assert len(empty_res.turns) == 0
    assert empty_res.raw_char_count == 0

    malformed_res = clean_reduce_transcript(["{invalid json", ""])
    assert len(malformed_res.turns) == 0
    assert "skipped_invalid_json_line" in malformed_res.warnings
