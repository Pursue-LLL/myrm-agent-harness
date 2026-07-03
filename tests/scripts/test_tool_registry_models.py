"""Unit tests for scripts.tool_registry_models.

Pure dataclass logic — no AST, no filesystem, no subprocess.
Covers every branch of `ScanReport` invariants and internal filters.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from scripts.tool_registry_models import ScanReport, ToolDeclaration


def _decl(name: str, file: str = "/a.py", line: int = 1, kind: str = "decorator") -> ToolDeclaration:
    return ToolDeclaration(name=name, kind=kind, file=Path(file), line=line)


def test_declared_names_dedups_repeated_entries() -> None:
    """Two declarations with the same name collapse to one in declared_names."""
    report = ScanReport(
        declarations=[_decl("foo"), _decl("foo", file="/b.py"), _decl("bar")]
    )
    assert report.declared_names == {"foo", "bar"}


def test_missing_registrations_excludes_internal_prefix_and_explicit() -> None:
    """Tools starting with INTERNAL_TOOL_PREFIXES or in INTERNAL_TOOL_NAMES are skipped."""
    report = ScanReport(
        declarations=[
            _decl("real_tool"),
            _decl("_internal_helper"),
            _decl("_completion_check"),
        ],
        registered_names=set(),
    )
    assert report.missing_registrations() == {"real_tool"}


def test_missing_registrations_excludes_ptc_runtime_tools() -> None:
    """DW PTC bridge tools are runtime-only; not required in _TOOL_LAYERS."""
    report = ScanReport(
        declarations=[_decl("spawn_subagent"), _decl("notify"), _decl("registered_tool")],
        registered_names={"registered_tool"},
    )
    assert report.missing_registrations() == set()


def test_missing_registrations_empty_when_all_registered() -> None:
    report = ScanReport(
        declarations=[_decl("foo")],
        registered_names={"foo"},
    )
    assert report.missing_registrations() == set()


def test_ghost_registrations_filters_internal() -> None:
    """Registered names with no declaration are ghosts, unless internal."""
    report = ScanReport(
        declarations=[_decl("alive")],
        registered_names={"alive", "ghost", "submit_verdict"},
    )
    assert report.ghost_registrations() == {"ghost"}


def test_ghost_registrations_filters_schema_only_control_plane() -> None:
    """DR orchestrator signal tools are schema-only registry entries."""
    report = ScanReport(
        declarations=[_decl("alive")],
        registered_names={"alive", "dispatch_research", "think", "finalize_report"},
    )
    assert report.ghost_registrations() == set()


def test_ghost_registry_metadata_keys_flags_orphan_maps() -> None:
    """Permission/group maps must not reference tools with no source."""
    report = ScanReport(
        declarations=[_decl("alive")],
        registered_names={"alive", "submit_verdict"},
    )
    ghosts = report.ghost_registry_metadata_keys({"alive", "orphan_meta_key", "submit_verdict"})
    assert ghosts == {"orphan_meta_key"}


def test_orphan_factories_skips_whitelist_and_called() -> None:
    """Only factories with zero call sites AND not whitelisted are orphans."""
    report = ScanReport(
        factories={
            "create_browser_tools": Path("/whitelisted.py"),
            "create_orphan_tool": Path("/orphan.py"),
            "create_used_tool": Path("/used.py"),
        },
        factory_call_sites={
            "create_browser_tools": [],
            "create_orphan_tool": [],
            "create_used_tool": [Path("/caller.py")],
        },
    )
    assert report.orphan_factories() == {"create_orphan_tool"}


def test_duplicate_declarations_detects_cross_file_only() -> None:
    """Same name across files = duplicate; same file (rename pattern) = legitimate."""
    report = ScanReport(
        declarations=[
            _decl("dup", file="/a.py"),
            _decl("dup", file="/b.py"),
            _decl("self_rename", file="/c.py", line=1),
            _decl("self_rename", file="/c.py", line=2),
        ]
    )
    dupes = report.duplicate_declarations()
    assert "dup" in dupes and len(dupes["dup"]) == 2
    assert "self_rename" not in dupes


def test_duplicate_declarations_ignores_internal_names() -> None:
    """Internal tool name collisions are not flagged as duplicates."""
    report = ScanReport(
        declarations=[
            _decl("_completion_check", file="/a.py"),
            _decl("_completion_check", file="/b.py"),
        ]
    )
    assert report.duplicate_declarations() == {}


def test_tool_declaration_is_frozen() -> None:
    """ToolDeclaration is frozen — mutation must raise."""
    decl = _decl("foo")
    with pytest.raises((AttributeError, TypeError)):
        decl.name = "bar"  # type: ignore[misc]


def test_scan_report_defaults_are_empty_but_typed() -> None:
    """Default-constructed ScanReport never returns None for collections."""
    report = ScanReport()
    assert report.declarations == []
    assert report.registered_names == set()
    assert report.factories == {}
    assert report.factory_call_sites == {}
    assert report.files_scanned == 0
    assert report.declared_names == set()
    assert report.missing_registrations() == set()
    assert report.ghost_registrations() == set()
    assert report.orphan_factories() == set()
    assert report.duplicate_declarations() == {}
