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


def test_build_doc_block_emits_canonical_markers_and_breakdown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Marker fences must be exact strings so re-runs are idempotent."""
    import scripts.validate_tool_registry as cli

    monkeypatch.setattr(
        cli,
        "_layer_counts",
        lambda _report: {"CORE": 2, "COMMON": 6, "EXTENDED": 71},
    )
    block = _build_doc_block(ScanReport())
    assert block.startswith(_BLOCK_BEGIN)
    assert block.endswith(_BLOCK_END)
    assert "**79**" in block
    assert "CORE 2 + COMMON 6 + EXTENDED 71" in block


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
    assert err is not None and "TOOL_COUNT markers" in err


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
        cli, "_layer_counts", lambda _r: {"CORE": 1, "COMMON": 1, "EXTENDED": 1}
    )
    report = ScanReport(declarations=[_decl("foo")], registered_names={"foo"})
    out = _format_report(report)
    assert "PASS - tool registry consistent" in out


def test_format_report_reports_missing_with_owner_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.validate_tool_registry as cli

    monkeypatch.setattr(
        cli, "_layer_counts", lambda _r: {"CORE": 0, "COMMON": 0, "EXTENDED": 0}
    )
    src_file = _repo_root / "scripts" / "tool_registry_models.py"
    report = ScanReport(
        declarations=[ToolDeclaration(name="never_registered", kind="decorator", file=src_file, line=10)],
        registered_names=set(),
    )
    out = _format_report(report)
    assert "FAIL" in out and "never_registered" in out


def test_format_report_incremental_suppresses_ghost_and_orphan(monkeypatch: pytest.MonkeyPatch) -> None:
    """Incremental scan only sees a subset of files, so ghost/orphan would be
    misleading false positives — they must be silently suppressed."""
    import scripts.validate_tool_registry as cli

    monkeypatch.setattr(
        cli, "_layer_counts", lambda _r: {"CORE": 0, "COMMON": 0, "EXTENDED": 0}
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
        cli, "_layer_counts", lambda _r: {"CORE": 0, "COMMON": 0, "EXTENDED": 0}
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


def _run_main(monkeypatch: pytest.MonkeyPatch, argv: list[str], **scan_kwargs: object) -> tuple[int, str, str]:
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
        cli, "_layer_counts", lambda _r: {"CORE": 1, "COMMON": 1, "EXTENDED": 1}
    )
    monkeypatch.setattr(cli.sys, "argv", ["validate_tool_registry.py", *argv])
    capsys = scan_kwargs["capsys"]
    rc = cli.main()
    out, err = capsys.readouterr()  # type: ignore[union-attr]
    return rc, out, err


def test_main_full_pass(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
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
    assert payload["layer_counts"] == {"CORE": 1, "COMMON": 1, "EXTENDED": 1}


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
    monkeypatch.setattr(cli, "_DOC_TARGETS", (bad_doc,))
    rc, _, err = _run_main(
        monkeypatch,
        ["--generate-docs"],
        report=ScanReport(declarations=[_decl("foo")], registered_names={"foo"}),
        capsys=capsys,
    )
    assert rc == 1
    assert "missing TOOL_COUNT markers" in err


def test_main_generate_docs_rewrites_existing_marker_block(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import scripts.validate_tool_registry as cli

    good_doc = tmp_path / "good.md"
    good_doc.write_text(f"intro\n{_BLOCK_BEGIN}\nold body\n{_BLOCK_END}\noutro\n")
    monkeypatch.setattr(cli, "_DOC_TARGETS", (good_doc,))
    rc, out, _ = _run_main(
        monkeypatch,
        ["--generate-docs"],
        report=ScanReport(declarations=[_decl("foo")], registered_names={"foo"}),
        capsys=capsys,
    )
    assert rc == 0
    assert "Updated TOOL_COUNT blocks" in out
    refreshed = good_doc.read_text()
    assert "Tools registered:" in refreshed
    assert "old body" not in refreshed
