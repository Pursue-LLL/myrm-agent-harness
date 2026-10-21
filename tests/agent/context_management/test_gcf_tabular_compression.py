"""Unit tests for GCF (Grid-Column Format) tabular lossless compression engine."""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
from myrm_agent_harness.agent.context_management.pipeline.processors.gcf_tabular_codec import (
    GcfTabularCodec,
)
from myrm_agent_harness.agent.context_management.pipeline.processors.gcf_tabular_compress_processor import (
    GcfTabularCompressProcessor,
)
from myrm_agent_harness.agent.context_management.pipeline.processors.gcf_tabular_types import (
    GcfColumnarTable,
    GcfCompressionGuardConfig,
)


def test_gcf_flatten_and_unflatten_nested_dict() -> None:
    nested = {
        "user": {
            "id": 101,
            "profile": {
                "name": "Alice",
                "role": "Admin",
            },
        },
        "status": "active",
    }
    flattened = GcfTabularCodec.flatten_dict(nested)
    assert flattened == {
        "user.id": 101,
        "user.profile.name": "Alice",
        "user.profile.role": "Admin",
        "status": "active",
    }
    restored = GcfTabularCodec.unflatten_dict(flattened)
    assert restored == nested


def test_gcf_encode_and_decode_object_array_lossless_roundtrip() -> None:
    records: list[dict[str, object]] = [
        {"id": 1, "username": "alice", "meta": {"dept": "eng", "level": "L5"}},
        {"id": 2, "username": "bob", "meta": {"dept": "design", "level": "L4"}},
        {"id": 3, "username": "charlie", "meta": {"dept": "qa", "level": "L3"}},
        {"id": 4, "username": "diana", "meta": {"dept": "product", "level": "L6"}},
        {"id": 5, "username": "evan", "meta": {"dept": "sales", "level": "L2"}},
    ]

    cfg = GcfCompressionGuardConfig(min_rows=3, min_savings_chars=20)
    result = GcfTabularCodec.encode_object_array(records, config=cfg)

    assert result.is_compressed is True
    assert result.cols_count == 4  # id, username, meta.dept, meta.level
    assert result.rows_count == 5
    assert result.saved_chars > 20
    assert result.compression_ratio > 0.15

    # Check tabular content
    parsed = json.loads(result.compressed_text)
    assert "_cols" in parsed
    assert "_rows" in parsed

    # Decode back
    table = GcfColumnarTable(cols=parsed["_cols"], rows=parsed["_rows"])
    restored = GcfTabularCodec.decode_to_object_array(table, unflatten_dot_paths=True)
    assert restored == records


def test_gcf_guard_heterogeneity_and_min_rows_bypass() -> None:
    # 1. Min rows bypass
    small_records: list[dict[str, object]] = [
        {"id": 1, "name": "foo"},
        {"id": 2, "name": "bar"},
    ]
    res_min_rows = GcfTabularCodec.encode_object_array(
        small_records, config=GcfCompressionGuardConfig(min_rows=3)
    )
    assert res_min_rows.is_compressed is False
    assert "min_rows_threshold_unmet" in str(res_min_rows.bypass_reason)

    # 2. Heterogeneous objects bypass
    hetero_records: list[dict[str, object]] = [
        {"a": 1, "b": 2},
        {"c": 3, "d": 4},
        {"e": 5, "f": 6},
        {"g": 7, "h": 8},
    ]
    res_hetero = GcfTabularCodec.encode_object_array(
        hetero_records, config=GcfCompressionGuardConfig(max_heterogeneity_rate=0.25)
    )
    assert res_hetero.is_compressed is False
    assert "heterogeneity_threshold_exceeded" in str(res_hetero.bypass_reason)


def test_gcf_markdown_and_csv_tabular_text_bridge() -> None:
    md_table = """
| user_id | score | active |
| --- | --- | --- |
| 1001 | 95 | true |
| 1002 | 88 | false |
| 1003 | 72 | true |
| 1004 | 99 | true |
"""
    res_md = GcfTabularCodec.encode_tabular_text(
        md_table, config=GcfCompressionGuardConfig(min_savings_chars=5)
    )
    assert res_md.is_compressed is True
    assert res_md.cols_count == 3
    assert res_md.rows_count == 4

    csv_data = "col1,col2,col3\nval1,val2,val3\nval4,val5,val6\nval7,val8,val9\nval10,val11,val12\n"
    res_csv = GcfTabularCodec.encode_tabular_text(
        csv_data, config=GcfCompressionGuardConfig(min_savings_chars=5)
    )
    assert res_csv.is_compressed is True
    assert res_csv.cols_count == 3
    assert res_csv.rows_count == 4


@pytest.mark.asyncio
async def test_gcf_tabular_compress_processor_pipeline_integration() -> None:
    table_payload = json.dumps(
        [
            {"sku": "SKU-001", "name": "Widget A", "price": 19.99, "stock": 100},
            {"sku": "SKU-002", "name": "Widget B", "price": 29.99, "stock": 50},
            {"sku": "SKU-003", "name": "Widget C", "price": 39.99, "stock": 25},
            {"sku": "SKU-004", "name": "Widget D", "price": 49.99, "stock": 10},
        ]
    )

    messages = [
        HumanMessage(content="Query the stock list"),
        AIMessage(content="Fetching from inventory tool"),
        ToolMessage(content=table_payload, tool_call_id="call_inventory_1"),
    ]

    proc = GcfTabularCompressProcessor(
        config=GcfCompressionGuardConfig(min_rows=3, min_savings_chars=10)
    )
    context = ProcessorContext(messages=messages, user_query="Query the stock list")

    assert await proc.should_process(context) is True
    processed_context = await proc.process(context)

    # ToolMessage should be compressed into GCF format
    compressed_content = str(processed_context.messages[2].content)
    assert "_cols" in compressed_content
    assert "_rows" in compressed_content
    assert "SKU-001" in compressed_content

    # Metadata metrics recorded
    assert processed_context.metadata.get("gcf_tabular_compressed_count") == 1
    assert int(processed_context.metadata.get("gcf_tabular_saved_chars", 0)) > 10
