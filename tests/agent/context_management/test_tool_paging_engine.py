"""Tests for Model-Native Dynamic Tool Pruning and Context Paging Offload Suite (Item 228)."""

import pytest

from myrm_agent_harness.agent.context_management.tool_paging import (
    ModelNativeToolPagingEngine,
    ModelTier,
    PageInSlice,
    ToolBlobRecord,
    ToolOutputStub,
    ToolPagingConfig,
    ToolSchemaDefinition,
)


def test_model_aware_tool_schema_compaction() -> None:
    """Verify tool schemas are compactly pruned for Flash models while retaining full semantics for Pro."""
    engine = ModelNativeToolPagingEngine()
    tools = [
        ToolSchemaDefinition(
            name="execute_sql_query",
            description="Executes a sanitized SQL read query against the operational SQLite database with telemetry hooks.",
            parameters={
                "query": "string: Must be a SELECT query. Mutations are strictly rejected by the isolation fence.",
                "timeout_ms": "integer: Query execution timeout limit bounded between 100 and 5000 milliseconds.",
            },
            compact_description="Run SQL SELECT query.",
            compact_parameters={"query": "str", "timeout_ms": "int"},
        ),
        ToolSchemaDefinition(
            name="search_codebase",
            description="Performs semantic AST search across all repository source trees indexing definitions and symbols.",
            parameters={
                "pattern": "string: Exact regex or semantic identifier.",
                "max_results": "integer: Upper cap on returned match entries.",
            },
            compact_description="Search code symbols.",
            compact_parameters={"pattern": "str", "max_results": "int"},
        ),
    ]

    # 1. Pro tier receives full descriptions
    pro_schemas = engine.compact_tool_schemas_for_tier(tools, ModelTier.PRO_REASONING)
    assert len(pro_schemas) == 2
    assert "sanitized SQL read query" in pro_schemas[0]["description"]
    assert "timeout limit bounded" in pro_schemas[0]["parameters"]

    # 2. Flash tier receives stripped compact schemas
    flash_schemas = engine.compact_tool_schemas_for_tier(tools, ModelTier.FLASH_LITE)
    assert len(flash_schemas) == 2
    assert flash_schemas[0]["description"] == "Run SQL SELECT query."
    assert flash_schemas[0]["parameters_summary"] == "query:str, timeout_ms:int"

    # Schema payload footprint is heavily compressed for Flash
    assert len(flash_schemas[0]["description"]) < len(pro_schemas[0]["description"])


def test_small_output_passthrough() -> None:
    """Verify tool outputs below offload byte threshold pass through directly without stubbing."""
    engine = ModelNativeToolPagingEngine(ToolPagingConfig(offload_byte_threshold=2048))
    session_id = "sess-paging-small"

    small_text = "Status: 200 OK\nItem count: 4\nExecution time: 12ms."
    card, is_offloaded, record = engine.process_tool_output(session_id, "get_health", small_text)

    assert not is_offloaded
    assert record is None
    assert card == small_text


def test_massive_output_stubbing_and_offload() -> None:
    """Verify massive multi-hundred-line outputs are automatically stubbed and stored in blob table."""
    engine = ModelNativeToolPagingEngine(ToolPagingConfig(offload_byte_threshold=1024, preview_line_count=3))
    session_id = "sess-paging-large"

    # Generate 300 lines of compilation output with an embedded error
    lines = [f"[INFO] Building crate module_{i}: compiled in 0.04s" for i in range(1, 200)]
    lines.append("[ERROR] crate module_142: syntax error on token ';' expected expression")
    lines.extend([f"[INFO] Building crate module_{i}: skipped" for i in range(201, 301)])
    massive_text = "\n".join(lines)

    card, is_offloaded, record = engine.process_tool_output(session_id, "cargo_build", massive_text)

    assert is_offloaded is True
    assert record is not None
    assert record.line_count == 300
    assert record.byte_size > 1024

    # Stub card must contain concise summary and blob ref
    assert "[Tool Output Offloaded: cargo_build" in card
    assert "blob://" in card
    assert "Found 1 errors in 300 lines" in card
    assert "[Preview]:" in card

    # Record must be retrievable from session virtual page table
    retrieved = engine.get_blob(session_id, record.blob_id)
    assert retrieved is not None
    assert retrieved.content == massive_text


def test_virtual_page_table_demand_page_in() -> None:
    """Verify line-sliced demand paging retrieves exact requested windows without full-document overhead."""
    engine = ModelNativeToolPagingEngine(ToolPagingConfig(offload_byte_threshold=500, max_page_lines=20))
    session_id = "sess-page-in-test"

    raw_lines = [f"Line {i:03d}: System telemetry metric sample data value {i * 10}" for i in range(1, 101)]
    full_output = "\n".join(raw_lines)

    _, is_offloaded, record = engine.process_tool_output(session_id, "dump_telemetry", full_output)
    assert is_offloaded is True
    assert record is not None
    blob_id = record.blob_id

    # Page in lines 45 to 55
    slice_window: PageInSlice = engine.page_in(
        session_id=session_id,
        blob_id=blob_id,
        start_line=45,
        end_line=55,
    )

    assert slice_window.blob_id == blob_id
    assert slice_window.start_line == 45
    assert slice_window.end_line == 55
    assert slice_window.total_lines == 100
    assert slice_window.lines_returned == 11
    assert "Line 045:" in slice_window.content_slice
    assert "Line 055:" in slice_window.content_slice
    assert "Line 044:" not in slice_window.content_slice
    assert "Line 056:" not in slice_window.content_slice
