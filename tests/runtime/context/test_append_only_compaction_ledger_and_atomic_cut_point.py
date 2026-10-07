"""Unit tests for AppendOnlyCompactionLedgerAndAtomicToolPairCutPointEngine (Item 103).

Validates Atomic Tool-Pair Invariants (zero orphaned tool results),
append-only history immutability, split-turn double-segment summary fusion,
and dynamic context assembly for LLM inference.
"""

from myrm_agent_harness.runtime.context.append_only_compaction_ledger_engine import (
    AppendOnlyCompactionLedgerEngine,
)
from myrm_agent_harness.runtime.context.append_only_compaction_types import (
    ContextEntryRole,
    ContextLogEntry,
)
from myrm_agent_harness.runtime.context.atomic_tool_pair_cut_point_resolver import (
    AtomicToolPairCutPointResolver,
)


def _build_interleaved_tool_entries() -> list[ContextLogEntry]:
    """Helper constructing realistic multi-turn conversation with tool calls."""
    return [
        ContextLogEntry(
            entry_id="e_01",
            role=ContextEntryRole.USER,
            content="Please check the current repository status.",
            token_estimate=50,
            turn_id=1,
        ),
        ContextLogEntry(
            entry_id="e_02",
            role=ContextEntryRole.TOOL_CALL,
            content="git status",
            tool_call_id="call_git_status",
            token_estimate=40,
            turn_id=1,
        ),
        ContextLogEntry(
            entry_id="e_03",
            role=ContextEntryRole.TOOL_RESULT,
            content="On branch main, working tree clean. Read README.md",
            tool_call_id="call_git_status",
            token_estimate=80,
            turn_id=1,
        ),
        ContextLogEntry(
            entry_id="e_04",
            role=ContextEntryRole.ASSISTANT,
            content="The working tree is clean. Ready for new features.",
            token_estimate=60,
            turn_id=1,
        ),
        ContextLogEntry(
            entry_id="e_05",
            role=ContextEntryRole.USER,
            content="Now inspect config and edit database settings.",
            token_estimate=50,
            turn_id=2,
        ),
        ContextLogEntry(
            entry_id="e_06",
            role=ContextEntryRole.TOOL_CALL,
            content="view config/database.yml",
            tool_call_id="call_view_db",
            token_estimate=40,
            turn_id=2,
        ),
        ContextLogEntry(
            entry_id="e_07",
            role=ContextEntryRole.TOOL_RESULT,
            content="host: localhost, port: 5432. Read config/database.yml",
            tool_call_id="call_view_db",
            token_estimate=120,
            turn_id=2,
        ),
        ContextLogEntry(
            entry_id="e_08",
            role=ContextEntryRole.TOOL_CALL,
            content="edit config/database.yml to update pool size",
            tool_call_id="call_edit_db",
            token_estimate=50,
            turn_id=2,
        ),
        ContextLogEntry(
            entry_id="e_09",
            role=ContextEntryRole.TOOL_RESULT,
            content="File updated successfully. Modified config/database.yml",
            tool_call_id="call_edit_db",
            token_estimate=90,
            turn_id=2,
        ),
        ContextLogEntry(
            entry_id="e_10",
            role=ContextEntryRole.ASSISTANT,
            content="Database pool size has been successfully updated.",
            token_estimate=70,
            turn_id=2,
        ),
    ]


def test_atomic_tool_pair_cut_point_invariant_no_orphaned_results() -> None:
    """Verify cut-point resolver never severs a tool_call and tool_result pair."""
    resolver = AtomicToolPairCutPointResolver()
    entries = _build_interleaved_tool_entries()

    # Total tokens = 50+40+80+60+50+40+120+50+90+70 = 650
    # Set target budget so natural cut would land directly on e_07 (TOOL_RESULT for call_view_db)
    target_budget = 300

    resolution = resolver.resolve_atomic_cut_point(entries, target_kept_tokens=target_budget)

    # Cut index must NOT be e_07 or e_09 (TOOL_RESULT)
    retained_entries = entries[resolution.cut_index :]
    assert len(retained_entries) > 0

    # Retained section must not start with a tool result
    assert retained_entries[0].role != ContextEntryRole.TOOL_RESULT

    # All tool results in retained section must have their corresponding tool call present
    tool_calls = {e.tool_call_id for e in retained_entries if e.role == ContextEntryRole.TOOL_CALL}
    tool_results = {e.tool_call_id for e in retained_entries if e.role == ContextEntryRole.TOOL_RESULT}

    for res_id in tool_results:
        assert res_id in tool_calls, f"Severed tool result found for {res_id}!"


def test_append_only_immutability_and_compaction_entry_creation() -> None:
    """Verify history log is immutable (append-only) and compaction tracks file footprints."""
    engine = AppendOnlyCompactionLedgerEngine()
    entries = _build_interleaved_tool_entries()
    engine.append_entries(entries)

    original_count = len(engine.entries)
    assert original_count == 10

    # Trigger compaction with 350 tokens budget
    compaction = engine.compact(target_kept_tokens=350)
    assert compaction is not None

    # Invariant: Log history length MUST NOT change (append-only, no destructive deletions)
    assert len(engine.entries) == original_count
    assert len(engine.compactions) == 1

    # Verify tracked file footprints
    assert any("README.md" in f or "database.yml" in f for f in compaction.read_files)
    assert compaction.tokens_before == 650
    assert compaction.tokens_after > 0
    assert compaction.first_kept_entry_id != ""

    # Verify context assembly
    assembly = engine.assemble_context_for_llm(system_prompt="You are an expert engineer.")
    assert assembly.active_summary is not None
    assert assembly.has_orphaned_tool_pairs is False
    assert len(assembly.retained_entries) < original_count


def test_split_turn_double_segment_fusion_for_oversized_turn() -> None:
    """Verify split-turn dual-segment summary fusion when a single turn exceeds budget."""
    engine = AppendOnlyCompactionLedgerEngine()

    # Construct Turn 1 (small) and Turn 2 (giant turn with multiple tool steps)
    t1_user = ContextLogEntry("t1_u", ContextEntryRole.USER, "Start task", token_estimate=30, turn_id=1)
    t1_asst = ContextLogEntry("t1_a", ContextEntryRole.ASSISTANT, "Task started", token_estimate=40, turn_id=1)

    t2_user = ContextLogEntry("t2_u", ContextEntryRole.USER, "Analyze big data", token_estimate=50, turn_id=2)
    t2_call1 = ContextLogEntry("t2_c1", ContextEntryRole.TOOL_CALL, "fetch_part1", tool_call_id="call_p1", token_estimate=60, turn_id=2)
    t2_res1 = ContextLogEntry("t2_r1", ContextEntryRole.TOOL_RESULT, "part1 data ok", tool_call_id="call_p1", token_estimate=400, turn_id=2)
    t2_call2 = ContextLogEntry("t2_c2", ContextEntryRole.TOOL_CALL, "fetch_part2", tool_call_id="call_p2", token_estimate=60, turn_id=2)
    t2_res2 = ContextLogEntry("t2_r2", ContextEntryRole.TOOL_RESULT, "part2 data ok", tool_call_id="call_p2", token_estimate=500, turn_id=2)
    t2_asst = ContextLogEntry("t2_a", ContextEntryRole.ASSISTANT, "Analysis done", token_estimate=70, turn_id=2)

    engine.append_entries([t1_user, t1_asst, t2_user, t2_call1, t2_res1, t2_call2, t2_res2, t2_asst])

    # Tight target budget forcing cut inside Turn 2
    compaction = engine.compact(target_kept_tokens=600)
    assert compaction is not None
    assert compaction.is_split_turn is True
    assert "[SPLIT_TURN_COMPACTION_SUMMARY]" in compaction.summary
    assert "Active Turn #2 Partial Progress" in compaction.summary

    # Ensure assembled view is valid and free of orphaned tool results
    assembly = engine.assemble_context_for_llm(system_prompt="Test agent")
    assert assembly.has_orphaned_tool_pairs is False


def test_multiple_consecutive_compactions_dynamic_assembly() -> None:
    """Verify consecutive compactions append distinct markers and assembly reflects newest."""
    engine = AppendOnlyCompactionLedgerEngine()
    entries = _build_interleaved_tool_entries()

    # Step 1: Add first 5 entries and compact
    engine.append_entries(entries[:5])
    c1 = engine.compact(target_kept_tokens=100)
    assert c1 is not None
    assert len(engine.compactions) == 1

    # Step 2: Add remaining 5 entries and compact again with small budget
    engine.append_entries(entries[5:])
    c2 = engine.compact(target_kept_tokens=200)
    assert c2 is not None
    assert len(engine.compactions) == 2

    # Assembly must use latest compaction marker (c2)
    assembly = engine.assemble_context_for_llm(system_prompt="Assistant prompt")
    assert assembly.active_summary == c2.summary
    assert assembly.has_orphaned_tool_pairs is False

    # Entries list retains all 10 entries historically
    assert len(engine.entries) == 10


def test_under_budget_no_compaction_idempotence() -> None:
    """Verify when conversation is comfortably under budget, compact is a no-op."""
    engine = AppendOnlyCompactionLedgerEngine()
    entries = _build_interleaved_tool_entries()[:3]
    engine.append_entries(entries)

    # 50 + 40 + 80 = 170 tokens, budget 1000
    compaction = engine.compact(target_kept_tokens=1000)
    assert compaction is None
    assert len(engine.compactions) == 0

    assembly = engine.assemble_context_for_llm(system_prompt="Base prompt")
    assert assembly.active_summary is None
    assert len(assembly.retained_entries) == 3
    assert assembly.has_orphaned_tool_pairs is False
