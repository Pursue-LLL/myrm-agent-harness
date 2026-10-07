# [POS]: tests/unit/toolkits/memory/test_lineage_recall_defense_suite.py
# [INPUT]: SourceDemoterAndFilter, LineageDeduplicator, AdaptiveWindowHydrator, LineageSearchEngine
# [OUTPUT]: Unit test suite verifying recall blindness defense, lineage dedup, and adaptive window hydration

from pathlib import Path

from myrm_agent_harness.toolkits.memory import (
    AdaptiveWindowHydrator,
    ConversationMessage,
    LineageDeduplicator,
    LineageSearchEngine,
    LineageSearchOptions,
    RawSearchHit,
    SessionMeta,
    SessionSourceKind,
    SourceDemoterAndFilter,
)


def test_source_demoter_recall_blindness_defense() -> None:
    """Verifies that interactive sessions take precedence over cron automation (PR #19434),

    and internal worker tasks are hidden by default.
    """
    demoter = SourceDemoterAndFilter()

    # Session metas
    metas: dict[str, SessionMeta] = {
        "sess_cron_1": SessionMeta("sess_cron_1", title="Nightly Sweep", source=SessionSourceKind.CRON),
        "sess_cron_2": SessionMeta("sess_cron_2", title="Health Check", source=SessionSourceKind.CRON),
        "sess_user": SessionMeta("sess_user", title="Auth Redesign", source=SessionSourceKind.INTERACTIVE),
        "sess_subagent": SessionMeta("sess_subagent", title="Worker Task", source=SessionSourceKind.SUBAGENT),
    }

    hits: list[RawSearchHit] = [
        RawSearchHit("sess_cron_1", "m_c1", "assistant", "nightly build passed", score=9.5, source=SessionSourceKind.CRON),
        RawSearchHit("sess_user", "m_u1", "user", "redesign auth architecture", score=8.0, source=SessionSourceKind.INTERACTIVE),
        RawSearchHit("sess_cron_2", "m_c2", "assistant", "health sweep ok", score=9.0, source=SessionSourceKind.CRON),
        RawSearchHit("sess_subagent", "m_sub", "assistant", "internal compile done", score=9.8, source=SessionSourceKind.SUBAGENT),
    ]

    # 1. Without include_hidden: subagent must be filtered out
    # Interactive must rank ABOVE cron even with lower raw score (PR #19434 recall blindness defense)
    filtered = demoter.filter_and_demote(hits, metas, include_hidden=False)
    assert len(filtered) == 3
    assert filtered[0].session_id == "sess_user"  # Interactive wins!
    assert filtered[1].session_id == "sess_cron_1"
    assert filtered[2].session_id == "sess_cron_2"

    # 2. When only cron hits exist, cron must still be reachable (demoting, not excluding)
    cron_only_hits = [hits[0], hits[2]]
    cron_result = demoter.filter_and_demote(cron_only_hits, metas, include_hidden=False)
    assert len(cron_result) == 2
    assert cron_result[0].session_id == "sess_cron_1"


def test_lineage_root_deduplication() -> None:
    """Verifies that multi-generation compressed slices sharing the same lineage root are deduplicated."""
    deduplicator = LineageDeduplicator()

    metas: dict[str, SessionMeta] = {
        "gen_1": SessionMeta("gen_1", title="Task Slice 1", lineage_root_id="root_999"),
        "gen_2": SessionMeta("gen_2", title="Task Slice 2", lineage_root_id="root_999"),
        "gen_3": SessionMeta("gen_3", title="Task Slice 3", lineage_root_id="root_999"),
        "other_sess": SessionMeta("other_sess", title="Independent Task", lineage_root_id="root_888"),
    }

    hits: list[RawSearchHit] = [
        RawSearchHit("gen_1", "m_1", "assistant", "compaction slice 1", score=10.0),
        RawSearchHit("gen_2", "m_2", "assistant", "compaction slice 2", score=9.5),
        RawSearchHit("other_sess", "m_oth", "user", "other query", score=9.0),
        RawSearchHit("gen_3", "m_3", "assistant", "compaction slice 3", score=8.5),
    ]

    deduped = deduplicator.deduplicate(hits, metas, limit=5)
    # Must only retain gen_1 for root_999, and other_sess for root_888
    assert len(deduped) == 2
    assert deduped[0][0].session_id == "gen_1"
    assert deduped[0][1] == "root_999"
    assert deduped[1][0].session_id == "other_sess"
    assert deduped[1][1] == "root_888"


def test_adaptive_window_hydration_token_economy() -> None:
    """Verifies Top 1 expands full window (±5 msgs + bookends) and Top 2-N expands compact card."""
    hydrator = AdaptiveWindowHydrator(anchor_window=2, bookend_count=2)

    # Prepare 10 messages for a session
    messages: list[ConversationMessage] = [
        ConversationMessage(f"m_{i}", "sess_10", "user" if i % 2 == 0 else "assistant", f"Message content #{i}", f"2026-10-08T0{i}:00:00Z", i)
        for i in range(10)
    ]

    metas = {"sess_10": SessionMeta("sess_10", title="Test Session")}
    store = {"sess_10": messages}

    candidates = [
        (RawSearchHit("sess_10", "m_5", "user", "hit content 5", score=10.0), "sess_10"),
        (RawSearchHit("sess_10", "m_2", "user", "hit content 2", score=8.0), "sess_10_branch"),
    ]

    hydrated = hydrator.hydrate(candidates, metas, store)
    assert len(hydrated) == 2

    # Top 1 receives full window
    top1 = hydrated[0]
    assert top1.detail_level == "full"
    assert len(top1.bookend_start) == 2
    assert len(top1.bookend_end) == 2
    # window covers anchor ±2 (m_3, m_4, m_5, m_6, m_7) -> 5 msgs
    assert len(top1.window_messages) == 5
    assert "@session:sess_10#msg_m_5" in top1.deep_link

    # Top 2 receives compact card
    top2 = hydrated[1]
    assert top2.detail_level == "compact"
    assert len(top2.bookend_start) == 0
    assert len(top2.bookend_end) == 0
    # compact card contains only matched message
    assert len(top2.window_messages) == 1
    assert top2.window_messages[0].message_id == "m_2"


def test_lineage_search_engine_e2e_integration(tmp_path: Path) -> None:
    """Verifies end-to-end integration: storage, FTS5 lexical matching, demotion, and telemetry."""
    db_file = tmp_path / "test_lineage.db"
    engine = LineageSearchEngine(db_path=db_file)

    # 1. Add interactive session
    s_user = SessionMeta("sess_user", title="Database Optimization", source=SessionSourceKind.INTERACTIVE)
    engine.add_session(s_user)
    engine.add_message(ConversationMessage("msg_u1", "sess_user", "user", "How to optimize SQLite FTS5 virtual tables?", "2026-10-08T10:00:00Z", 1))
    engine.add_message(ConversationMessage("msg_u2", "sess_user", "assistant", "Use unicode61 tokenization and compact storage.", "2026-10-08T10:01:00Z", 2))

    # 2. Add cron session with identical keyword
    s_cron = SessionMeta("sess_cron", title="Scheduled DB Vacuum", source=SessionSourceKind.CRON)
    engine.add_session(s_cron)
    engine.add_message(ConversationMessage("msg_c1", "sess_cron", "assistant", "Routine maintenance: optimize SQLite database vacuum.", "2026-10-08T03:00:00Z", 1))

    # 3. Search query: "optimize SQLite"
    opts = LineageSearchOptions(query="optimize SQLite", limit=5)
    results = engine.search(opts)

    assert len(results) == 2
    # Interactive must precede cron
    assert results[0].session_id == "sess_user"
    assert results[0].detail_level == "full"
    assert results[1].session_id == "sess_cron"
    assert results[1].detail_level == "compact"

    # Telemetry
    stats = engine.get_stats()
    assert stats.total_sessions == 2
    assert stats.total_messages == 3
    assert stats.demoted_sources_count == 1
    engine.close()
