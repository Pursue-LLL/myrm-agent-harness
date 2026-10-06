# [POS]: tests/toolkits/memory/test_mcp_server_interop.py
# [INPUT]: pytest, myrm_agent_harness.toolkits.memory.agent_surface.mcp
# [OUTPUT]: test_mcp_server_interop suite
"""Unit test suite for memory MCP interop gateway and ai-memory wire parity.

Validates drop-in MCP tool compatibility (query_memory, get_handoff,
finalize_session, remember), privacy boundary gating, and tool registration.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from myrm_agent_harness.agent.context_management.handoff import (
    AgentHandoffEngine,
)
from myrm_agent_harness.toolkits.memory.agent_surface.mcp import (
    AiMemoryWireAdapter,
    McpServerInfo,
    create_interop_memory_mcp_server,
)
from myrm_agent_harness.toolkits.memory.privacy_gate import (
    MemoryPrivacyBoundaryGate,
    MemoryPrivacyConfig,
)


@pytest.fixture
def temp_dir() -> Path:
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def wire_adapter(temp_dir: Path) -> AiMemoryWireAdapter:
    engine = AgentHandoffEngine(storage_dir=temp_dir / "handoffs")
    gate = MemoryPrivacyBoundaryGate(
        config=MemoryPrivacyConfig(
            block_on_critical=False,
            strict_mode=False,
        )
    )
    return AiMemoryWireAdapter(handoff_engine=engine, privacy_gate=gate)


def test_remember_and_query_memory(wire_adapter: AiMemoryWireAdapter) -> None:
    # 1. Query empty memory
    empty_res = wire_adapter.query_memory("architecture")
    assert "No matching memories found" in empty_res

    # 2. Remember new facts
    res1 = wire_adapter.remember(
        topic="Architecture",
        note="Use FastAPI for synchronous routing and Harness for Agent loop",
    )
    assert "Stored fact under topic [Architecture]" in res1

    res2 = wire_adapter.remember(
        topic="Database",
        note="Qdrant is used for vector search and SQLite for operational records",
    )
    assert "Stored fact under topic [Database]" in res2

    # 3. Query matching memory
    search_res = wire_adapter.query_memory("FastAPI", limit=5)
    assert "### Memory Search: \"FastAPI\" (1 results)" in search_res
    assert "[Architecture]" in search_res
    assert "Harness for Agent loop" in search_res


def test_remember_with_secret_redaction(wire_adapter: AiMemoryWireAdapter) -> None:
    # Ingest a note containing a mock API Key (auto-sanitized when block_on_critical=False)
    raw_note = "Connecting with upstream key sk-proj-1234567890abcdef1234567890abcdef safely"
    rem_res = wire_adapter.remember(topic="Credentials", note=raw_note)
    assert "Sanitized and stored" in rem_res

    # Verify redacted in query
    query_res = wire_adapter.query_memory("Credentials")
    assert "[REDACTED:API_KEY]" in query_res
    assert "sk-proj-1234567890abcdef1234567890abcdef" not in query_res


def test_remember_rejected_by_privacy_gate(temp_dir: Path) -> None:
    engine = AgentHandoffEngine(storage_dir=temp_dir / "handoffs")
    # Configure hard block gate (strict_mode=True or prohibited source file)
    gate = MemoryPrivacyBoundaryGate(
        config=MemoryPrivacyConfig(
            block_on_critical=True,
            strict_mode=True,
        )
    )
    adapter = AiMemoryWireAdapter(handoff_engine=engine, privacy_gate=gate)

    # Ingest note from prohibited file .env
    res = adapter.remember(
        topic="Security",
        note="Found token sk-proj-1234567890abcdef1234567890abcdef",
        source_file=".env",
    )
    assert "REJECTED by Privacy Boundary Gate" in res


def test_finalize_session_and_get_handoff(wire_adapter: AiMemoryWireAdapter) -> None:
    # 1. No pending handoff initially
    init_handoff = wire_adapter.get_handoff()
    assert "No pending handoff memorandum found" in init_handoff

    # 2. Finalize working session
    summary_text = "Completed core wire adapter and MCP server endpoints"
    next_steps = ["Add unit tests", "Register API routes"]
    failed = ["Directly exposing raw unredacted store"]

    finalize_msg = wire_adapter.finalize_session(
        summary=summary_text,
        next_steps=next_steps,
        failed_approaches=failed,
        session_id="test-session-43",
    )
    assert "Session finalized successfully" in finalize_msg
    assert "Ready for successor agent pickup" in finalize_msg

    # 3. Retrieve handoff
    retrieved = wire_adapter.get_handoff()
    assert "Active Handoff Memorandum" in retrieved
    assert summary_text in retrieved
    assert "1. Add unit tests" in retrieved
    assert "2. Register API routes" in retrieved
    assert "Directly exposing raw unredacted store" in retrieved


def test_create_interop_memory_mcp_server(temp_dir: Path) -> None:
    engine = AgentHandoffEngine(storage_dir=temp_dir / "handoffs")
    gate = MemoryPrivacyBoundaryGate(config=MemoryPrivacyConfig())

    server, info = create_interop_memory_mcp_server(
        handoff_engine=engine,
        privacy_gate=gate,
        server_name="test-myrm-memory-mcp",
    )

    assert isinstance(info, McpServerInfo)
    assert info.server_name == "test-myrm-memory-mcp"
    assert "query_memory" in info.tools_exposed
    assert "get_handoff" in info.tools_exposed
    assert "finalize_session" in info.tools_exposed
    assert "remember" in info.tools_exposed
    assert "ai-memory-v1" in info.compatible_with

    # Verify tool callable registry
    tool_dict = server._tool_manager._tools
    assert "query_memory" in tool_dict
    assert "get_handoff" in tool_dict
    assert "finalize_session" in tool_dict
    assert "remember" in tool_dict
