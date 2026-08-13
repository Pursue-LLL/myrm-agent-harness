"""Unit tests for the validate_tool_registry CLI helpers.

Targets pure functions (`_build_doc_block`, `_update_doc_block`,
`_filter_report_to_files`, `_format_report`, `_layer_counts`). Subprocess
behaviour is covered by the architecture test that invokes the full scan.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from scripts.tool_registry_models import ScanReport, ToolDeclaration
from scripts.validate_tool_registry import (
    _BLOCK_BEGIN,
    _BLOCK_END,
    _build_doc_block,
    _filter_report_to_files,
    _format_report,
    _update_doc_block,
)


def _decl(name: str, file: str = "/a.py", line: int = 1) -> ToolDeclaration:
    return ToolDeclaration(name=name, kind="decorator", file=Path(file), line=line)


def test_build_doc_block_emits_canonical_markers_and_breakdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Marker fences must be exact strings so re-runs are idempotent."""
    import scripts.validate_tool_registry as cli

    monkeypatch.setattr(
        cli,
        "_layer_counts",
        lambda _report: {"CORE": 2, "COMMON": 6, "EXTENDED": 71, "EXTERNAL": 0},
    )
    block = _build_doc_block(ScanReport())
    assert block.startswith(_BLOCK_BEGIN)
    assert block.endswith(_BLOCK_END)
    assert "**79**" in block
    assert "CORE 2 + COMMON 6 + EXTENDED 71" in block
    assert "PTC runtime tools: **" in block
    assert "`spawn_subagent`" in block


def test_update_doc_block_writes_when_markers_present(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text(f"head\n{_BLOCK_BEGIN}\nold\n{_BLOCK_END}\ntail\n")
    changed, err = _update_doc_block(doc, f"{_BLOCK_BEGIN}\nnew\n{_BLOCK_END}")
    assert changed is True
    assert err is None
    assert "new" in doc.read_text()


def test_update_doc_block_returns_error_on_missing_marker(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text("no markers here\n")
    changed, err = _update_doc_block(doc, "anything")
    assert changed is False
    assert err is not None and "TOOL_COUNT_BEGIN" in err


def test_update_doc_block_returns_error_on_missing_file(tmp_path: Path) -> None:
    changed, err = _update_doc_block(tmp_path / "absent.md", "anything")
    assert changed is False
    assert err is not None and "missing" in err


def test_update_doc_block_idempotent_when_already_current(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    block = f"{_BLOCK_BEGIN}\nsame\n{_BLOCK_END}"
    doc.write_text(f"head\n{block}\ntail\n")
    changed, err = _update_doc_block(doc, block)
    assert changed is False
    assert err is None


def test_filter_report_to_files_preserves_global_registry() -> None:
    """`registered_names` must stay full so newly-added @tools are still detected."""
    full = ScanReport(
        declarations=[_decl("a", file="/x.py"), _decl("b", file="/y.py")],
        registered_names={"a", "b", "c"},
        factories={"create_x_tool": Path("/x.py"), "create_y_tool": Path("/y.py")},
        factory_call_sites={"create_x_tool": [], "create_y_tool": []},
        files_scanned=99,
    )
    filtered = _filter_report_to_files(full, {Path("/x.py")})
    assert filtered.declared_names == {"a"}
    assert filtered.registered_names == {"a", "b", "c"}
    assert "create_x_tool" in filtered.factories
    assert "create_y_tool" not in filtered.factories
    assert filtered.files_scanned == 1


def test_format_report_pass_path(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.validate_tool_registry as cli

    monkeypatch.setattr(
        cli, "_layer_counts", lambda _r: {"CORE": 1, "COMMON": 1, "EXTENDED": 1, "EXTERNAL": 0}
    )
    report = ScanReport(declarations=[_decl("foo")], registered_names={"foo"})
    out = _format_report(report)
    assert "PASS - tool registry consistent" in out


def test_format_report_reports_missing_with_owner_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.validate_tool_registry as cli

    monkeypatch.setattr(
        cli, "_layer_counts", lambda _r: {"CORE": 0, "COMMON": 0, "EXTENDED": 0, "EXTERNAL": 0}
    )
    src_file = _repo_root / "scripts" / "tool_registry_models.py"
    report = ScanReport(
        declarations=[
            ToolDeclaration(
                name="never_registered", kind="decorator", file=src_file, line=10
            )
        ],
        registered_names=set(),
    )
    out = _format_report(report)
    assert "FAIL" in out and "never_registered" in out


def test_format_report_incremental_suppresses_ghost_and_orphan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Incremental scan only sees a subset of files, so ghost/orphan would be
    misleading false positives — they must be silently suppressed."""
    import scripts.validate_tool_registry as cli

    monkeypatch.setattr(
        cli, "_layer_counts", lambda _r: {"CORE": 0, "COMMON": 0, "EXTENDED": 0, "EXTERNAL": 0}
    )
    report = ScanReport(
        declarations=[_decl("foo")],
        registered_names={"foo", "ghost_tool"},
        factories={"create_orphan_tool": Path("/x.py")},
        factory_call_sites={"create_orphan_tool": []},
    )
    out = _format_report(report, incremental=True)
    assert "(incremental)" in out
    assert "ghost_tool" not in out
    assert "create_orphan_tool" not in out
    assert "PASS" in out


def test_format_report_reports_ghosts_and_orphans_and_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full mode emits the FAIL block for every category that has findings."""
    import scripts.validate_tool_registry as cli

    monkeypatch.setattr(
        cli, "_layer_counts", lambda _r: {"CORE": 0, "COMMON": 0, "EXTENDED": 0, "EXTERNAL": 0}
    )
    src_a = _repo_root / "scripts" / "tool_registry_engine.py"
    src_b = _repo_root / "scripts" / "tool_registry_models.py"
    report = ScanReport(
        declarations=[
            ToolDeclaration(name="dup_tool", kind="decorator", file=src_a, line=1),
            ToolDeclaration(name="dup_tool", kind="decorator", file=src_b, line=2),
        ],
        registered_names={"dup_tool", "ghost_only"},
        factories={"create_dead_tool": src_a},
        factory_call_sites={"create_dead_tool": []},
    )
    out = _format_report(report)
    assert "ghost_only" in out
    assert "create_dead_tool" in out
    assert "dup_tool" in out
    assert "FAIL" in out


def _run_main(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], **scan_kwargs: object
) -> tuple[int, str, str]:
    """Drive `main()` with synthetic argv and a stubbed `scan()`."""
    import scripts.validate_tool_registry as cli

    fake_report = scan_kwargs.get("report", ScanReport(registered_names=set()))

    def _fake_scan() -> ScanReport:
        result = scan_kwargs.get("side_effect")
        if isinstance(result, Exception):
            raise result
        return fake_report  # type: ignore[return-value]

    monkeypatch.setattr(cli, "scan", _fake_scan)
    monkeypatch.setattr(
        cli, "_layer_counts", lambda _r: {"CORE": 1, "COMMON": 1, "EXTENDED": 1, "EXTERNAL": 0}
    )
    # main() compares real TOOL_* maps against the stubbed scan report; isolate metadata.
    monkeypatch.setattr(
        cli,
        "_load_registry_metadata_keys",
        lambda: fake_report.declared_names | fake_report.registered_names,
    )
    monkeypatch.setattr(cli.sys, "argv", ["validate_tool_registry.py", *argv])
    capsys = scan_kwargs["capsys"]
    rc = cli.main()
    out, err = capsys.readouterr()  # type: ignore[union-attr]
    return rc, out, err


def test_main_incremental_runs_layer_product_gate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Incremental pre-commit must still fail on invalid COMMON layer assignments."""
    import scripts.validate_tool_registry as cli
    from myrm_agent_harness.agent.tool_management.tool_layers import (
        _TOOL_LAYERS,
        ToolLayer,
    )

    bad_layers = dict(_TOOL_LAYERS)
    bad_layers["todo_write"] = ToolLayer.COMMON

    monkeypatch.setattr(cli, "load_registered_layers", lambda: bad_layers)
    rc, out, _ = _run_main(
        monkeypatch,
        ["--incremental"],
        report=ScanReport(declarations=[_decl("foo")], registered_names={"foo"}),
        capsys=capsys,
    )
    assert rc == 1
    assert "todo_write" in out
    assert "tool catalog metadata" in out.lower() or "COMMON" in out


def test_main_full_pass(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, out, _ = _run_main(
        monkeypatch,
        [],
        report=ScanReport(declarations=[_decl("foo")], registered_names={"foo"}),
        capsys=capsys,
    )
    assert rc == 0
    assert "PASS" in out


def test_main_json_emits_mode_and_layer_counts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import json as _json

    rc, out, _ = _run_main(
        monkeypatch,
        ["--json"],
        report=ScanReport(declarations=[_decl("foo")], registered_names={"foo"}),
        capsys=capsys,
    )
    assert rc == 0
    payload = _json.loads(out)
    assert payload["mode"] == "full"
    assert payload["layer_counts"] == {
        "CORE": 1,
        "COMMON": 1,
        "EXTENDED": 1,
        "EXTERNAL": 0,
    }


def test_main_returns_2_on_scanner_crash(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, _, err = _run_main(
        monkeypatch,
        [],
        side_effect=RuntimeError("boom"),
        capsys=capsys,
    )
    assert rc == 2
    assert "Internal error" in err


def test_main_generate_docs_exit_1_when_marker_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import scripts.validate_tool_registry as cli

    bad_doc = tmp_path / "no_markers.md"
    bad_doc.write_text("just text, no markers\n")
    bad_catalog = tmp_path / "no_catalog_markers.md"
    bad_catalog.write_text("just text\n")
    monkeypatch.setattr(cli, "_COUNT_DOC_TARGETS", (bad_doc,))
    monkeypatch.setattr(cli, "_CATALOG_DOC_TARGET", bad_catalog)
    rc, _, err = _run_main(
        monkeypatch,
        ["--generate-docs"],
        report=ScanReport(declarations=[_decl("foo")], registered_names={"foo"}),
        capsys=capsys,
    )
    assert rc == 1
    assert "TOOL_COUNT_BEGIN" in err or "TOOL_CATALOG_BEGIN" in err


def test_layer_counts_aggregates_registered_layers() -> None:
    import scripts.validate_tool_registry as cli

    counts = cli._layer_counts(ScanReport())
    assert counts["CORE"] >= 7
    assert counts["COMMON"] >= 4
    assert counts["EXTENDED"] >= 40
    assert (
        sum(counts.values())
        == counts["CORE"]
        + counts["COMMON"]
        + counts["EXTENDED"]
        + counts["EXTERNAL"]
    )


def test_load_registry_metadata_keys_includes_todo_write() -> None:
    import scripts.validate_tool_registry as cli

    keys = cli._load_registry_metadata_keys()
    assert "todo_write" in keys
    assert "web_search_tool" in keys


def test_check_default_enabled_product_parity_passes() -> None:
    import scripts.validate_tool_registry as cli

    errors = cli._check_default_enabled_product_parity()
    assert errors == []


def test_format_report_metadata_ghosts(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.validate_tool_registry as cli

    monkeypatch.setattr(
        cli, "_layer_counts", lambda _r: {"CORE": 0, "COMMON": 0, "EXTENDED": 0, "EXTERNAL": 0}
    )
    report = ScanReport(declarations=[_decl("foo")], registered_names={"foo"})
    out = _format_report(report, metadata_ghosts={"dead_meta_key"})
    assert "dead_meta_key" in out
    assert "registry metadata key" in out


def test_main_incremental_filters_to_changed_files(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import scripts.validate_tool_registry as cli
    from myrm_agent_harness.agent.tool_management.tool_layers import _TOOL_LAYERS

    src_a = _repo_root / "scripts" / "tool_registry_engine.py"
    src_b = _repo_root / "scripts" / "tool_registry_models.py"
    full = ScanReport(
        declarations=[
            ToolDeclaration(name="a", kind="decorator", file=src_a, line=1),
            ToolDeclaration(name="b", kind="decorator", file=src_b, line=2),
        ],
        registered_names={"a", "b"},
    )
    monkeypatch.setattr(cli, "scan", lambda: full)
    monkeypatch.setattr(cli, "get_changed_python_files", lambda _roots: [src_a])
    monkeypatch.setattr(cli, "load_registered_layers", lambda: dict(_TOOL_LAYERS))
    monkeypatch.setattr(
        cli, "_layer_counts", lambda _r: {"CORE": 1, "COMMON": 1, "EXTENDED": 1, "EXTERNAL": 0}
    )
    monkeypatch.setattr(cli.sys, "argv", ["validate_tool_registry.py", "--incremental"])
    rc = cli.main()
    out, _ = capsys.readouterr()
    assert rc == 0
    assert "(incremental)" in out
    assert "Files scanned: 1" in out


def test_main_prints_catalog_and_parity_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import scripts.validate_tool_registry as cli
    from myrm_agent_harness.agent.tool_management.tool_layers import (
        _TOOL_LAYERS,
        ToolLayer,
    )

    bad_layers = dict(_TOOL_LAYERS)
    bad_layers["todo_write"] = ToolLayer.COMMON
    monkeypatch.setattr(cli, "load_registered_layers", lambda: bad_layers)
    monkeypatch.setattr(
        cli, "_check_default_enabled_product_parity", lambda: ["parity drift"]
    )
    rc, out, _ = _run_main(
        monkeypatch,
        [],
        report=ScanReport(declarations=[_decl("foo")], registered_names={"foo"}),
        capsys=capsys,
    )
    assert rc == 1
    assert "tool catalog metadata" in out.lower()
    assert "parity drift" in out


def test_main_generate_docs_already_up_to_date(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import scripts.validate_tool_registry as cli

    good_doc = tmp_path / "good.md"
    good_doc.write_text(f"intro\n{_BLOCK_BEGIN}\nplaceholder\n{_BLOCK_END}\noutro\n")
    catalog_doc = tmp_path / "catalog.md"
    catalog_doc.write_text(
        "intro\n<!-- TOOL_CATALOG_BEGIN -->\nplaceholder\n<!-- TOOL_CATALOG_END -->\n"
    )
    monkeypatch.setattr(cli, "_COUNT_DOC_TARGETS", (good_doc,))
    monkeypatch.setattr(cli, "_CATALOG_DOC_TARGET", catalog_doc)
    report = ScanReport(declarations=[_decl("foo")], registered_names={"foo"})
    _run_main(
        monkeypatch,
        ["--generate-docs"],
        report=report,
        capsys=capsys,
    )
    rc, out, _ = _run_main(
        monkeypatch,
        ["--generate-docs"],
        report=report,
        capsys=capsys,
    )
    assert rc == 0
    assert "already up-to-date" in out


def test_main_generate_docs_rewrites_existing_marker_block(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import scripts.validate_tool_registry as cli

    good_doc = tmp_path / "good.md"
    good_doc.write_text(f"intro\n{_BLOCK_BEGIN}\nold body\n{_BLOCK_END}\noutro\n")
    monkeypatch.setattr(cli, "_COUNT_DOC_TARGETS", (good_doc,))
    catalog_doc = tmp_path / "catalog.md"
    catalog_doc.write_text(
        "intro\n<!-- TOOL_CATALOG_BEGIN -->\nold\n<!-- TOOL_CATALOG_END -->\n"
    )
    monkeypatch.setattr(cli, "_CATALOG_DOC_TARGET", catalog_doc)
    rc, out, _ = _run_main(
        monkeypatch,
        ["--generate-docs"],
        report=ScanReport(declarations=[_decl("foo")], registered_names={"foo"}),
        capsys=capsys,
    )
    assert rc == 0
    assert "Updated TOOL_COUNT blocks" in out
    refreshed = good_doc.read_text()
    assert "LLM tools:" in refreshed
    assert "old body" not in refreshed


# ---------------------------------------------------------------------------
# Governance coverage gate
# ---------------------------------------------------------------------------


def _governance_registry() -> "ModuleType":
    """Return the live tool_registry module so tests can monkeypatch constants."""
    from types import ModuleType

    from myrm_agent_harness.core.security import tool_registry

    assert isinstance(tool_registry, ModuleType)
    return tool_registry


def test_governance_coverage_passes_on_clean_metadata() -> None:
    import scripts.validate_tool_registry as cli

    errors, matrix = cli._check_governance_coverage()
    assert errors == []
    tool_coverage = matrix["tool_coverage"]
    for tool, meta in tool_coverage.items():  # type: ignore[union-attr]
        assert (
            meta["permission"] or meta["dynamic_resolved"] or meta["auto_approved_reason"]
        ), f"{tool} is governance-uncovered"


def test_governance_coverage_all_permission_types_ruled_or_whitelisted() -> None:
    """The 11 permission types must each have a DEFAULT_RULESET rule or a
    RULESET_COVERAGE_WHITELIST declaration (fail-closed baseline)."""
    from myrm_agent_harness.core.security.tool_registry import (
        RULESET_COVERAGE_WHITELIST,
        TOOL_PERMISSION_MAP,
    )
    from myrm_agent_harness.core.security.types import DEFAULT_RULESET

    ruleset_permissions = {rule.permission for rule in DEFAULT_RULESET}
    for perm in TOOL_PERMISSION_MAP.values():
        assert (
            perm in ruleset_permissions or perm in RULESET_COVERAGE_WHITELIST
        ), f"permission type {perm!r} has no rule or whitelist declaration"


def test_governance_coverage_flags_uncovered_builtin_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A new built-in tool with no mapping/dynamic branch/declaration must fail."""
    import scripts.validate_tool_registry as cli

    registry = _governance_registry()
    original = registry.BUILTIN_TOOL_NAMES
    registry.BUILTIN_TOOL_NAMES = frozenset(original | {"silent_new_tool"})
    try:
        errors, _ = cli._check_governance_coverage()
    finally:
        registry.BUILTIN_TOOL_NAMES = original
    assert any("silent_new_tool" in e and "fail-closed" in e for e in errors)


def test_governance_coverage_flags_invalid_approve_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.validate_tool_registry as cli

    registry = _governance_registry()
    original = registry.AUTO_APPROVED_BUILTIN_TOOLS
    registry.AUTO_APPROVED_BUILTIN_TOOLS = {
        **original,
        "silent_new_tool": "not_a_valid_reason",
    }
    try:
        errors, _ = cli._check_governance_coverage()
    finally:
        registry.AUTO_APPROVED_BUILTIN_TOOLS = original
    assert any(
        "silent_new_tool='not_a_valid_reason'" in e
        and "not in AUTO_APPROVE_REASONS" in e
        for e in errors
    )


def test_governance_coverage_flags_ghost_declaration(monkeypatch: pytest.MonkeyPatch) -> None:
    """An AUTO_APPROVED_BUILTIN_TOOLS key for a non-built-in tool must fail."""
    import scripts.validate_tool_registry as cli

    registry = _governance_registry()
    original = registry.AUTO_APPROVED_BUILTIN_TOOLS
    registry.AUTO_APPROVED_BUILTIN_TOOLS = {**original, "phantom_tool": "read_only"}
    try:
        errors, _ = cli._check_governance_coverage()
    finally:
        registry.AUTO_APPROVED_BUILTIN_TOOLS = original
    assert any("phantom_tool" in e and "non-built-in" in e for e in errors)


def test_governance_coverage_flags_uncovered_permission_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.validate_tool_registry as cli

    registry = _governance_registry()
    original = registry.RULESET_COVERAGE_WHITELIST
    registry.RULESET_COVERAGE_WHITELIST = {
        k: v for k, v in original.items() if k != "browser_read"
    }
    try:
        errors, _ = cli._check_governance_coverage()
    finally:
        registry.RULESET_COVERAGE_WHITELIST = original
    assert any("'browser_read'" in e and "no DEFAULT_RULESET rule" in e for e in errors)


def test_governance_coverage_flags_missing_canonical_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.validate_tool_registry as cli

    registry = _governance_registry()
    original = registry.TOOL_CANONICAL_PARAMS
    registry.TOOL_CANONICAL_PARAMS = {
        k: v for k, v in original.items() if k != "cron_manage_tool"
    }
    try:
        errors, _ = cli._check_governance_coverage()
    finally:
        registry.TOOL_CANONICAL_PARAMS = original
    assert any("cron_manage_tool" in e and "TOOL_CANONICAL_PARAMS" in e for e in errors)


def test_governance_coverage_matrix_contains_audit_fields() -> None:
    import scripts.validate_tool_registry as cli

    _, matrix = cli._check_governance_coverage()
    assert isinstance(matrix["builtin_tools"], list)
    assert isinstance(matrix["permission_type_coverage"], dict)
    assert matrix["tool_coverage"]["cron_manage_tool"] == {  # type: ignore[index]
        "permission": "cron_manage",
        "dynamic_resolved": False,
        "auto_approved_reason": None,
        "safety_declared": True,
        "canonical_params": ["action", "job_id", "name_filter"],
    }


def test_main_fails_and_prints_on_governance_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import scripts.validate_tool_registry as cli

    monkeypatch.setattr(
        cli, "_check_governance_coverage", lambda: (["governance drift"], {})
    )
    rc, out, _ = _run_main(
        monkeypatch,
        [],
        report=ScanReport(declarations=[_decl("foo")], registered_names={"foo"}),
        capsys=capsys,
    )
    assert rc == 1
    assert "governance drift" in out
    assert "governance coverage issue" in out


def test_main_json_emits_governance_coverage(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import json as _json

    rc, out, _ = _run_main(
        monkeypatch,
        ["--json"],
        report=ScanReport(declarations=[_decl("foo")], registered_names={"foo"}),
        capsys=capsys,
    )
    assert rc == 0
    payload = _json.loads(out)
    assert "governance_errors" in payload
    assert payload["governance_errors"] == []
    assert "tool_coverage" in payload["governance_coverage"]


def test_canonical_params_completed_for_management_tools() -> None:
    """The 12 previously-missing tools must have precise canonical params so
    allow-always hashing matches semantically, not by full-argument literal."""
    from myrm_agent_harness.core.security.tool_registry import TOOL_CANONICAL_PARAMS

    assert TOOL_CANONICAL_PARAMS["cron_manage_tool"] == [
        "action",
        "job_id",
        "name_filter",
    ]
    assert TOOL_CANONICAL_PARAMS["delegate_task_tool"] == ["mode", "agent_type"]
    assert TOOL_CANONICAL_PARAMS["delegate_to_agent_tool"] == ["agent_name"]
    assert TOOL_CANONICAL_PARAMS["subagent_control_tool"] == ["action", "task_id"]
    assert TOOL_CANONICAL_PARAMS["skill_manage_tool"] == ["action", "name"]
    assert TOOL_CANONICAL_PARAMS["skill_market_tool"] == ["action", "skill_id"]
    assert TOOL_CANONICAL_PARAMS["skill_select_tool"] == ["skill_ids"]
    assert TOOL_CANONICAL_PARAMS["todo_write"] == ["merge"]
    assert TOOL_CANONICAL_PARAMS["update_ui_data_tool"] == ["surface_id"]
    for control_signal in (
        "ask_question_tool",
        "complete_goal_tool",
        "render_ui_tool",
        "request_answer_user_tool",
    ):
        assert TOOL_CANONICAL_PARAMS[control_signal] == []
