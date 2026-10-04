"""Regression tests for the inline-link and TS-extension support added to
``scripts/md_ref_validator.py``.

Covers the behaviours that the backtick-only validator lacked: ``[label](path)``
extraction, tsconfig-style source-file table anchoring, placeholder-row
skipping, extension probing for import-notation refs, and the guard that stops
progressive stripping from reducing a ref to a parent marker."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_repo_root))

from scripts.md_ref_validator import (
    _extract_md_refs,
    _path_exists,
    _progressive_paths,
    scan_md_refs,
)

_TOP_DIRS = frozenset({"agent", "api", "core", "runtime", "toolkits"})


@pytest.mark.architecture
def test_extract_md_refs_captures_inline_links(tmp_path: Path) -> None:
    """Inline ``[label](path)`` and image links feed the same pipeline as
    backtick spans; anchors, external URLs, and extension-less labels are
    dropped while a bare filename carrying a file extension is kept."""
    md = tmp_path / "doc.md"
    md.write_text(
        "See [guide](./sub/guide.md) and ![diagram](./assets/diagram.png).\n"
        "Anchor [top](#overview), external [site](https://example.com/x.md), "
        "anchor-strip [sec](./sub/guide.md#part) cover.\n"
        "Bare [readme](README.md) is a leaf file target, "
        "label [go](nowhere) carries no extension.\n",
        encoding="utf-8",
    )
    refs = _extract_md_refs(md, frozenset())
    assert [(ref, line) for ref, line, _ in refs] == [
        ("./sub/guide.md", 1),
        ("./assets/diagram.png", 1),
        ("./sub/guide.md", 2),
        ("README.md", 3),
    ]


@pytest.mark.architecture
def test_extract_md_refs_skips_symbolic_placeholder_rows(tmp_path: Path) -> None:
    """Rows whose first cell carries a ``{placeholder}`` are illustrative
    patterns (``sections/{group}/X.tsx``), so their refs are not checked."""
    md = tmp_path / "doc.md"
    md.write_text(
        "| `sections/{group}/X.tsx` | `sections/SettingsSection` | `../SettingsSection` |\n"
        "| `sections/ai-core/Y.tsx`  | `sections/SettingsSection` | `../SettingsSection` |\n",
        encoding="utf-8",
    )
    refs = _extract_md_refs(md, frozenset())
    assert not any(line == 1 for _, line, _ in refs)


@pytest.mark.architecture
def test_extract_md_refs_row_dir_from_source_file_cell(tmp_path: Path) -> None:
    """Import-specifier tables anchor refs to the first cell's source file: the
    segment matching the md's own directory is stripped before resolving."""
    sections = tmp_path / "sections"
    sections.mkdir()
    md = sections / "_ARCH.md"
    md.write_text(
        "| `sections/{group}/X.tsx` | t | `../SettingsSection` |\n"
        "| `sections/ai-core/Y.tsx` | t | `../SettingsSection` |\n",
        encoding="utf-8",
    )
    refs = _extract_md_refs(md, frozenset())
    assert ("../SettingsSection", 2, "ai-core") in refs


@pytest.mark.architecture
def test_path_exists_probes_ts_extensions(tmp_path: Path) -> None:
    """Extension-less refs written in import notation resolve to their TS/JS
    source file; genuinely missing refs stay unresolved."""
    (tmp_path / "useMessageQueue.ts").write_text("", encoding="utf-8")
    (tmp_path / "Component.tsx").write_text("", encoding="utf-8")
    (tmp_path / "legacy.js").write_text("", encoding="utf-8")
    assert _path_exists(tmp_path, "./useMessageQueue")
    assert _path_exists(tmp_path, "./Component")
    assert _path_exists(tmp_path, "./legacy")
    assert not _path_exists(tmp_path, "./ghost")


@pytest.mark.architecture
def test_progressive_paths_never_strips_parent_markers() -> None:
    """Stripping must never reduce a path to a parent marker (``../..``) or an
    elision (``...``); those trivially "exist" as directories and mask bugs."""
    assert _progressive_paths("../../SettingsSection") == ["../../SettingsSection"]
    assert _progressive_paths("../common/...") == ["../common/..."]


@pytest.mark.architecture
def test_extract_md_refs_keeps_dynamic_segments(tmp_path: Path) -> None:
    """Bracketed dynamic path segments (``[chatId]``) are part of the path and
    must still be extracted and resolvable, not dropped as noise."""
    (tmp_path / "app" / "mobile" / "[chatId]").mkdir(parents=True)
    (tmp_path / "app" / "mobile" / "[chatId]" / "page.tsx").write_text("", encoding="utf-8")
    md = tmp_path / "doc.md"
    md.write_text("| `./app/mobile/[chatId]/page.tsx` | 路由页 |\n", encoding="utf-8")
    refs = _extract_md_refs(md, frozenset())
    assert [(ref, line) for ref, line, _ in refs] == [("./app/mobile/[chatId]/page.tsx", 1)]


def test_extract_md_refs_skips_non_utf8(tmp_path: Path) -> None:
    """Non-UTF-8 markdown (fixtures/binary dumps) is skipped, not fatal."""
    md = tmp_path / "bad.md"
    md.write_bytes(b"\xff\xfe`./x.py`\n")
    assert _extract_md_refs(md, frozenset()) == []


@pytest.mark.architecture
def test_bare_filename_links_are_validated(tmp_path: Path) -> None:
    """A bare leaf filename link resolves against the md's own directory: an
    existing sibling passes while a missing one is reported broken. A plain
    backtick mention of the same name stays unchecked (prose, not navigation)."""
    (tmp_path / "sibling.md").write_text("", encoding="utf-8")
    md = tmp_path / "doc.md"
    md.write_text(
        "OK [a](sibling.md), broken [b](missing.md), prose `missing.md` here.\n",
        encoding="utf-8",
    )
    reports = scan_md_refs(tmp_path, monorepo_root=tmp_path, repo_root=tmp_path)
    broken = [(ref, line) for report in reports for ref, line in report.broken_refs]
    assert broken == [("missing.md", 1)]
