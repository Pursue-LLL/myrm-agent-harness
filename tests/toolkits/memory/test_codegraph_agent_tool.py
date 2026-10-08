"""Tests for CodeGraph LangChain Agent Tool facade.

[INPUT]
- toolkits.memory.codegraph.ast_parser::AstTopologyExtractor
- toolkits.memory.codegraph.store::CodeGraphMemoryStore
- toolkits.memory.codegraph.tool::create_code_impact_tool

[OUTPUT]
- Pytest test cases verifying Agent runtime consumption of CodeGraph impact tool.
"""

from __future__ import annotations

import json

import pytest
from langchain_core.tools import BaseTool

from myrm_agent_harness.toolkits.memory.codegraph import (
    AstTopologyExtractor,
    CodeGraphMemoryStore,
    create_code_impact_tool,
)


@pytest.fixture
def sample_module_a() -> str:
    return """
def helper_calculate(x: int, y: int) -> int:
    '''Core utility function.'''
    return x + y

def unused_func() -> None:
    pass
"""


@pytest.fixture
def sample_module_b() -> str:
    return """
from module_a import helper_calculate

def compute_metrics(val: int) -> int:
    return helper_calculate(val, 42)

def run_pipeline() -> None:
    res = compute_metrics(10)
    print(res)
"""


def test_create_code_impact_tool_metadata(
    sample_module_a: str, sample_module_b: str
) -> None:
    """Verify tool metadata conform to LangChain BaseTool standards."""
    store = CodeGraphMemoryStore(repo_id="test_repo")
    extractor = AstTopologyExtractor()

    syms_a, edges_a = extractor.extract_from_source(sample_module_a, "module_a.py")
    store.index_file("module_a.py", syms_a, edges_a)

    syms_b, edges_b = extractor.extract_from_source(sample_module_b, "module_b.py")
    store.index_file("module_b.py", syms_b, edges_b)

    tool: BaseTool = create_code_impact_tool(store)

    assert tool.name == "analyze_code_impact"
    assert "blast radius" in tool.description.lower()
    assert tool.args_schema is not None


def test_code_impact_tool_invocation_flow(
    sample_module_a: str, sample_module_b: str
) -> None:
    """Verify agent invokes tool with valid arguments and receives structured JSON."""
    store = CodeGraphMemoryStore(repo_id="test_repo")
    extractor = AstTopologyExtractor()

    syms_a, edges_a = extractor.extract_from_source(sample_module_a, "module_a.py")
    store.index_file("module_a.py", syms_a, edges_a)

    syms_b, edges_b = extractor.extract_from_source(sample_module_b, "module_b.py")
    store.index_file("module_b.py", syms_b, edges_b)

    tool = create_code_impact_tool(store)
    raw_result = tool.invoke(
        {"symbol_name": "helper_calculate", "file_path": "module_a.py"}
    )

    assert isinstance(raw_result, str)
    data = json.loads(raw_result)

    assert data["target_symbol_name"] == "helper_calculate"
    assert data["file_path"] == "module_a.py"
    assert "module_b.py::compute_metrics" in data["direct_callers"]
    assert "module_b.py::run_pipeline" in data["indirect_callers"]
    assert "module_b.py" in data["affected_files"]
    assert data["blast_radius"] >= 3
    assert data["risk_level"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert isinstance(data["safety_recommendations"], list)
    assert len(data["safety_recommendations"]) > 0


def test_code_impact_tool_unindexed_symbol(sample_module_a: str) -> None:
    """Verify graceful assessment when querying a symbol not present in CodeGraph."""
    store = CodeGraphMemoryStore(repo_id="test_repo")
    extractor = AstTopologyExtractor()

    syms_a, edges_a = extractor.extract_from_source(sample_module_a, "module_a.py")
    store.index_file("module_a.py", syms_a, edges_a)

    tool = create_code_impact_tool(store)
    raw_result = tool.invoke({"symbol_name": "non_existent_function"})

    assert isinstance(raw_result, str)
    data = json.loads(raw_result)

    assert data["target_symbol_name"] == "non_existent_function"
    assert data["blast_radius"] == 0
    assert data["risk_level"] == "LOW"
    assert data["direct_callers"] == []
    assert data["indirect_callers"] == []
