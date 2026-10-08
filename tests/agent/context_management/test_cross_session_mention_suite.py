# [INPUT]: CrossSessionConfig, CrossSessionMentionReferenceAndSnapshotInjectionSuite, MentionInjectionResult, SessionMentionParser, SessionMentionTag, SessionRecord, SessionSnapshot, SessionSnapshotExtractor
# [OUTPUT]: test_cross_session_mention_suite.py
# [POS]: tests/agent/context_management/test_cross_session_mention_suite.py

"""Comprehensive unit tests for CrossSessionMentionReferenceAndSnapshotInjectionSuite.

Verifies:
1. Lexical @Session mention tag parsing across quoted and unquoted syntax.
2. Multi-strategy session resolution (exact ID, title match, fuzzy substring).
3. Snapshot extraction priority (compacted summary vs recent turns fallback) and token caps.
4. Composer dropdown session fuzzy search and scoring.
5. End-to-end prompt injection, read-only snapshot envelope assembly, and proof badges.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.cross_session_mention import (
    CrossSessionConfig,
    CrossSessionMentionReferenceAndSnapshotInjectionSuite,
    MentionInjectionResult,
    SessionMentionParser,
    SessionMentionTag,
    SessionRecord,
    SessionSnapshot,
    SessionSnapshotExtractor,
)


def _build_sample_sessions() -> list[SessionRecord]:
    return [
        SessionRecord(
            session_id="sess_beijing_01",
            title="北京站落地方案",
            created_at=1700000100.0,
            compacted_summary="北京站方案第一阶段完成：高可用架构完成部署，数据迁移通过验证。",
            artifacts=["deploy_manifest.yaml", "migration_checklist.md"],
        ),
        SessionRecord(
            session_id="sess_auth_02",
            title="OAuth Authentication Refactor",
            created_at=1700000200.0,
            compacted_summary=None,
            recent_messages=[
                {"role": "user", "content": "How should we handle token refresh?"},
                {"role": "assistant", "content": "Use silent refresh with rotation and Redis blacklisting."},
                {"role": "user", "content": "Great, let's implement Redis store."},
            ],
            artifacts=["auth_middleware.py"],
        ),
        SessionRecord(
            session_id="sess_billing_03",
            title="Billing Stripe Integration",
            created_at=1700000300.0,
            compacted_summary="Stripe webhook integration active with idempotent signature verification.",
            artifacts=["stripe_webhook.py"],
        ),
    ]


def test_session_mention_parser_regex_and_quotes() -> None:
    parser = SessionMentionParser()

    text = (
        'Please review @Session:sess_beijing_01 and check with @Session:"北京站落地方案" '
        "as well as @Session:'OAuth Authentication Refactor'."
    )
    tags = parser.parse_mentions(text)

    assert len(tags) == 3
    assert tags[0].identifier == "sess_beijing_01"
    assert tags[1].identifier == "北京站落地方案"
    assert tags[2].identifier == "OAuth Authentication Refactor"
    assert not any(t.is_resolved for t in tags)

    # Empty text case
    assert parser.parse_mentions("") == []


def test_session_mention_parser_resolution() -> None:
    parser = SessionMentionParser()
    sessions = _build_sample_sessions()

    text = "Refer to @Session:sess_beijing_01 and @Session:oauth and @Session:non_existent_sess"
    tags = parser.parse_mentions(text)
    resolved = parser.resolve_mentions(tags, sessions)

    assert len(resolved) == 3
    # First matches exact ID
    assert resolved[0].is_resolved is True
    assert resolved[0].matched_session_id == "sess_beijing_01"

    # Second matches substring in title (OAuth)
    assert resolved[1].is_resolved is True
    assert resolved[1].matched_session_id == "sess_auth_02"

    # Third fails to resolve
    assert resolved[2].is_resolved is False
    assert resolved[2].matched_session_id is None


def test_session_snapshot_extractor_summary_priority() -> None:
    extractor = SessionSnapshotExtractor()
    sessions = _build_sample_sessions()

    # Session 0 has compacted summary
    snap = extractor.extract_snapshot(sessions[0])

    assert snap.session_id == "sess_beijing_01"
    assert "高可用架构完成部署" in snap.summary_content
    assert "deploy_manifest.yaml" in snap.key_artifacts
    assert snap.is_read_only is True
    assert "🔗 引用了会话《北京站落地方案》只读快照" == snap.reference_badge
    assert snap.token_estimate > 0


def test_session_snapshot_extractor_fallback_and_truncation() -> None:
    # Session 1 has no summary, relies on fallback recent turns
    extractor = SessionSnapshotExtractor()
    sessions = _build_sample_sessions()

    snap = extractor.extract_snapshot(sessions[1])
    assert snap.session_id == "sess_auth_02"
    assert "[Recent Turn History (Fallback)]" in snap.summary_content
    assert "silent refresh with rotation" in snap.summary_content
    assert "auth_middleware.py" in snap.key_artifacts

    # Budget cap test
    tight_config = CrossSessionConfig(max_snapshot_tokens_per_session=15)
    tight_extractor = SessionSnapshotExtractor(tight_config)
    tight_snap = tight_extractor.extract_snapshot(sessions[0])

    assert "[Truncated to Token Budget]" in tight_snap.summary_content


def test_suite_search_sessions() -> None:
    suite = CrossSessionMentionReferenceAndSnapshotInjectionSuite()
    sessions = _build_sample_sessions()

    # Exact title match
    matches = suite.search_sessions("北京站落地方案", sessions)
    assert len(matches) >= 1
    assert matches[0].session_id == "sess_beijing_01"

    # Prefix match
    matches_prefix = suite.search_sessions("OAuth", sessions)
    assert len(matches_prefix) >= 1
    assert matches_prefix[0].session_id == "sess_auth_02"

    # Search by session id
    matches_id = suite.search_sessions("sess_billing", sessions)
    assert len(matches_id) >= 1
    assert matches_id[0].session_id == "sess_billing_03"

    # Empty query returns recent first
    recent = suite.search_sessions("", sessions, limit=2)
    assert len(recent) == 2
    assert recent[0].created_at >= recent[1].created_at


def test_suite_inject_mentions_end_to_end() -> None:
    config = CrossSessionConfig(max_referenced_sessions=2)
    suite = CrossSessionMentionReferenceAndSnapshotInjectionSuite(config=config)
    sessions = _build_sample_sessions()

    user_prompt = "请根据 @Session:sess_beijing_01 和 @Session:sess_auth_02 编写整体部署文档。"
    result = suite.inject_mentions(user_prompt, sessions)

    assert result.original_user_prompt == user_prompt
    assert "[REFERENCED HISTORICAL SESSION SNAPSHOTS (READ-ONLY)]" in result.expanded_prompt
    assert "### Referenced Session: \"北京站落地方案\"" in result.expanded_prompt
    assert "### Referenced Session: \"OAuth Authentication Refactor\"" in result.expanded_prompt
    assert len(result.referenced_snapshots) == 2
    assert len(result.proof_badges) == 2
    assert any("北京站落地方案" in b for b in result.proof_badges)
    assert any("OAuth Authentication Refactor" in b for b in result.proof_badges)
    assert result.total_injected_tokens > 0

    # Unresolved mention returns original prompt unchanged
    no_match_result = suite.inject_mentions("Check @Session:unknown_random_sess please", sessions)
    assert no_match_result.expanded_prompt == "Check @Session:unknown_random_sess please"
    assert len(no_match_result.referenced_snapshots) == 0
    assert len(no_match_result.proof_badges) == 0
    assert no_match_result.total_injected_tokens == 0
