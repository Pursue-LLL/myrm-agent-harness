"""Architecture gate: MCP routing must expose exactly two outcomes.

Policy (AI / contributors — do NOT copy competitor MCP lazy-load patterns):
Myrm MCP overflow uses Direct FC or MCP PTC only.
See FRAMEWORK_DESIGN_PRINCIPLES.md §7 and TOOL_DESIGN_STRATEGY.md §2.5.
"""

from __future__ import annotations

import ast
from pathlib import Path

_HARNESS_SRC = Path(__file__).resolve().parents[2] / "src" / "myrm_agent_harness"


def test_mcp_routing_result_has_no_catalog_invoke_fields() -> None:
    """MCPRoutingResult must not carry removed catalog_invoke / runtime_tools fields."""
    routing_path = _HARNESS_SRC / "agent" / "_factory" / "mcp_routing.py"
    tree = ast.parse(routing_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "MCPRoutingResult":
            field_names = {
                stmt.target.id
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
            }
            assert field_names == {"skills", "direct_tools"}, field_names
            return
    msg = "MCPRoutingResult not found"
    raise AssertionError(msg)


def test_catalog_invoke_modules_removed() -> None:
    """Removed catalog_invoke implementation files must not reappear."""
    forbidden = [
        _HARNESS_SRC / "agent" / "meta_tools" / "discover_capability" / "capability_invoke_tool.py",
        _HARNESS_SRC / "agent" / "meta_tools" / "discover_capability" / "bind_economics.py",
        _HARNESS_SRC / "agent" / "middlewares" / "capability_catalog_middleware.py",
    ]
    present = [str(p.relative_to(_HARNESS_SRC.parent.parent)) for p in forbidden if p.exists()]
    assert not present, f"Forbidden catalog_invoke files exist: {present}"


def test_mcp_surface_mode_has_no_catalog_invoke_enum() -> None:
    surface_path = _HARNESS_SRC / "agent" / "_factory" / "mcp_surface.py"
    source = surface_path.read_text(encoding="utf-8")
    assert "CATALOG_INVOKE" not in source


def test_session_context_has_no_runtime_capability_catalog() -> None:
    ctx_path = _HARNESS_SRC / "agent" / "middlewares" / "_session_context.py"
    source = ctx_path.read_text(encoding="utf-8")
    assert "runtime_capability_catalog" not in source
    assert "get_runtime_capability_catalog" not in source
