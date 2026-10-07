"""[POS]: tests/unit/toolkits/memory/test_competitor_migration_suite.py
[INPUT]: None.
[OUTPUT]: Comprehensive unit tests for competitor memory asset detection, schema translation, and deduplication.
"""

from pathlib import Path

from myrm_agent_harness.toolkits.memory.migration import (
    CompetitorAssetScanner,
    CompetitorMigrationMetaTools,
    CompetitorMigrationService,
    CompetitorSourceKind,
    UniversalMemoryTranslator,
)


def test_asset_scanner_discovers_mock_artifacts(tmp_path: Path) -> None:
    """Verify scanner detects mock Hermes and OpenClaw assets accurately."""
    mock_home = tmp_path / "user_home"
    hermes_mem_dir = mock_home / ".hermes" / "memories"
    hermes_mem_dir.mkdir(parents=True)
    user_md = hermes_mem_dir / "USER.md"
    user_md.write_text(
        "# User Profile\n- 用户偏好简洁的代码风格\n- 常用 Python 与 TypeScript\n",
        encoding="utf-8",
    )

    openclaw_dir = mock_home / ".openclaw"
    openclaw_dir.mkdir(parents=True)
    openclaw_json = openclaw_dir / "memory.json"
    openclaw_json.write_text(
        '[{"id": "c1", "content": "工作日9点上班", "category": "user"}]',
        encoding="utf-8",
    )

    scanner = CompetitorAssetScanner(home_dir=mock_home)
    artifacts = scanner.scan()
    assert len(artifacts) >= 2

    hermes_art = next(a for a in artifacts if a.source_kind == CompetitorSourceKind.HERMES)
    openclaw_art = next(a for a in artifacts if a.source_kind == CompetitorSourceKind.OPENCLAW)
    assert hermes_art.estimated_entries >= 2
    assert openclaw_art.estimated_entries == 1


def test_universal_translator_hermes_and_openclaw(tmp_path: Path) -> None:
    """Verify translator maps markdown and JSON into normalized canonical schemas."""
    translator = UniversalMemoryTranslator()

    # 1. Hermes Markdown
    md_file = tmp_path / "MEMORY.md"
    md_file.write_text(
        "# User Identity\n- 用户是一名全栈工程师\n# Rules\n- 严禁使用 Any 类型标注\n",
        encoding="utf-8",
    )
    payloads_md = translator.translate_file(CompetitorSourceKind.HERMES, md_file)
    assert len(payloads_md) == 2

    p_profile = next(p for p in payloads_md if "全栈工程师" in p.normalized_content)
    p_rule = next(p for p in payloads_md if "严禁使用" in p.normalized_content)
    assert p_profile.layer_recommendation == "profile"
    assert p_rule.layer_recommendation == "procedural"
    assert p_profile.content_hash != ""

    # 2. OpenClaw JSON
    json_file = tmp_path / "claw.json"
    json_file.write_text(
        '{"memories": [{"id": "m1", "text": "早晨喝冰美式", "category": "user"}]}',
        encoding="utf-8",
    )
    payloads_json = translator.translate_file(CompetitorSourceKind.OPENCLAW, json_file)
    assert len(payloads_json) == 1
    assert payloads_json[0].normalized_content == "早晨喝冰美式"
    assert payloads_json[0].layer_recommendation == "profile"


def test_migration_service_idempotent_deduplication(tmp_path: Path) -> None:
    """Verify service deduplicates imported records on repeated runs."""
    db_file = tmp_path / "mig.db"
    service = CompetitorMigrationService(db_path=db_file)

    sample_md = tmp_path / "test_hermes.md"
    sample_md.write_text(
        "# General Facts\n- 事实A: 框架遵循 MIT 协议\n- 事实B: 沙箱严格单机隔离\n",
        encoding="utf-8",
    )

    # First migration run: all records imported
    rep1 = service.import_from_artifact(CompetitorSourceKind.HERMES, sample_md)
    assert rep1.total_scanned == 2
    assert rep1.total_imported == 2
    assert rep1.total_skipped_duplicates == 0

    # Second migration run with identical content: all skipped as duplicates
    rep2 = service.import_from_artifact(CompetitorSourceKind.HERMES, sample_md)
    assert rep2.total_scanned == 2
    assert rep2.total_imported == 0
    assert rep2.total_skipped_duplicates == 2

    # Verify audit ledger records both runs
    history = service.list_migration_history()
    assert len(history) == 2

    fingerprints = service.list_imported_fingerprints()
    assert len(fingerprints) == 2

    service.close()


def test_meta_tools_integration(tmp_path: Path) -> None:
    """Verify Agent CompetitorMigrationMetaTools end-to-end operation."""
    db_file = tmp_path / "meta_tools.db"
    service = CompetitorMigrationService(db_path=db_file)
    tools = CompetitorMigrationMetaTools(service=service)

    # Ingest text buffer
    rep = tools.import_competitor_memory_text(
        source_kind="hermes",
        raw_text="# Guidelines\n- 保持代码整洁与高性能\n",
        source_label="runtime_doc",
    )
    assert rep.total_imported == 1
    assert rep.source_kind == CompetitorSourceKind.HERMES

    # Check history via tools
    hist = tools.get_migration_audit_history()
    assert len(hist) == 1

    service.close()
