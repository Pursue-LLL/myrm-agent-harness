"""[POS]: tests/unit/toolkits/memory/test_multi_platform_memory_migration_suite.py
[INPUT]: None.
[OUTPUT]: Comprehensive unit tests for Item 134 MultiPlatformMemoryMigrationAndImportEngineSuite.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory.migration import (
    ChatExportParser,
    ChunkedMemoryArtifact,
    ClaudeProjectParser,
    CompetitorMigrationService,
    CompetitorSourceKind,
    MemOSParser,
    MigrationSecurityGuard,
    MigrationSecurityPolicy,
    MigrationSourceType,
    MultiPlatformMigrationEngine,
    MultiPlatformParserMatrix,
    SecurityLimitExceededError,
)


def test_memos_graph_parser_nodes_and_triples() -> None:
    """Verify MemOSParser extracts knowledge graph entities and relational triples."""
    guard = MigrationSecurityGuard()
    parser = MemOSParser()

    memos_payload = {
        "nodes": [
            {"id": "n1", "name": "UserPersona", "description": "资深全栈架构师", "type": "user_profile"},
            {"id": "n2", "name": "FastAPI", "description": "高性能异步 Python Web 框架", "type": "tech_stack"},
        ],
        "triples": [
            {"id": "t1", "subject": "UserPersona", "predicate": "masters", "object": "FastAPI"},
        ],
    }
    raw_json = json.dumps(memos_payload, ensure_ascii=False)
    units = parser.parse(raw_json, source_id="test_memos", guard=guard)

    assert len(units) == 3
    persona_node = next(u for u in units if u.source_id == "n1")
    assert persona_node.layer == "profile"
    assert "资深全栈架构师" in persona_node.normalized_text
    assert persona_node.source_type == MigrationSourceType.MEMOS

    triple_node = next(u for u in units if u.source_id == "t1")
    assert triple_node.layer == "semantic"
    assert "UserPersona masters FastAPI" in triple_node.normalized_text
    assert "memos_relation" in triple_node.tags


def test_claude_project_parser_prompt_and_docs() -> None:
    """Verify ClaudeProjectParser parses prompt instructions and project docs."""
    guard = MigrationSecurityGuard()
    parser = ClaudeProjectParser()

    claude_payload = {
        "custom_instructions": "遵循纯净重构原则，单文件严禁超过400行。",
        "docs": [
            {"file_name": "API_SPEC.md", "content": "# Architecture\n严格执行三层分离。"},
        ],
    }
    raw_json = json.dumps(claude_payload, ensure_ascii=False)
    units = parser.parse(raw_json, source_id="claude_project", guard=guard)

    assert len(units) == 2
    prompt_unit = next(u for u in units if u.source_id.endswith("_prompt"))
    assert prompt_unit.layer == "procedural"
    assert "纯净重构" in prompt_unit.normalized_text

    doc_unit = next(u for u in units if "API_SPEC.md" in u.source_id)
    assert doc_unit.layer == "semantic"
    assert doc_unit.source_type == MigrationSourceType.CLAUDE_PROJECT


def test_chatgpt_export_parser() -> None:
    """Verify ChatExportParser extracts meaningful conversation messages."""
    guard = MigrationSecurityGuard()
    parser = ChatExportParser()

    chatgpt_payload = [
        {
            "title": "系统架构研讨",
            "custom_instructions": "用户常年使用 macOS 开发。",
            "messages": [
                {"role": "user", "content": "我的偏好是使用 TypeScript 和 Python。"},
                {"role": "assistant", "content": "收到，我们将始终遵循您的技术栈规范。"},
            ],
        }
    ]
    raw_json = json.dumps(chatgpt_payload, ensure_ascii=False)
    units = parser.parse(raw_json, source_id="chat_export", guard=guard)

    assert len(units) >= 3
    inst_unit = next(u for u in units if "inst" in u.source_id)
    assert inst_unit.layer == "profile"
    assert "macOS" in inst_unit.normalized_text


def test_parser_matrix_dispatch() -> None:
    """Verify MultiPlatformParserMatrix dispatches each platform type correctly."""
    matrix = MultiPlatformParserMatrix()

    # OpenClaw JSON
    claw_units = matrix.parse_payload(
        source_type=MigrationSourceType.OPENCLAW,
        raw_content='[{"id": "c1", "content": "测试OpenClaw导入", "category": "user"}]',
    )
    assert len(claw_units) == 1
    assert claw_units[0].source_type == MigrationSourceType.OPENCLAW

    # MemOS
    memos_units = matrix.parse_payload(
        source_type=MigrationSourceType.MEMOS,
        raw_content='{"nodes": [{"id": "m1", "name": "Mem1", "description": "Desc1"}]}',
    )
    assert len(memos_units) == 1
    assert memos_units[0].source_type == MigrationSourceType.MEMOS


def test_security_guard_bounds(tmp_path: Path) -> None:
    """Verify MigrationSecurityGuard halts oversized files and batch payloads."""
    guard = MigrationSecurityGuard(
        policy=MigrationSecurityPolicy(max_file_size_bytes=100, max_batch_bytes=200)
    )

    oversized_file = tmp_path / "large.txt"
    oversized_file.write_text("x" * 200, encoding="utf-8")

    with pytest.raises(SecurityLimitExceededError):
        guard.validate_file(oversized_file)

    with pytest.raises(SecurityLimitExceededError):
        guard.validate_batch(300)


@pytest.mark.asyncio
async def test_multi_platform_migration_engine_end_to_end(tmp_path: Path) -> None:
    """Verify engine coordinates parsing, deduplication, sliding chunking, and fallback."""
    vector_sink_called: list[list[ChunkedMemoryArtifact]] = []

    async def mock_vector_sink(chunks: list[ChunkedMemoryArtifact]) -> bool:
        vector_sink_called.append(chunks)
        return True

    engine = MultiPlatformMigrationEngine(
        vector_sink=mock_vector_sink,
        vector_timeout_seconds=2.0,
    )

    # 1. First run with file migration
    sample_file = tmp_path / "hermes_sample.md"
    sample_file.write_text(
        "# Architectural Guidelines\n"
        "- 保持极简设计，单文件严禁超过400行\n"
        "- 严格使用具体的 Type Hints 消除 Any\n",
        encoding="utf-8",
    )

    admitted1, rep1 = await engine.migrate_file(
        source_type=MigrationSourceType.HERMES,
        file_path=sample_file,
    )
    assert len(admitted1) == 2
    assert rep1.total_scanned == 2
    assert rep1.total_admitted == 2
    assert rep1.total_skipped_duplicates == 0
    assert rep1.total_chunks_generated >= 2
    assert rep1.vector_ingestion_status == "success"
    assert len(vector_sink_called) == 1

    # 2. Second run on unchanged file: Level 1 fast skipped
    admitted2, rep2 = await engine.migrate_file(
        source_type=MigrationSourceType.HERMES,
        file_path=sample_file,
    )
    assert len(admitted2) == 0
    assert rep2.total_admitted == 0
    assert rep2.total_skipped_duplicates == 1
    assert rep2.vector_ingestion_status == "skipped_unchanged"

    # 3. Payload migration with timeout / vector error fallback
    async def failing_vector_sink(_: list[ChunkedMemoryArtifact]) -> bool:
        raise RuntimeError("Vector provider down")

    fallback_engine = MultiPlatformMigrationEngine(
        vector_sink=failing_vector_sink,
        vector_timeout_seconds=0.1,
    )
    admitted3, rep3 = await fallback_engine.migrate_payload(
        source_type=MigrationSourceType.OPENCLAW,
        raw_content='[{"id": "k1", "content": "新知识点写入", "category": "semantic"}]',
        source_label="runtime_stream",
    )
    assert len(admitted3) == 1
    assert rep3.total_admitted == 1
    assert rep3.vector_ingestion_status == "fallback_fts_only"


def test_competitor_migration_service_with_memos(tmp_path: Path) -> None:
    """Verify CompetitorMigrationService smoothly ingests MemOS graph JSON."""
    db_file = tmp_path / "memos_service.db"
    service = CompetitorMigrationService(db_path=db_file)

    memos_json = json.dumps(
        {
            "nodes": [
                {"id": "n100", "name": "ProjectAlpha", "description": "核心认知引擎", "type": "project"}
            ],
            "triples": [
                {"id": "t100", "subject": "ProjectAlpha", "predicate": "uses", "object": "SQLite"}
            ],
        },
        ensure_ascii=False,
    )

    rep = service.import_raw_text(
        source_kind=CompetitorSourceKind.MEMOS,
        raw_text=memos_json,
        source_label="test_memos_buf",
    )

    assert rep.total_scanned == 2
    assert rep.total_imported == 2
    assert rep.source_kind == MigrationSourceType.MEMOS

    # Check fingerprints table
    fps = service.list_imported_fingerprints()
    assert len(fps) == 2
    assert any("ProjectAlpha" in f["normalized_content"] for f in fps)

    service.close()
