"""Integration tests for code_graph — full pipeline without mocks.

Exercises the complete chain:
  create_code_graph_tools → code_graph_build → code_graph_query
using a real temporary workspace with Python files, real Tree-sitter parsing,
real SQLite storage, and real analysis/search modules.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.code_graph.code_graph_agent_tools import (
    create_code_graph_tools,
)

_SAMPLE_PROJECT = {
    "src/main.py": """\
from src.utils import calculate_total
from src.models import User

def main():
    user = User("Alice", 30)
    total = calculate_total([10, 20, 30])
    print(f"User: {user.name}, Total: {total}")

if __name__ == "__main__":
    main()
""",
    "src/utils.py": """\
def calculate_total(items: list[int]) -> int:
    return sum(items)

def format_currency(amount: float) -> str:
    return f"${amount:.2f}"

class MathHelper:
    @staticmethod
    def square(n: int) -> int:
        return n * n

    @staticmethod
    def cube(n: int) -> int:
        return n * n * n
""",
    "src/models.py": """\
class User:
    def __init__(self, name: str, age: int):
        self.name = name
        self.age = age

    def greet(self) -> str:
        return f"Hello, {self.name}!"

    def is_adult(self) -> bool:
        return self.age >= 18

class Admin(User):
    def __init__(self, name: str, age: int, role: str):
        super().__init__(name, age)
        self.role = role

    def permissions(self) -> list[str]:
        return ["read", "write", "admin"]
""",
    "tests/test_utils.py": """\
from src.utils import calculate_total, format_currency, MathHelper

def test_calculate_total():
    assert calculate_total([1, 2, 3]) == 6

def test_format_currency():
    assert format_currency(99.9) == "$99.90"

def test_square():
    assert MathHelper.square(3) == 9
""",
}


def _tree_sitter_available() -> bool:
    try:
        import tree_sitter_language_pack  # noqa: F401
        return True
    except ImportError:
        return False


def _create_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "project"
    for rel_path, content in _SAMPLE_PROJECT.items():
        fpath = ws / rel_path
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(content, encoding="utf-8")
    return ws


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return _create_workspace(tmp_path)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture
def tools(workspace: Path, data_dir: Path) -> list:
    return create_code_graph_tools(workspace, data_dir)


def _invoke_tool(tools: list, name: str, **kwargs: str | int) -> dict:
    for t in tools:
        if t.name == name:
            return json.loads(t.invoke(kwargs))
    raise ValueError(f"Tool {name} not found")


@pytest.mark.skipif(
    not _tree_sitter_available(),
    reason="tree-sitter-language-pack not installed",
)
class TestFullPipelineIntegration:
    """End-to-end: build → query across all operations."""

    def test_build_full_then_stats(self, tools: list) -> None:
        result = _invoke_tool(tools, "code_graph_build", mode="full")
        assert result["status"] == "success"
        assert result["files_processed"] >= 3
        assert result["nodes_added"] >= 5
        assert result["edges_added"] >= 1

        stats = _invoke_tool(tools, "code_graph_query", operation="stats")
        assert stats["nodes"] >= 5
        assert stats["edges"] >= 1
        assert stats["files"] >= 3

    def test_query_before_build_returns_error(
        self, workspace: Path, tmp_path: Path,
    ) -> None:
        fresh_data = tmp_path / "fresh_data"
        fresh_data.mkdir()
        fresh_tools = create_code_graph_tools(workspace, fresh_data)

        result = _invoke_tool(fresh_tools, "code_graph_query", operation="stats")
        assert "error" in result
        assert "not built" in result["error"].lower()

    def test_callers_query(self, tools: list) -> None:
        _invoke_tool(tools, "code_graph_build", mode="full")

        result = _invoke_tool(
            tools, "code_graph_query",
            operation="callers",
            target="src/utils.py::calculate_total",
        )
        assert "callers" in result
        assert isinstance(result["callers"], list)

    def test_callers_without_target_returns_error(self, tools: list) -> None:
        _invoke_tool(tools, "code_graph_build", mode="full")

        result = _invoke_tool(
            tools, "code_graph_query",
            operation="callers",
            target="",
        )
        assert "error" in result

    def test_dependencies_query(self, tools: list) -> None:
        _invoke_tool(tools, "code_graph_build", mode="full")

        result = _invoke_tool(
            tools, "code_graph_query",
            operation="dependencies",
            target="src/main.py::main",
        )
        assert "dependencies" in result
        assert isinstance(result["dependencies"], list)

    def test_impact_radius_query(self, tools: list) -> None:
        _invoke_tool(tools, "code_graph_build", mode="full")

        result = _invoke_tool(
            tools, "code_graph_query",
            operation="impact_radius",
            target="src/utils.py::calculate_total",
        )
        assert "target" in result
        assert "affected_count" in result
        assert "affected_files" in result
        assert isinstance(result["affected_files"], list)

    def test_impact_radius_without_target_returns_error(self, tools: list) -> None:
        _invoke_tool(tools, "code_graph_build", mode="full")

        result = _invoke_tool(
            tools, "code_graph_query",
            operation="impact_radius",
            target="",
        )
        assert "error" in result

    def test_structure_search(self, tools: list) -> None:
        _invoke_tool(tools, "code_graph_build", mode="full")

        result = _invoke_tool(
            tools, "code_graph_query",
            operation="structure_search",
            target="calculate",
        )
        assert "results" in result
        assert len(result["results"]) >= 1
        names = [r["name"] for r in result["results"]]
        assert any("calculate" in n for n in names)

    def test_structure_search_without_query_returns_error(self, tools: list) -> None:
        _invoke_tool(tools, "code_graph_build", mode="full")

        result = _invoke_tool(
            tools, "code_graph_query",
            operation="structure_search",
            target="",
        )
        assert "error" in result

    def test_execution_flows_entry_points(self, tools: list) -> None:
        _invoke_tool(tools, "code_graph_build", mode="full")

        result = _invoke_tool(
            tools, "code_graph_query",
            operation="execution_flows",
        )
        assert "entry_points" in result
        assert isinstance(result["entry_points"], list)

    def test_execution_flows_with_target(self, tools: list) -> None:
        _invoke_tool(tools, "code_graph_build", mode="full")

        result = _invoke_tool(
            tools, "code_graph_query",
            operation="execution_flows",
            target="src/main.py::main",
        )
        assert "entry_point" in result
        assert "steps" in result

    def test_hotspots_query(self, tools: list) -> None:
        _invoke_tool(tools, "code_graph_build", mode="full")

        result = _invoke_tool(
            tools, "code_graph_query",
            operation="hotspots",
        )
        assert "hotspots" in result
        assert "total_nodes" in result
        assert "total_edges" in result

    def test_unknown_operation_returns_error(self, tools: list) -> None:
        _invoke_tool(tools, "code_graph_build", mode="full")

        result = _invoke_tool(
            tools, "code_graph_query",
            operation="nonexistent_operation",
        )
        assert "error" in result
        assert "Unknown operation" in result["error"]

    def test_incremental_build(
        self, workspace: Path, data_dir: Path, tools: list,
    ) -> None:
        _invoke_tool(tools, "code_graph_build", mode="full")
        stats_before = _invoke_tool(tools, "code_graph_query", operation="stats")

        new_file = workspace / "src" / "new_module.py"
        new_file.write_text(
            "def new_function():\n    return 42\n\ndef another():\n    return new_function()\n",
            encoding="utf-8",
        )

        result = _invoke_tool(
            tools, "code_graph_build", mode="incremental",
        )
        assert result["status"] == "success"

    def test_build_error_handling(
        self, tmp_path: Path,
    ) -> None:
        empty_ws = tmp_path / "empty_workspace"
        empty_ws.mkdir()
        empty_data = tmp_path / "empty_data"
        empty_data.mkdir()

        empty_tools = create_code_graph_tools(empty_ws, empty_data)
        result = _invoke_tool(empty_tools, "code_graph_build", mode="full")
        assert result["status"] == "success"
        assert result["files_processed"] == 0

    def test_dedup_consistency(self, tools: list) -> None:
        """Build twice, edges should not duplicate."""
        _invoke_tool(tools, "code_graph_build", mode="full")
        stats1 = _invoke_tool(tools, "code_graph_query", operation="stats")

        _invoke_tool(tools, "code_graph_build", mode="full")
        stats2 = _invoke_tool(tools, "code_graph_query", operation="stats")

        assert stats1["nodes"] == stats2["nodes"]
        assert stats1["edges"] == stats2["edges"]

    def test_dependencies_without_target_returns_error(self, tools: list) -> None:
        _invoke_tool(tools, "code_graph_build", mode="full")
        result = _invoke_tool(
            tools, "code_graph_query",
            operation="dependencies", target="",
        )
        assert "error" in result

    def test_structure_search_with_kind_filter(self, tools: list) -> None:
        _invoke_tool(tools, "code_graph_build", mode="full")
        result = _invoke_tool(
            tools, "code_graph_query",
            operation="structure_search",
            target="User",
            kind_filter="Class",
        )
        assert "results" in result

    def test_structure_search_with_file_filter(self, tools: list) -> None:
        _invoke_tool(tools, "code_graph_build", mode="full")
        result = _invoke_tool(
            tools, "code_graph_query",
            operation="structure_search",
            target="calculate",
            file_filter="utils",
        )
        assert "results" in result

    def test_impact_radius_with_max_depth(self, tools: list) -> None:
        _invoke_tool(tools, "code_graph_build", mode="full")
        result = _invoke_tool(
            tools, "code_graph_query",
            operation="impact_radius",
            target="src/models.py::User",
            max_depth=1,
        )
        assert "target" in result
        assert isinstance(result["depth_reached"], int)

    def test_stats_shows_correct_file_count(self, tools: list) -> None:
        _invoke_tool(tools, "code_graph_build", mode="full")
        stats = _invoke_tool(tools, "code_graph_query", operation="stats")
        assert stats["files"] >= 3

    def test_callers_returns_correct_structure(self, tools: list) -> None:
        _invoke_tool(tools, "code_graph_build", mode="full")
        result = _invoke_tool(
            tools, "code_graph_query",
            operation="callers",
            target="src/utils.py::calculate_total",
        )
        if result.get("callers"):
            caller = result["callers"][0]
            assert "source_qualified" in caller
            assert "kind" in caller
            assert "file_path" in caller

    def test_hotspots_returns_node_centrality(self, tools: list) -> None:
        _invoke_tool(tools, "code_graph_build", mode="full")
        result = _invoke_tool(
            tools, "code_graph_query",
            operation="hotspots",
            max_results=5,
        )
        assert result["total_nodes"] >= 5
        if result["hotspots"]:
            h = result["hotspots"][0]
            assert "qualified_name" in h
            assert "in_degree" in h
            assert "out_degree" in h
            assert "is_hub" in h
            assert "is_bridge" in h
