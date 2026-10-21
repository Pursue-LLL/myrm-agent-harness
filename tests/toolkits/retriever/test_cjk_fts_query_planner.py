"""Tests for CjkFtsQueryPlanner and CJK Bigram Tokenizer robustness."""

from __future__ import annotations

import sqlite3

from myrm_agent_harness.api import (
    CjkFtsQueryPlanner,
    build_cjk_index_segment,
    tokenize_cjk_bigram,
)


def test_tokenize_cjk_bigram_preserves_ascii_identifiers() -> None:
    text = "Deploy k8s-prod v1.2.0 on 沙箱环境"
    tokens = tokenize_cjk_bigram(text)

    # ASCII technical identifiers should be intact and lowercased
    assert "deploy" in tokens
    assert "k8s-prod" in tokens
    assert "v1.2.0" in tokens
    assert "on" in tokens

    # CJK unigrams and adjacent bigrams
    assert "沙" in tokens
    assert "箱" in tokens
    assert "沙箱" in tokens
    assert "箱环" in tokens
    assert "环境" in tokens


def test_build_cjk_index_segment_expansion_bound() -> None:
    text = "测试" * 100  # 200 repeated CJK chars
    segment = build_cjk_index_segment(text, max_expansion_ratio=2.2)
    tokens = segment.split()

    # Deduplicated tokens should be bounded
    assert len(tokens) <= int(len(text) * 2.2)
    assert "测" in tokens
    assert "试" in tokens
    assert "测试" in tokens


def test_cjk_fts_query_planner_tiers() -> None:
    query = "沙箱部署"
    plans = CjkFtsQueryPlanner.plan_query_tiers(query)

    assert len(plans) == 2
    strict_match, is_strict_relaxed = plans[0]
    assert is_strict_relaxed is False
    assert '"沙箱"' in strict_match
    assert '"部署"' in strict_match

    relaxed_match, is_relaxed = plans[1]
    assert is_relaxed is True
    # Relaxed drops 2-character CJK bigrams, keeping only unigrams
    assert '"沙箱"' not in relaxed_match
    assert '"沙"' in relaxed_match
    assert '"箱"' in relaxed_match
    assert '"部"' in relaxed_match
    assert '"署"' in relaxed_match


def test_cjk_fts_query_planner_ascii_only() -> None:
    query = "k8s-prod service"
    plans = CjkFtsQueryPlanner.plan_query_tiers(query)

    # ASCII only queries don't have separate relaxed tier if identical
    assert len(plans) == 1
    match_str, is_relaxed = plans[0]
    assert is_relaxed is False
    assert '"k8s-prod"' in match_str
    assert '"service"' in match_str


def test_sqlite_fts5_cjk_recall_end_to_end() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(
            'CREATE VIRTUAL TABLE t USING fts5(content, tokenize="unicode61 remove_diacritics 1")'
        )

        corpus = "沙箱环境部署已完成，PR review 通过，AI agent 运行正常"
        indexed_text = build_cjk_index_segment(corpus)
        conn.execute("INSERT INTO t(content) VALUES (?)", (indexed_text,))

        # Test all high-frequency 2-char CJK and short ASCII keywords
        test_queries = ["沙箱", "部署", "完成", "PR", "AI", "agent"]

        for q in test_queries:
            plans = CjkFtsQueryPlanner.plan_query_tiers(q)
            hits = 0
            for match_str, _ in plans:
                cursor = conn.execute("SELECT content FROM t WHERE t MATCH ?", (match_str,))
                rows = cursor.fetchall()
                if rows:
                    hits = len(rows)
                    break
            assert hits > 0, f"Query '{q}' failed to recall from FTS5 indexed corpus!"
    finally:
        conn.close()
