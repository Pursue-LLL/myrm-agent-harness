# [INPUT]: ArchiveSearchResult, ExpandedHandoffAnchor, ExpandedHandoffConfig, ExpandedHandoffSuite, ExpandedSkeletonAnchorBuilder, FullDialogue1200WordAnchorWithSearchableArchiveHandoffSuite, HistoricalSessionTurn, SearchableOldSessionArchiveConduit
# [OUTPUT]: test_expanded_handoff_suite.py
# [POS]: tests/agent/context_management/test_expanded_handoff_suite.py

"""Comprehensive unit tests for FullDialogue1200WordAnchorWithSearchableArchiveHandoffSuite.

Verifies:
1. Empty turn sequence anchor generation and fallback handling.
2. Anchor skeleton extraction for constraints, rejected paths, and technical assets.
3. Character budget clamping and safe truncation mechanics.
4. Lexical archive indexing, scoring, phrase bonus, and snippet extraction.
5. Search threshold filtering and non-matching query rejection.
6. Function tool spec structure compliance.
7. Full facade end-to-end integration and context prompt injection rendering.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.expanded_handoff import (
    ArchiveSearchResult,
    ExpandedHandoffAnchor,
    ExpandedHandoffConfig,
    ExpandedHandoffSuite,
    ExpandedSkeletonAnchorBuilder,
    FullDialogue1200WordAnchorWithSearchableArchiveHandoffSuite,
    HistoricalSessionTurn,
    SearchableOldSessionArchiveConduit,
)


def test_empty_turns_anchor_generation() -> None:
    """Verifies that an empty transcript yields a safe empty handoff anchor."""
    builder = ExpandedSkeletonAnchorBuilder()
    anchor = builder.build_anchor(
        origin_session_id="sess-orig-001",
        target_session_id="sess-target-001",
        turns=(),
        title="Empty Test",
    )

    assert anchor.origin_session_id == "sess-orig-001"
    assert anchor.target_session_id == "sess-target-001"
    assert anchor.anchor_title == "Empty Test"
    assert anchor.origin_total_turns == 0
    assert "No prior dialogue turns available" in anchor.expanded_skeleton_text
    assert anchor.search_pointer_key == "archive:sess-orig-001"


def test_anchor_builder_extraction_and_markdown_structure() -> None:
    """Verifies extraction of architectural constraints, rejected alternatives, and code assets."""
    builder = ExpandedSkeletonAnchorBuilder()
    turns = [
        HistoricalSessionTurn(
            turn_id="t1",
            role="user",
            content="We must strictly avoid using Any types across all modules in harness.",
        ),
        HistoricalSessionTurn(
            turn_id="t2",
            role="assistant",
            content="Understood. We rule out using raw dictionaries without TypedDict schema.",
        ),
        HistoricalSessionTurn(
            turn_id="t3",
            role="user",
            content="Please inspect src/core/pipeline.py and asset c8f30999-5678-4321-8765-abcdef012345.",
        ),
        HistoricalSessionTurn(
            turn_id="t4",
            role="assistant",
            content="Completed refactor of pipeline.py. All tests passed with 100% coverage.",
        ),
    ]

    anchor = builder.build_anchor(
        origin_session_id="sess-orig-12345678",
        target_session_id="sess-target-999",
        turns=turns,
    )

    text = anchor.expanded_skeleton_text
    assert "sess-orig-12345678" in text
    # 1. Constraints
    assert "## 1. Core Mission & Critical Constraints" in text
    assert "avoid using Any types" in text

    # 2. Rejected paths
    assert "## 2. Architectural Decisions & Deprecated Paths" in text
    assert "raw dictionaries without TypedDict" in text

    # 3. Assets
    assert "## 3. Key Technical Assets & Anchors" in text
    assert "src/core/pipeline.py" in text
    assert "c8f30999-5678-4321-8765-abcdef012345" in text

    # 4. Chronological milestones
    assert "## 4. Chronological Trajectory & Active Breakpoint" in text
    assert "Turn t4 (ASSISTANT)" in text
    assert anchor.origin_total_turns == 4
    assert anchor.word_count > 20


def test_anchor_character_budget_clamping() -> None:
    """Verifies that large dialogues are gracefully bounded by character limits."""
    config = ExpandedHandoffConfig(max_char_budget=400)
    builder = ExpandedSkeletonAnchorBuilder(config=config)

    long_turns = [
        HistoricalSessionTurn(
            turn_id=f"t{i}",
            role="assistant",
            content=f"Detailed log execution entry number {i} " + ("padding content " * 15),
        )
        for i in range(15)
    ]

    anchor = builder.build_anchor(
        origin_session_id="sess-long",
        target_session_id="sess-next",
        turns=long_turns,
    )

    assert len(anchor.expanded_skeleton_text) <= 450
    assert "...[Remainder indexed in archive]" in anchor.expanded_skeleton_text


def test_searchable_archive_conduit_lexical_search() -> None:
    """Verifies sub-session lexical retrieval, score ranking, phrase bonus, and snippet extraction."""
    conduit = SearchableOldSessionArchiveConduit()
    turns = [
        HistoricalSessionTurn(
            turn_id="turn-10",
            role="user",
            content="Deploy service to Kubernetes cluster with replica count 5.",
            timestamp=100.0,
        ),
        HistoricalSessionTurn(
            turn_id="turn-11",
            role="assistant",
            content="Encountered CrashLoopBackOff: exit code 137 OOMKilled in container worker-pod.",
            timestamp=101.0,
        ),
        HistoricalSessionTurn(
            turn_id="turn-12",
            role="assistant",
            content="Adjusted memory limit from 512Mi to 2Gi. Pod restarted successfully.",
            timestamp=102.0,
        ),
    ]

    conduit.register_archive("sess-k8s", turns)

    # 1. Exact phrase search for error
    results = conduit.search_archive("sess-k8s", query="CrashLoopBackOff OOMKilled")
    assert len(results) >= 1
    top = results[0]
    assert top.turn_id == "turn-11"
    assert "OOMKilled" in top.matched_snippet
    assert top.relevance_score > 0.5

    # 2. Multi-token search for memory adjustment
    mem_results = conduit.search_archive("sess-k8s", query="memory limit 2Gi")
    assert len(mem_results) >= 1
    assert mem_results[0].turn_id == "turn-12"
    assert "2Gi" in mem_results[0].matched_snippet


def test_searchable_archive_filtering_and_empty_queries() -> None:
    """Verifies filtering of low-relevance queries and handling of unregistered sessions."""
    conduit = SearchableOldSessionArchiveConduit(config=ExpandedHandoffConfig(min_search_score=0.4))
    turns = [
        HistoricalSessionTurn(
            turn_id="t1",
            role="user",
            content="The quick brown fox jumps over the lazy dog.",
        ),
    ]
    conduit.register_archive("sess-fox", turns)

    # Query with no overlapping terms
    assert conduit.search_archive("sess-fox", query="cryptocurrency blockchain mining") == ()

    # Query with unregistered session ID
    assert conduit.search_archive("sess-unknown", query="fox") == ()

    # Empty query string
    assert conduit.search_archive("sess-fox", query="   ") == ()


def test_search_tool_spec_generation() -> None:
    """Verifies that the generated OpenAI tool definition matches specification schema."""
    conduit = SearchableOldSessionArchiveConduit()
    spec = conduit.generate_tool_definition()

    assert spec["type"] == "function"
    fn = spec["function"]
    assert fn["name"] == "search_origin_session_archive"
    assert "session_id" in fn["parameters"]["properties"]
    assert "query" in fn["parameters"]["properties"]
    assert fn["parameters"]["required"] == ["session_id", "query"]


def test_full_facade_end_to_end_pipeline_and_injection() -> None:
    """Verifies end-to-end handoff workflow using the facade suite."""
    suite = FullDialogue1200WordAnchorWithSearchableArchiveHandoffSuite()
    assert ExpandedHandoffSuite is FullDialogue1200WordAnchorWithSearchableArchiveHandoffSuite

    turns = [
        HistoricalSessionTurn(
            turn_id="step-1",
            role="user",
            content="Goal: Refactor SQLite WAL mode in db_driver.py.",
        ),
        HistoricalSessionTurn(
            turn_id="step-2",
            role="assistant",
            content="Executing sqlite3 PRAGMA journal_mode=WAL on /var/data/app.db.",
        ),
    ]

    # 1. Create anchor
    anchor = suite.create_handoff_anchor(
        origin_session_id="orig-session-8888",
        target_session_id="target-session-9999",
        turns=turns,
        title="SQLite WAL Refactor Handoff",
    )
    assert anchor.origin_session_id == "orig-session-8888"
    assert anchor.target_session_id == "target-session-9999"

    # 2. Verify search on registered archive
    search_res = suite.search_origin_archive("orig-session-8888", query="journal_mode=WAL")
    assert len(search_res) >= 1
    assert search_res[0].turn_id == "step-2"

    # 3. Tool definition retrieval
    tool_spec = suite.get_search_tool_spec()
    assert tool_spec["type"] == "function"

    # 4. Render context injection block with A Way Back instructions
    injected_prompt = suite.render_handoff_context_injection(anchor)
    assert "# [Cross-Session Expanded Dialogue Anchor: SQLite WAL Refactor Handoff]" in injected_prompt
    assert "### 🔍 [A Way Back: Origin Session Search Conduit]" in injected_prompt
    assert "search_origin_session_archive" in injected_prompt
    assert "orig-session-8888" in injected_prompt
