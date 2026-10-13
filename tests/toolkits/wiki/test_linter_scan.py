"""Tests for WikiLinter.scan separation."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.wiki.core.config import WikiConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.maintenance.linter import WikiLinter
from myrm_agent_harness.toolkits.wiki.maintenance.modes import MaintainMode


class _NoopLlm:
    async def ainvoke(self, _messages: list[object]) -> object:
        class _Resp:
            content = "NO_DRIFT"

        return _Resp()


@pytest.mark.asyncio
async def test_scan_structural_skips_raw_security_mutation(tmp_path: Path) -> None:
    base = tmp_path / "vault"
    structure = WikiStructure(base_dir=base)
    structure.ensure_structure()
    concept = structure.concepts_dir / "alpha.md"
    concept.write_text(
        "---\ntitle: Alpha\ntype: concept\n---\n\nShort [[missing]]\n",
        encoding="utf-8",
    )

    linter = WikiLinter(_NoopLlm(), structure, WikiConfig())
    issues, raw_scan = await linter.scan(MaintainMode.STRUCTURAL, include_raw_security=False)

    assert raw_scan == {}
    assert any(issue.issue_type == "broken_wikilink" for issue in issues)
    assert all(issue.action_kind in {"repair", "recompile", "navigate", "info"} for issue in issues)


class _StubIndexer:
    def graph_insights(self) -> dict[str, list[dict[str, object]]]:
        return {
            "knowledge_gaps": [
                {"node": "notes/alone", "type": "isolated", "degree": 0},
                {"node": "shared/public-page", "type": "isolated", "degree": 1},
            ],
            "unexpected_connections": [],
            "communities": [],
        }


@pytest.mark.asyncio
async def test_scan_reports_knowledge_gaps_only_for_local_pages(tmp_path: Path) -> None:
    structure = WikiStructure(base_dir=tmp_path / "vault")
    structure.ensure_structure()
    local = structure.get_concept_file_path("notes/alone")
    local.write_text("---\ntitle: Alone\ntype: concept\n---\n\nBody.\n", encoding="utf-8")

    linter = WikiLinter(_NoopLlm(), structure, WikiConfig(), indexer=_StubIndexer())  # type: ignore[arg-type]
    issues, _ = await linter.scan(MaintainMode.STRUCTURAL)

    assert [issue.location for issue in issues if issue.issue_type == "knowledge_gap"] == ["notes/alone"]
