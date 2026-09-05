"""Tests for core.artifacts.architecture_ir — structured JSON IR and pre-delivery validation."""

from __future__ import annotations

from myrm_agent_harness.core.artifacts.architecture_ir import (
    ArchitectureEdge,
    ArchitectureGroup,
    ArchitectureIR,
    ArchitectureNode,
    ArchitectureNodeType,
    DiagramType,
    ValidationReceipt,
    validate_and_sanitize_architecture_ir,
)


def test_valid_architecture_ir_parsing() -> None:
    raw_payload = {
        "title": "Sample System",
        "diagram_type": "architecture",
        "nodes": [
            {"id": "web", "label": "Web Frontend", "type": "frontend"},
            {"id": "api", "label": "API Gateway", "type": "gateway"},
            {"id": "db", "label": "PostgreSQL", "type": "database"},
        ],
        "edges": [
            {"source": "web", "target": "api", "protocol": "HTTPS"},
            {"source": "api", "target": "db", "protocol": "SQL"},
        ],
        "groups": [
            {"id": "core", "label": "Core Cluster"},
        ],
    }

    ir, receipt = validate_and_sanitize_architecture_ir(raw_payload)
    assert ir is not None
    assert receipt.is_valid is True
    assert receipt.node_count == 3
    assert receipt.edge_count == 2
    assert receipt.sanitized_dangling_edges == 0
    assert len(receipt.isolated_nodes) == 0


def test_dangling_edge_sanitization() -> None:
    raw_payload = {
        "title": "System with Dangling Edge",
        "diagram_type": "architecture",
        "nodes": [
            {"id": "node1", "label": "Node 1"},
            {"id": "node2", "label": "Node 2"},
        ],
        "edges": [
            {"source": "node1", "target": "node2"},
            {"source": "node1", "target": "nonexistent_node"},
        ],
    }

    ir, receipt = validate_and_sanitize_architecture_ir(raw_payload)
    assert ir is not None
    assert receipt.is_valid is True
    assert receipt.edge_count == 1
    assert receipt.sanitized_dangling_edges == 1
    assert any("Dangling edge removed" in w for w in receipt.warnings)


def test_isolated_node_detection() -> None:
    raw_payload = {
        "title": "System with Isolated Node",
        "nodes": [
            {"id": "connected_1", "label": "Node 1"},
            {"id": "connected_2", "label": "Node 2"},
            {"id": "isolated_node", "label": "Isolated Node"},
        ],
        "edges": [
            {"source": "connected_1", "target": "connected_2"},
        ],
    }

    ir, receipt = validate_and_sanitize_architecture_ir(raw_payload)
    assert ir is not None
    assert "isolated_node" in receipt.isolated_nodes


def test_duplicate_node_id_deduplication() -> None:
    raw_payload = {
        "title": "System with Duplicates",
        "nodes": [
            {"id": "dup", "label": "First"},
            {"id": "dup", "label": "Second"},
        ],
        "edges": [],
    }

    ir, receipt = validate_and_sanitize_architecture_ir(raw_payload)
    assert ir is not None
    assert receipt.node_count == 1
    assert any("Duplicate node ID detected" in w for w in receipt.warnings)


def test_invalid_json_handling() -> None:
    ir, receipt = validate_and_sanitize_architecture_ir("not valid json")
    assert ir is None
    assert receipt.is_valid is False
    assert any("Invalid JSON" in e for e in receipt.errors)


def test_empty_nodes_validation() -> None:
    raw_payload = {
        "title": "Empty System",
        "nodes": [],
        "edges": [],
    }

    ir, receipt = validate_and_sanitize_architecture_ir(raw_payload)
    assert receipt.is_valid is False
    assert any("contains zero valid nodes" in e for e in receipt.errors)
