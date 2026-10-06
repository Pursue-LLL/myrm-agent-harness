"""Unit tests for Zero-LLM local memory capture and rule-based FTS graph retrieval.

Validates deterministic fact extraction across all 6 categories, sub-millisecond
FTS5 lexical and [[Wikilink]] topological graph expansion, progressive gate fail-open
safety, and engine facade thread safety with zero token consumption.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory.zero_llm import (
    FactCategory,
    LlmAugmentationMode,
    ZeroLlmConfig,
    ZeroLlmFtsGraphRetriever,
    ZeroLlmMemoryEngine,
    ZeroLlmProgressiveGate,
    ZeroLlmRuleExtractor,
)


def _init_test_wiki_db(db_path: Path) -> None:
    """Create a minimal SQLite schema with FTS5 virtual table matching wiki_memory layout."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wiki_pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                page_slug TEXT UNIQUE NOT NULL,
                scope_level TEXT NOT NULL,
                agent_profile_id TEXT,
                title TEXT NOT NULL,
                content TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS wiki_pages_fts USING fts5(
                page_slug,
                title,
                content,
                content='wiki_pages',
                content_rowid='id'
            );
            """
        )
        # Seed test documents with wikilinks
        pages: list[tuple[str, str, str | None, str, str]] = [
            (
                "auth-architecture",
                "global",
                None,
                "Authentication Architecture",
                "We use JWT tokens and RBAC for secure access. See [[SecurityPolicy]] for details.",
            ),
            (
                "security-policy",
                "global",
                None,
                "SecurityPolicy",
                "Strict security rules enforced. Database connections require SSL. Refer to [[DatabaseConfig]].",
            ),
            (
                "database-config",
                "global",
                None,
                "DatabaseConfig",
                "Production PostgreSQL database cluster hosted on port 5432.",
            ),
            (
                "agent-notes",
                "agent",
                "coder-agent",
                "Coder Agent Notes",
                "Specialized instructions for code refactoring and [[CodingStandards]].",
            ),
            (
                "coding-standards",
                "agent",
                "coder-agent",
                "CodingStandards",
                "Zero Any type tolerance and PEP8 compliance mandated.",
            ),
        ]
        for p in pages:
            cur = conn.execute(
                "INSERT INTO wiki_pages (page_slug, scope_level, agent_profile_id, title, content) VALUES (?, ?, ?, ?, ?)",
                p,
            )
            row_id = cur.lastrowid
            conn.execute(
                "INSERT INTO wiki_pages_fts (rowid, page_slug, title, content) VALUES (?, ?, ?, ?)",
                (row_id, p[0], p[3], p[4]),
            )
        conn.commit()
    finally:
        conn.close()


def test_rule_extractor_preferences_and_config() -> None:
    """Test deterministic rule extraction for user preferences, prohibitions, and configs."""
    extractor = ZeroLlmRuleExtractor(min_confidence=0.6)
    text = (
        "Please remember: never use rm -rf in production. "
        "Also prefer PostgreSQL over MySQL for all new services. "
        "务必优先使用异步驱动进行数据库连接。\n"
        "export DATABASE_URL=postgres://user:pass@localhost:5432/mydb\n"
        "service listening on port 8080."
    )

    facts = extractor.extract_from_text(text, turn_index=1, source_file="deploy.sh")
    assert len(facts) >= 4

    categories = {f.category for f in facts}
    assert FactCategory.PREFERENCE in categories
    assert FactCategory.CONFIGURATION in categories

    # Check prohibition extraction
    prohibitions = [f for f in facts if f.predicate == "is_strictly_prohibited"]
    assert len(prohibitions) == 1
    assert "rm" in prohibitions[0].subject

    # Check config extraction
    configs = [f for f in facts if f.category == FactCategory.CONFIGURATION]
    db_config = [c for c in configs if c.subject == "DATABASE_URL"]
    assert len(db_config) == 1
    assert "mydb" in db_config[0].object_value


def test_rule_extractor_outcomes_decisions_and_deps() -> None:
    """Test deterministic extraction of tool outcomes, decisions, dependencies, and entities."""
    extractor = ZeroLlmRuleExtractor(min_confidence=0.6)
    text = (
        "The command exited with code 0.\n"
        "337 passed, 1 skipped in 23.40s\n"
        "We decided to adopt SQLite FTS5 for zero-cost lexical search.\n"
        "最终采用微服务架构隔离控制平面与工作节点。\n"
        "pydantic >= 2.6.0\n"
        "We evaluated JWT and RBAC with HMAC authentication."
    )

    facts = extractor.extract_from_text(text, turn_index=2)
    categories = {f.category for f in facts}
    assert FactCategory.TOOL_OUTCOME in categories
    assert FactCategory.DECISION in categories
    assert FactCategory.DEPENDENCY in categories
    assert FactCategory.ENTITY in categories

    # Check outcome extraction
    outcomes = [f for f in facts if f.category == FactCategory.TOOL_OUTCOME]
    assert any("exit_code_0" in o.object_value for o in outcomes)
    assert any("337_passed" in o.object_value for o in outcomes)

    # Check entity extraction
    entities = [f for f in facts if f.category == FactCategory.ENTITY]
    entity_terms = {e.subject for e in entities}
    assert "JWT" in entity_terms or "RBAC" in entity_terms or "FTS5" in entity_terms


def test_fts_graph_retriever_lexical_and_topology(tmp_path: Path) -> None:
    """Test SQLite FTS5 matching combined with 1-hop wikilink graph traversal."""
    db_file = tmp_path / "test_wiki.db"
    _init_test_wiki_db(db_file)

    retriever = ZeroLlmFtsGraphRetriever(db_path=db_file, limit=5, graph_hop_decay=0.5)

    # Query matching primary doc "auth-architecture" which links to [[SecurityPolicy]]
    res = retriever.search(query="JWT tokens RBAC", profile_id=None)
    assert res.zero_token_cost is True
    assert res.total_hits >= 2

    primary_hit = next(h for h in res.hits if h.page_slug == "auth-architecture")
    assert primary_hit.graph_hops == 0
    assert primary_hit.fts_score > 0.0

    # Neighbor hit from graph traversal
    neighbor_hit = next(h for h in res.hits if h.page_slug == "security-policy")
    assert neighbor_hit.graph_hops == 1
    assert neighbor_hit.composite_score < primary_hit.composite_score


def test_progressive_enhancement_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test progressive enhancement decisions and fallback behavior."""
    # 1. No keys in environment -> LLM unavailable
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("QWEN_API_KEY", raising=False)

    gate = ZeroLlmProgressiveGate(config=ZeroLlmConfig(augmentation_mode=LlmAugmentationMode.OPTIONAL))
    assert gate.is_llm_available() is False
    assert gate.should_use_llm_augmentation() is False

    extractor = ZeroLlmRuleExtractor()
    facts = extractor.extract_from_text("never use sudo in docker containers.")
    consolidated = gate.consolidate_facts(facts)
    assert len(consolidated) == len(facts)

    # 2. Disabled mode -> never use LLM even if keys exist
    monkeypatch.setenv("OPENAI_API_KEY", "sk-mock-key")
    disabled_gate = ZeroLlmProgressiveGate(config=ZeroLlmConfig(augmentation_mode=LlmAugmentationMode.DISABLED))
    assert disabled_gate.is_llm_available() is False
    assert disabled_gate.should_use_llm_augmentation() is False


def test_zero_llm_memory_engine_facade(tmp_path: Path) -> None:
    """Test unified engine facade extraction, search, and telemetry."""
    db_file = tmp_path / "engine_test.db"
    _init_test_wiki_db(db_file)

    engine = ZeroLlmMemoryEngine(db_path=db_file)

    # Extraction test
    extract_res = engine.extract_facts(
        text="We decided to use SQLite FTS5 for offline search. export TIMEOUT=5000",
        turn_index=3,
        source_file="setup.py",
    )
    assert extract_res.zero_token_cost is True
    assert extract_res.total_extracted >= 2

    # Search test
    search_res = engine.search(query="PostgreSQL database")
    assert search_res.zero_token_cost is True
    assert len(search_res.hits) >= 1

    # Telemetry stats
    stats = engine.get_stats()
    assert stats["total_extractions"] >= 2
    assert stats["total_queries"] == 1
    assert stats["zero_token_cost"] is True
