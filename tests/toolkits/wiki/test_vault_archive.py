"""Tests for wiki vault portability archive export."""

from __future__ import annotations

import json
import zipfile

import pytest

from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.portability import EXPORT_MANIFEST_VERSION, build_vault_archive_zip


@pytest.fixture
def temp_vault(tmp_path) -> WikiStructure:
    structure = WikiStructure(tmp_path / "agent-vault")
    structure.ensure_structure()
    concept_path = structure.get_concept_file_path("AI/Test")
    concept_path.write_text("---\ntype: concept\n---\n\n# Test\n", encoding="utf-8")
    raw_path = structure.get_raw_file_path("note.md")
    raw_path.write_text("raw body", encoding="utf-8")
    structure.get_index_file_path().write_text("# Index\n", encoding="utf-8")
    structure.get_log_file_path().write_text("# Log\n", encoding="utf-8")
    structure.get_hot_file_path().write_text("# Hot\n", encoding="utf-8")
    structure.wiki_dir.joinpath(".metadata.json").write_text("{}", encoding="utf-8")
    assets_dir = structure.wiki_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    (assets_dir / "diagram.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return structure


def test_build_vault_archive_zip_includes_raw_wiki_and_manifest(temp_vault: WikiStructure) -> None:
    archive = build_vault_archive_zip(temp_vault, agent_id="agent-a")
    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
        assert "wiki/concepts/ai/test.md" in names
        assert "raw/note.md" in names
        assert "wiki/index.md" in names
        assert "wiki/log.md" in names
        assert "wiki/hot.md" in names
        assert "wiki/assets/diagram.png" in names
        assert "wiki/.metadata.json" not in names
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["version"] == EXPORT_MANIFEST_VERSION
        assert manifest["agent_id"] == "agent-a"


def test_build_vault_archive_zip_accepts_extra_entries(temp_vault: WikiStructure) -> None:
    archive = build_vault_archive_zip(
        temp_vault,
        extra_entries={".obsidian/graph.json": "{}"},
    )
    with zipfile.ZipFile(archive) as zf:
        assert ".obsidian/graph.json" in zf.namelist()
