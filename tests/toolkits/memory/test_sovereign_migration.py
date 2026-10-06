# [POS]: tests/toolkits/memory/test_sovereign_migration.py
# [INPUT]: pathlib.Path, tempfile, pytest, myrm_agent_harness.toolkits.memory.sovereign_migration
# [OUTPUT]: test_path_relativizer, test_bundle_export_and_restore_cycle, test_bundle_tamper_protection, test_competitor_ingestion_adapter
"""Unit test suite for sovereign asset migration and cross-machine restore protocol.

Validates path relativization, atomic bundle export/restore, SHA-256 integrity checks,
and competitor ingestion adapters (Hermes, Claude Code, Codex).
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import tarfile
import tempfile
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory.sovereign_migration import (
    AssetCategory,
    CompetitorIngestionAdapter,
    CompetitorType,
    ExportBundleRequest,
    ExportBundleResult,
    PathRelativizer,
    RestoreBundleRequest,
    RestoreBundleResult,
    SovereignBundleArchiver,
    SovereignBundleRestorer,
)


def test_path_relativizer() -> None:
    """Verify PathRelativizer replaces absolute host paths with placeholder and rebinds them."""
    source_root = "/Users/alice/projects/vortex"
    target_root = "/home/bob/workspace/vortex"

    original_text = (
        "Memory record refers to /Users/alice/projects/vortex/src/main.py and "
        "another file at /Users/alice/projects/vortex/docs/arch.md."
    )

    # 1. Relativize
    relativized, count = PathRelativizer.relativize_text(original_text, source_root)
    assert count == 2
    assert "${MYRM_WORKSPACE}/src/main.py" in relativized
    assert "${MYRM_WORKSPACE}/docs/arch.md" in relativized
    assert "/Users/alice" not in relativized

    # 2. Rebind on new host
    rebound, count_rebind = PathRelativizer.rebind_text(
        text=relativized,
        source_root=source_root,
        target_root=target_root,
    )
    assert count_rebind == 2
    assert "/home/bob/workspace/vortex/src/main.py" in rebound
    assert "/home/bob/workspace/vortex/docs/arch.md" in rebound
    assert "${MYRM_WORKSPACE}" not in rebound


def test_bundle_export_and_restore_cycle() -> None:
    """Verify full end-to-end export -> package (.myrmpkg) -> restore cycle."""
    with tempfile.TemporaryDirectory() as td_src, tempfile.TemporaryDirectory() as td_dst:
        src_path = Path(td_src)
        dst_path = Path(td_dst)

        # 1. Populate mock source workspace with memories, skills, and hardcoded absolute paths
        wiki_dir = src_path / "wiki"
        wiki_dir.mkdir(parents=True, exist_ok=True)
        sample_page = wiki_dir / "Architecture.md"
        sample_page.write_text(
            f"# Core Architecture\nPath in memory: {src_path}/src/service.py\nRules defined.",
            encoding="utf-8",
        )

        skill_dir = src_path / "skills" / "deployer"
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "run.py"
        skill_file.write_text("print('Deploying...')\n", encoding="utf-8")

        bundle_archive = src_path / "export_backup.myrmpkg"

        # 2. Export package
        archiver = SovereignBundleArchiver()
        export_req = ExportBundleRequest(
            source_dir=str(src_path),
            output_bundle_path=str(bundle_archive),
            include_categories=[AssetCategory.WIKI_MEMORY, AssetCategory.CUSTOM_SKILL],
            custom_description="Test export package",
        )
        export_res: ExportBundleResult = archiver.export_bundle(export_req)

        assert export_res.success is True
        assert export_res.asset_count >= 2
        assert export_res.sha256 != ""
        assert bundle_archive.exists()

        # 3. Restore package onto destination host
        restorer = SovereignBundleRestorer()
        restore_req = RestoreBundleRequest(
            bundle_path=str(bundle_archive),
            target_destination_dir=str(dst_path),
            current_workspace_root=str(dst_path),
            overwrite_existing=True,
        )
        restore_res: RestoreBundleResult = restorer.restore_bundle(restore_req)

        assert restore_res.success is True
        assert restore_res.remapped_paths_count >= 1
        assert len(restore_res.restored_assets) >= 2

        # 4. Verify restored content has paths remapped
        restored_wiki = dst_path / "wiki" / "Architecture.md"
        assert restored_wiki.exists()
        restored_text = restored_wiki.read_text(encoding="utf-8")
        assert f"{dst_path}/src/service.py" in restored_text
        assert str(src_path) not in restored_text


def test_bundle_tamper_protection() -> None:
    """Verify SovereignBundleRestorer detects corrupted or modified files and refuses restoration."""
    with tempfile.TemporaryDirectory() as td_src, tempfile.TemporaryDirectory() as td_dst:
        src_path = Path(td_src)
        dst_path = Path(td_dst)

        wiki_dir = src_path / "wiki"
        wiki_dir.mkdir(parents=True, exist_ok=True)
        (wiki_dir / "Note.md").write_text("Original note content", encoding="utf-8")

        bundle_archive = src_path / "tamper_test.myrmpkg"
        archiver = SovereignBundleArchiver()
        archiver.export_bundle(
            ExportBundleRequest(
                source_dir=str(src_path),
                output_bundle_path=str(bundle_archive),
            )
        )

        # Tamper the package by corrupting the archive header
        raw_bytes = bytearray(bundle_archive.read_bytes())
        # Corrupt first 30 bytes including gzip magic header
        for i in range(min(30, len(raw_bytes))):
            raw_bytes[i] = 0x00
        bundle_archive.write_bytes(bytes(raw_bytes))

        restorer = SovereignBundleRestorer()
        with pytest.raises((tarfile.ReadError, ValueError, Exception)):
            restorer.restore_bundle(
                RestoreBundleRequest(
                    bundle_path=str(bundle_archive),
                    target_destination_dir=str(dst_path),
                    current_workspace_root=str(dst_path),
                )
            )


def test_competitor_ingestion_adapter() -> None:
    """Verify CompetitorIngestionAdapter detects and translates Hermes, Claude Code, and Codex assets."""
    with tempfile.TemporaryDirectory() as td_home, tempfile.TemporaryDirectory() as td_ws, tempfile.TemporaryDirectory() as td_target:
        home_path = Path(td_home).resolve()
        ws_path = Path(td_ws).resolve()
        target_path = Path(td_target).resolve()

        # 1. Setup mock Hermes directory
        hermes_dir = home_path / ".hermes"
        hermes_dir.mkdir(parents=True, exist_ok=True)
        (hermes_dir / "config.yaml").write_text("model: gpt-4o\ntemperature: 0.2\n", encoding="utf-8")
        hermes_mem = hermes_dir / "memories"
        hermes_mem.mkdir(parents=True, exist_ok=True)
        (hermes_mem / "user_pref.md").write_text("User likes concise responses", encoding="utf-8")

        # 2. Setup mock Claude Code rule
        claude_rule = ws_path / "CLAUDE.md"
        claude_rule.write_text("Always write python unit tests using pytest.", encoding="utf-8")

        # 3. Setup mock Codex rule
        codex_rule = ws_path / "AGENTS.md"
        codex_rule.write_text("Follow architecture rules defined in repository.", encoding="utf-8")

        adapter = CompetitorIngestionAdapter()
        detect_res = adapter.detect(home_dir=home_path, workspace_root=ws_path)

        assert CompetitorType.HERMES in detect_res.detected_competitors
        assert CompetitorType.CLAUDE_CODE in detect_res.detected_competitors
        assert CompetitorType.CODEX in detect_res.detected_competitors
        assert detect_res.hermes_dir == str(hermes_dir)

        # 4. Ingest Hermes
        res_hermes = adapter.ingest(
            competitor=CompetitorType.HERMES,
            source_path=hermes_dir,
            target_destination_dir=target_path,
        )
        assert res_hermes.success is True
        assert res_hermes.imported_memories_count == 1
        assert (target_path / "wiki_memory_data" / "user_pref.md").exists()
        assert (target_path / "rules" / "hermes_config.yaml").exists()

        # 5. Ingest Claude Code
        res_claude = adapter.ingest(
            competitor=CompetitorType.CLAUDE_CODE,
            source_path=claude_rule,
            target_destination_dir=target_path,
        )
        assert res_claude.success is True
        assert (target_path / "rules" / "claude_code_rule.md").exists()

        # 6. Ingest Codex
        res_codex = adapter.ingest(
            competitor=CompetitorType.CODEX,
            source_path=codex_rule,
            target_destination_dir=target_path,
        )
        assert res_codex.success is True
        assert (target_path / "rules" / "codex_rule.md").exists()
