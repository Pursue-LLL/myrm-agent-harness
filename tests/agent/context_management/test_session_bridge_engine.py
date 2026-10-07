"""Tests for Universal Harness Session Handoff and Full-State Bridge Suite (Item 211).

Verifies multi-format parsing, lossless tool execution trace and workspace retention,
bidirectional round-trip export, web export sanitization, and session indexing.
"""

from __future__ import annotations

import json

from myrm_agent_harness.agent.context_management.session_bridge.session_bridge_engine import (
    UniversalSessionBridgeEngine,
)
from myrm_agent_harness.agent.context_management.session_bridge.session_bridge_types import (
    ExportBridgeResult,
    ExternalHarnessFormat,
    FullStateHandoffBundle,
    UniversalSessionDescriptor,
)


def test_parse_and_export_claude_code_session() -> None:
    """Verifies Claude Code session ingestion preserves tool traces, thinking, CWD, and round-trips."""
    engine = UniversalSessionBridgeEngine()

    raw_claude_payload = {
        "session_id": "claude_session_alpha_123",
        "title": "Refactor Authentication Middleware",
        "cwd": "/workspace/my-project",
        "git_diff": "diff --git a/auth.py b/auth.py\n+ def verify(): pass",
        "git_branch": "feature/auth-guard",
        "model": "claude-3-7-sonnet",
        "total_tokens": 14200,
        "messages": [
            {
                "role": "user",
                "content": "Check database connection pool configuration.",
            },
            {
                "role": "assistant",
                "thinking": "Analyzing config files for connection pool parameters.",
                "content": "Running inspection tool.",
                "tool_use": [
                    {
                        "id": "call_inspect_db_01",
                        "name": "view_file",
                        "input": {"path": "config/db.yaml"},
                    }
                ],
                "tool_results": [
                    {
                        "tool_use_id": "call_inspect_db_01",
                        "content": "max_connections: 50\ntimeout_seconds: 30",
                        "is_error": False,
                    }
                ],
            },
        ],
    }

    # 1. Parse external session
    bundle: FullStateHandoffBundle = engine.parse_claude_code_session(
        raw_claude_payload, source_path="/home/user/.claude/projects/sess_123.json"
    )

    # 2. Verify descriptor and workspace state
    assert bundle.descriptor.session_id == "claude_session_alpha_123"
    assert bundle.descriptor.format == ExternalHarnessFormat.CLAUDE_CODE
    assert bundle.descriptor.title == "Refactor Authentication Middleware"
    assert bundle.workspace_state.cwd == "/workspace/my-project"
    assert "diff --git a/auth.py" in bundle.workspace_state.uncommitted_git_diff
    assert bundle.workspace_state.git_branch == "feature/auth-guard"
    assert bundle.accumulated_tokens == 14200
    assert bundle.model_name == "claude-3-7-sonnet"

    # 3. Verify messages and tool trace fidelity
    assert len(bundle.messages) == 2
    user_msg = bundle.messages[0]
    asst_msg = bundle.messages[1]

    assert user_msg.role == "user"
    assert "Check database" in user_msg.content

    assert asst_msg.role == "assistant"
    assert asst_msg.thinking == "Analyzing config files for connection pool parameters."
    assert len(asst_msg.tool_traces) == 1

    trace = asst_msg.tool_traces[0]
    assert trace.tool_name == "view_file"
    assert trace.tool_call_id == "call_inspect_db_01"
    assert trace.arguments == {"path": "config/db.yaml"}
    assert "max_connections: 50" in trace.output
    assert trace.is_error is False

    # 4. Bidirectional round-trip export
    export_res: ExportBridgeResult = engine.export_to_claude_code(bundle)
    assert export_res.target_format == ExternalHarnessFormat.CLAUDE_CODE
    assert export_res.exported_message_count == 2
    assert export_res.export_duration_ms >= 0.0

    exported_json = json.loads(export_res.output_payload)
    assert exported_json["session_id"] == "claude_session_alpha_123"
    assert exported_json["cwd"] == "/workspace/my-project"
    assert len(exported_json["messages"]) == 2
    assert len(exported_json["messages"][1]["tool_use"]) == 1
    assert exported_json["messages"][1]["tool_results"][0]["content"] == "max_connections: 50\ntimeout_seconds: 30"


def test_parse_and_export_openai_codex_session() -> None:
    """Verifies OpenAI Codex rollout JSONL parsing, tool capture, and reverse export."""
    engine = UniversalSessionBridgeEngine()

    codex_rollout_lines = [
        json.dumps({
            "type": "session_start",
            "session_id": "codex_rollout_7788",
            "cwd": "/opt/app",
            "model": "codex-astra",
        }),
        json.dumps({
            "type": "message",
            "role": "user",
            "content": "Run tests for payment module.",
        }),
        json.dumps({
            "type": "message",
            "role": "assistant",
            "content": "Executing pytest on payment package.",
            "tool_calls": [
                {
                    "id": "call_exec_001",
                    "name": "bash",
                    "arguments": {"cmd": "pytest tests/payment"},
                    "output": "12 passed in 1.45s",
                }
            ],
        }),
    ]
    raw_payload = "\n".join(codex_rollout_lines)

    bundle = engine.parse_openai_codex_session(raw_payload, source_path="/tmp/rollout.jsonl")

    assert bundle.descriptor.session_id == "codex_rollout_7788"
    assert bundle.descriptor.format == ExternalHarnessFormat.OPENAI_CODEX
    assert bundle.workspace_state.cwd == "/opt/app"
    assert len(bundle.messages) == 2

    tool_msg = bundle.messages[1]
    assert len(tool_msg.tool_traces) == 1
    assert tool_msg.tool_traces[0].tool_name == "bash"
    assert tool_msg.tool_traces[0].output == "12 passed in 1.45s"

    # Export back to Codex format
    export_res = engine.export_to_openai_codex(bundle)
    assert export_res.target_format == ExternalHarnessFormat.OPENAI_CODEX
    assert "session_start" in export_res.output_payload
    assert "12 passed in 1.45s" in export_res.output_payload


def test_parse_web_ai_chat_export_json_and_markdown() -> None:
    """Verifies Web AI chat exports in JSON and Markdown with disclaimer sanitization."""
    engine = UniversalSessionBridgeEngine()

    # Case A: JSON format from Web AI chat exporter
    json_export = {
        "id": "chat_export_web_99",
        "title": "Quantum Computing Basics",
        "messages": [
            {"role": "user", "content": "Explain qubits."},
            {
                "role": "assistant",
                "content": "Disclaimer: AI generated response.\nChatGPT: A qubit is a basic unit of quantum information.",
            },
        ],
    }

    bundle_json = engine.parse_web_ai_chat_export(json_export)
    assert bundle_json.descriptor.session_id == "chat_export_web_99"
    assert bundle_json.descriptor.title == "Quantum Computing Basics"
    assert len(bundle_json.messages) == 2
    # Check disclaimer and prefix stripping
    assert "Disclaimer:" not in bundle_json.messages[1].content
    assert "ChatGPT:" not in bundle_json.messages[1].content
    assert bundle_json.messages[1].content.startswith("A qubit is a basic unit")

    # Case B: Markdown format
    md_export = """
### User
How to optimize SQLite queries?

### Assistant
Claude: You can create indexes on foreign keys and use EXPLAIN QUERY PLAN.
"""
    bundle_md = engine.parse_web_ai_chat_export(md_export)
    assert bundle_md.descriptor.format == ExternalHarnessFormat.WEB_CHAT_EXPORT
    assert len(bundle_md.messages) == 2
    assert bundle_md.messages[0].role == "user"
    assert "How to optimize SQLite" in bundle_md.messages[0].content
    assert bundle_md.messages[1].role == "assistant"
    assert "Claude:" not in bundle_md.messages[1].content
    assert "create indexes on foreign keys" in bundle_md.messages[1].content


def test_discover_and_index_multiple_sessions() -> None:
    """Verifies scanning multiple external session files and creating concise index descriptors."""
    engine = UniversalSessionBridgeEngine()

    entries: list[tuple[ExternalHarnessFormat, str, str]] = [
        (
            ExternalHarnessFormat.CLAUDE_CODE,
            "/home/user/.claude/projects/session_a.json",
            json.dumps({"session_id": "sess_a", "title": "Claude Task", "messages": []}),
        ),
        (
            ExternalHarnessFormat.OPENAI_CODEX,
            "/home/user/.codex/sessions/session_b.jsonl",
            json.dumps({"type": "session_start", "session_id": "sess_b"}),
        ),
        (
            ExternalHarnessFormat.WEB_CHAT_EXPORT,
            "/home/user/Downloads/chat_c.json",
            json.dumps({"id": "sess_c", "title": "Web Chat Task", "messages": []}),
        ),
    ]

    descriptors: list[UniversalSessionDescriptor] = engine.discover_and_index_sessions(entries)
    assert len(descriptors) == 3

    assert descriptors[0].session_id == "sess_a"
    assert descriptors[0].format == ExternalHarnessFormat.CLAUDE_CODE
    assert descriptors[0].source_path == "/home/user/.claude/projects/session_a.json"

    assert descriptors[1].session_id == "sess_b"
    assert descriptors[1].format == ExternalHarnessFormat.OPENAI_CODEX

    assert descriptors[2].session_id == "sess_c"
    assert descriptors[2].format == ExternalHarnessFormat.WEB_CHAT_EXPORT

    # Serialization check
    serialized = descriptors[0].to_dict()
    assert serialized["session_id"] == "sess_a"
    assert serialized["format"] == "claude_code"
