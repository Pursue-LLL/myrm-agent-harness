"""Tool registry consistency assertions.

Closes the loop that pre-commit and CI workflow open: even if a developer
bypasses local hooks (`--no-verify`) or pushes directly to a non-protected
branch, this `pytest -m architecture` test still gates merges and releases.

Architecture Reference: src/myrm_agent_harness/agent/tool_management/_ARCH.md
Usage Guide: scripts/validate_tool_registry.py --help
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from scripts.tool_registry_engine import scan


@pytest.fixture(scope="module")
def report():
    """Run the full scan once and share the report across cases."""
    return scan()


@pytest.mark.architecture
def test_no_missing_registrations(report) -> None:
    """Every declared @tool / BaseTool / module-level tool assignment must be
    present in `_TOOL_LAYERS` (or in the server bootstrap).
    """
    missing = report.missing_registrations()
    assert not missing, (
        "Tools declared in code but missing from _TOOL_LAYERS:\n"
        + "\n".join(f"  - {name}" for name in sorted(missing))
        + "\nFix: register via register_tool_layer() in tool_layers.py "
        "(harness) or _tool_layer_bootstrap.py (server)."
    )


@pytest.mark.architecture
def test_no_ghost_registrations(report) -> None:
    """`_TOOL_LAYERS` must not list names that no source file declares;
    such entries waste prompt cache and mislead docs."""
    ghosts = report.ghost_registrations()
    assert not ghosts, (
        "Tools registered in _TOOL_LAYERS but never declared in code:\n"
        + "\n".join(f"  - {name}" for name in sorted(ghosts))
        + "\nFix: drop the dead entry from tool_layers.py / bootstrap."
    )


@pytest.mark.architecture
def test_no_orphan_factories(report) -> None:
    """Every `create_*_tool(s)` factory must be invoked from at least one
    startup path or appear in `ORPHAN_FACTORY_WHITELIST` with justification."""
    orphans = report.orphan_factories()
    assert not orphans, (
        "Tool factory functions with zero call sites:\n"
        + "\n".join(
            f"  - {factory}  (defined @ {report.factories[factory].relative_to(_repo_root.parent)})"
            for factory in sorted(orphans)
        )
        + "\nFix: wire the factory into get_meta_tools() or delete the dead code. "
        "Intentionally unused factories must be added to ORPHAN_FACTORY_WHITELIST."
    )


@pytest.mark.architecture
def test_no_duplicate_tool_names(report) -> None:
    """The same tool name declared from multiple files would silently
    overwrite the prior entry in the runtime registry."""
    dupes = report.duplicate_declarations()
    assert not dupes, (
        "Identical tool names declared in multiple files:\n"
        + "\n".join(
            f"  - {name}\n"
            + "\n".join(
                f"      {decl.file.relative_to(_repo_root.parent)}:{decl.line}"
                for decl in decls
            )
            for name, decls in sorted(dupes.items())
        )
        + "\nFix: rename one of the colliding tools."
    )
