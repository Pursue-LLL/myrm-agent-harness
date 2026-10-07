"""[POS]: tests/unit/toolkits/memory/test_autonomous_dreaming_pruning_suite.py
[INPUT]: Autonomous dreaming synthesizer, memory pruning engine, and dreaming models.
[OUTPUT]: Pytest unit tests validating cross-session dreaming consolidation, contradiction superseding, and redundancy pruning.
"""

from myrm_agent_harness.toolkits.memory import (
    AutonomousDreamingSynthesizer,
    DreamDiaryEntry,
    DreamSessionFragment,
    DreamingMetaTools,
    MemoryPruningEngine,
    PruningDecisionKind,
)


def test_memory_pruning_contradiction_detection() -> None:
    pruner = MemoryPruningEngine()

    raw_memories = [
        {
            "id": "mem_old_1",
            "content": "项目中全面使用 React 18 作为核心视图层",
            "confidence": 0.8,
        },
        {
            "id": "mem_stable_1",
            "content": "数据库统一选用 PostgreSQL 16",
            "confidence": 0.9,
        },
    ]

    new_insight = DreamDiaryEntry.create(
        cognitive_statement="架构演进：全面采用 Svelte 5 构建极致高性能前端",
        source_session_ids=["sess_2026_01", "sess_2026_02"],
        evidence_snippets=["Migrate all web UI to Svelte 5"],
        confidence_delta=0.3,
    )

    records = pruner.evaluate_pruning(raw_memories=raw_memories, synthesized_entries=[new_insight])
    assert len(records) == 1
    assert records[0].memory_id == "mem_old_1"
    assert records[0].decision == PruningDecisionKind.CONTRADICTION_SUPERSEDED
    assert "Svelte" in str(records[0].superseded_by_statement)


def test_memory_pruning_redundant_absorption() -> None:
    pruner = MemoryPruningEngine()

    raw_memories = [
        {
            "id": "mem_frag_1",
            "content": "prefer uv run with python",
            "confidence": 0.7,
        },
        {
            "id": "mem_other_1",
            "content": "redis cache timeout is set to 300 seconds",
            "confidence": 0.8,
        },
    ]

    higher_insight = DreamDiaryEntry.create(
        cognitive_statement="[Cross-Session Validated] prefer uv run with python 3.13 for all backend workflows",
        source_session_ids=["sess_a", "sess_b"],
        evidence_snippets=["Always use uv run with python"],
    )

    records = pruner.evaluate_pruning(raw_memories=raw_memories, synthesized_entries=[higher_insight])
    assert len(records) == 1
    assert records[0].memory_id == "mem_frag_1"
    assert records[0].decision == PruningDecisionKind.REDUNDANT_ABSORBED


def test_autonomous_dreaming_synthesizer_cycle() -> None:
    synthesizer = AutonomousDreamingSynthesizer()

    fragment_a = DreamSessionFragment(
        session_id="sess_101",
        memories=[
            {
                "id": "mem_101_1",
                "content": "User prefers dark mode UI",
                "confidence": 0.8,
                "evidence": [{"quote_snippet": "Switch to dark mode"}],
            }
        ],
    )
    fragment_b = DreamSessionFragment(
        session_id="sess_102",
        memories=[
            {
                "id": "mem_102_1",
                "content": "User prefers dark mode UI for all dashboard apps",
                "confidence": 0.85,
                "evidence": [{"quote_snippet": "I always use dark mode"}],
            }
        ],
    )

    report = synthesizer.consolidate_and_prune(fragments=[fragment_a, fragment_b])
    assert report.candidate_count >= 2
    assert len(report.synthesized_insights) >= 1
    assert any("dark mode" in e.cognitive_statement for e in report.synthesized_insights)
    assert report.duration_ms >= 0.0


def test_dreaming_meta_tools_execution() -> None:
    tools = DreamingMetaTools()

    input_payload = [
        {
            "session_id": "sess_tool_1",
            "memories": [
                {
                    "content": "Use strict type hints without Any in Python",
                    "confidence": 0.9,
                    "evidence": [{"quote_snippet": "never use Any"}],
                }
            ],
            "chat_turn_count": 5,
        },
        {
            "session_id": "sess_tool_2",
            "memories": [
                {
                    "content": "Use strict type hints and Pydantic DTO in Python",
                    "confidence": 0.95,
                    "evidence": [{"quote_snippet": "strict type hints everywhere"}],
                }
            ],
            "chat_turn_count": 3,
        },
    ]

    res = tools.run_dreaming_consolidation(fragments_data=input_payload)
    assert "run_id" in res
    assert res["synthesized_count"] >= 1
    assert "synthesized_insights" in res
