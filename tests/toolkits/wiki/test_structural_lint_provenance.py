"""Tests for provenance gap structural lint."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.wiki.core.config import WikiConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.diagnostics.structural_lint import (
    collect_provenance_gap_issues,
    collect_structural_lint_snapshot,
)
from myrm_agent_harness.toolkits.wiki.maintenance.linter import WikiLinter
from myrm_agent_harness.toolkits.wiki.maintenance.modes import MaintainMode


class _NoopLlm:
    async def ainvoke(self, _messages: list[object]) -> object:
        class _Resp:
            content = "NO_DRIFT"

        return _Resp()


@pytest.fixture
def wiki_structure(tmp_path: Path) -> WikiStructure:
    structure = WikiStructure(tmp_path / "vault")
    structure.ensure_structure()
    return structure


def test_provenance_gap_flags_missing_sources_for_compiled(
    wiki_structure: WikiStructure,
) -> None:
    concept = wiki_structure.concepts_dir / "policy.md"
    concept.write_text(
        "---\ntitle: Policy\ntype: concept\nprovenance: compiled\n---\n\nBody",
        encoding="utf-8",
    )

    issues = collect_provenance_gap_issues(wiki_structure)

    assert len(issues) == 1
    assert issues[0].issue_type == "provenance_gap"
    assert issues[0].action_kind == "navigate"


def test_provenance_gap_flags_missing_raw_file(wiki_structure: WikiStructure) -> None:
    concept = wiki_structure.concepts_dir / "policy.md"
    concept.write_text(
        "---\ntitle: Policy\ntype: concept\nprovenance: compiled\nsources:\n  - missing.md\n---\n\nBody",
        encoding="utf-8",
    )

    issues = collect_provenance_gap_issues(wiki_structure)

    assert len(issues) == 1
    assert "missing.md" in issues[0].description


def test_provenance_gap_skips_chat_save(wiki_structure: WikiStructure) -> None:
    concept = wiki_structure.concepts_dir / "note.md"
    concept.write_text(
        "---\ntitle: Note\ntype: concept\nprovenance: chat-save\n---\n\nSaved from chat",
        encoding="utf-8",
    )

    issues = collect_provenance_gap_issues(wiki_structure)

    assert issues == []


def test_provenance_gap_passes_when_raw_source_exists(
    wiki_structure: WikiStructure,
) -> None:
    raw_file = wiki_structure.raw_dir / "policy.md"
    raw_file.write_text("raw policy", encoding="utf-8")
    concept = wiki_structure.concepts_dir / "policy.md"
    concept.write_text(
        "---\ntitle: Policy\ntype: concept\nprovenance: compiled\nsources:\n  - policy.md\n---\n\nBody",
        encoding="utf-8",
    )

    issues = collect_provenance_gap_issues(wiki_structure)

    assert issues == []


def test_provenance_gap_flags_unknown_provenance_without_sources(
    wiki_structure: WikiStructure,
) -> None:
    concept = wiki_structure.concepts_dir / "typo.md"
    concept.write_text(
        "---\ntitle: Typo\ntype: concept\nprovenance: compilled\n---\n\nBody",
        encoding="utf-8",
    )

    issues = collect_provenance_gap_issues(wiki_structure)

    assert len(issues) == 1
    assert "compilled" in issues[0].description


def test_provenance_gap_accepts_http_source(wiki_structure: WikiStructure) -> None:
    concept = wiki_structure.concepts_dir / "web.md"
    concept.write_text(
        "---\ntitle: Web\ntype: concept\nprovenance: web_fetch\nsources:\n  - https://example.com/doc\n---\n\nBody",
        encoding="utf-8",
    )

    issues = collect_provenance_gap_issues(wiki_structure)

    assert issues == []


def test_provenance_gap_accepts_string_sources_metadata(
    wiki_structure: WikiStructure,
) -> None:
    raw_file = wiki_structure.raw_dir / "note.md"
    raw_file.write_text("raw note", encoding="utf-8")
    concept = wiki_structure.concepts_dir / "string-source.md"
    concept.write_text(
        "---\ntitle: String Source\ntype: concept\nprovenance: compiled\nsources: note.md\n---\n\nBody",
        encoding="utf-8",
    )

    issues = collect_provenance_gap_issues(wiki_structure)

    assert issues == []


def test_provenance_gap_flags_invalid_raw_source_path(wiki_structure: WikiStructure) -> None:
    concept = wiki_structure.concepts_dir / "traversal.md"
    concept.write_text(
        "---\ntitle: Traversal\ntype: concept\nprovenance: compiled\nsources:\n  - ../outside.md\n---\n\nBody",
        encoding="utf-8",
    )

    issues = collect_provenance_gap_issues(wiki_structure)

    assert len(issues) == 1
    assert "outside.md" in issues[0].description


def test_provenance_gap_accepts_raw_prefixed_source_path(
    wiki_structure: WikiStructure,
) -> None:
    raw_file = wiki_structure.raw_dir / "prefixed.md"
    raw_file.write_text("raw", encoding="utf-8")
    concept = wiki_structure.concepts_dir / "prefixed.md"
    concept.write_text(
        "---\ntitle: Prefixed\ntype: concept\nprovenance: compiled\nsources:\n  - raw/prefixed.md\n---\n\nBody",
        encoding="utf-8",
    )

    issues = collect_provenance_gap_issues(wiki_structure)

    assert issues == []


@pytest.mark.asyncio
async def test_scan_includes_provenance_gap(wiki_structure: WikiStructure) -> None:
    concept = wiki_structure.concepts_dir / "orphan.md"
    concept.write_text(
        "---\ntitle: Orphan\ntype: concept\n---\n\nObsidian manual import",
        encoding="utf-8",
    )

    linter = WikiLinter(_NoopLlm(), wiki_structure, WikiConfig())
    issues, _raw_scan = await linter.scan(MaintainMode.STRUCTURAL, include_raw_security=False)

    assert any(issue.issue_type == "provenance_gap" for issue in issues)


def test_provenance_gap_truncates_many_missing_sources(
    wiki_structure: WikiStructure,
) -> None:
    concept = wiki_structure.concepts_dir / "policy.md"
    concept.write_text(
        "---\n"
        "title: Policy\n"
        "type: concept\n"
        "provenance: compiled\n"
        "sources:\n"
        "  - a.md\n"
        "  - b.md\n"
        "  - c.md\n"
        "  - d.md\n"
        "---\n\nBody",
        encoding="utf-8",
    )

    issues = collect_provenance_gap_issues(wiki_structure)

    assert len(issues) == 1
    assert "+1 more" in issues[0].description


def test_provenance_gap_skips_unreadable_concept(
    wiki_structure: WikiStructure,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    concept = wiki_structure.concepts_dir / "locked.md"
    concept.write_text(
        "---\ntitle: Locked\ntype: concept\nprovenance: compiled\n---\n\nBody",
        encoding="utf-8",
    )

    original_read_text = Path.read_text

    def _read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self.name == "locked.md":
            raise OSError("permission denied")
        return original_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", _read_text)

    issues = collect_provenance_gap_issues(wiki_structure)

    assert issues == []


def test_collect_structural_lint_snapshot_counts_provenance_gaps(
    wiki_structure: WikiStructure,
) -> None:
    concept = wiki_structure.concepts_dir / "gap.md"
    concept.write_text(
        "---\ntitle: Gap\ntype: concept\nprovenance: compiled\n---\n\nBody",
        encoding="utf-8",
    )

    snapshot = collect_structural_lint_snapshot(wiki_structure)

    assert snapshot.provenance_gaps == 1
    assert snapshot.has_issues() is True
