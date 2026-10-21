"""Unit tests for long-horizon research incremental checkpoints and draft persistence suite.

Verifies:
- Atomic draft persistence and loading for individual research chapters.
- Order-preserving multi-chapter retrieval and final Markdown document assembly.
- Relational checkpoint lifecycle, chapter advancement, and resource accumulation.
- Zero-waste resumption planning, next-chapter targeting, and prompt synthesis.
"""

from __future__ import annotations

import tempfile

from myrm_agent_harness.runtime.research_checkpoint import (
    IncrementalDraftStore,
    ResearchChapterDraft,
    ResearchCheckpoint,
    ResearchCheckpointLedger,
    ResearchResumptionEngine,
    ResearchStatus,
)


def test_incremental_draft_store_atomic_write_and_load() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = IncrementalDraftStore(storage_root=tmp_dir)
        task_id = "task_deep_eval_001"

        draft1 = ResearchChapterDraft(
            chapter_index=1,
            title="Industry Background and Executive Summary",
            content_markdown="### 1. Overview\nThe AI agent ecosystem is shifting rapidly...",
            sources_cited=("https://arxiv.org/abs/2401.0001", "https://news.ycombinator.com"),
            token_estimate=12500,
            duration_ms=4200.0,
        )

        draft2 = ResearchChapterDraft(
            chapter_index=2,
            title="Technical Architecture & Kernel Benchmarks",
            content_markdown="### 2. Architecture\nSubprocess isolation with PTY emulation...",
            sources_cited=("https://github.com/NousResearch/hermes-agent",),
            token_estimate=18400,
            duration_ms=6100.0,
        )

        path1 = store.save_chapter_draft(task_id, draft1)
        path2 = store.save_chapter_draft(task_id, draft2)

        assert path1.exists()
        assert path2.exists()

        # Load single draft
        loaded1 = store.load_chapter_draft(task_id, chapter_index=1)
        assert loaded1 is not None
        assert loaded1.chapter_index == 1
        assert loaded1.title == "Industry Background and Executive Summary"
        assert len(loaded1.sources_cited) == 2

        # Get all drafts sorted
        all_drafts = store.get_all_drafts(task_id)
        assert len(all_drafts) == 2
        assert all_drafts[0].chapter_index == 1
        assert all_drafts[1].chapter_index == 2


def test_assemble_final_document() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = IncrementalDraftStore(storage_root=tmp_dir)
        task_id = "task_report_assembly"

        for i in range(1, 4):
            store.save_chapter_draft(
                task_id,
                ResearchChapterDraft(
                    chapter_index=i,
                    title=f"Section {i} Analysis",
                    content_markdown=f"Findings for section {i}.",
                    sources_cited=(f"https://source-{i}.com", "https://common-source.org"),
                ),
            )

        doc = store.assemble_final_document(task_id, report_title="Global AI Benchmark")
        assert "# Global AI Benchmark" in doc
        assert "## Table of Contents" in doc
        assert "- [Chapter 1: Section 1 Analysis](#section-1-analysis)" in doc
        assert "## Chapter 3: Section 3 Analysis" in doc
        assert "## References & Sources Cited" in doc
        assert "https://common-source.org" in doc
        assert "https://source-1.com" in doc


def test_checkpoint_ledger_lifecycle_and_advancement() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = f"{tmp_dir}/checkpoints.db"
        ledger = ResearchCheckpointLedger(db_path=db_file)
        task_id = "task_ledger_test"

        initial_chk = ResearchCheckpoint(
            checkpoint_id="chk_init",
            task_id=task_id,
            session_id="sess_123",
            current_status=ResearchStatus.IN_PROGRESS,
            completed_chapters=(),
            pending_chapters=(1, 2, 3),
            total_tokens_consumed=0,
            total_duration_ms=0.0,
        )
        ledger.commit_checkpoint(initial_chk)

        # Advance chapter 1
        chk1 = ledger.advance_chapter_progress(
            task_id,
            finished_chapter_index=1,
            tokens_used=120000,
            duration_ms=35000.0,
        )
        assert chk1.completed_chapters == (1,)
        assert chk1.pending_chapters == (2, 3)
        assert chk1.total_tokens_consumed == 120000
        assert chk1.total_duration_ms == 35000.0
        assert chk1.current_status == ResearchStatus.IN_PROGRESS

        # Advance chapter 2 and 3
        ledger.advance_chapter_progress(task_id, 2, tokens_used=100000, duration_ms=25000.0)
        final_chk = ledger.advance_chapter_progress(task_id, 3, tokens_used=90000, duration_ms=20000.0)

        assert final_chk.completed_chapters == (1, 2, 3)
        assert final_chk.pending_chapters == ()
        assert final_chk.total_tokens_consumed == 310000
        assert final_chk.current_status == ResearchStatus.COMPLETED
        assert final_chk.is_finished is True

        ledger.close()


def test_resumption_engine_prepare_resumption() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = f"{tmp_dir}/checkpoints.db"
        ledger = ResearchCheckpointLedger(db_path=db_file)
        store = IncrementalDraftStore(storage_root=f"{tmp_dir}/drafts")
        engine = ResearchResumptionEngine(ledger, store)

        task_id = "task_crash_resumption"

        # Materialize completed chapter 1 and 2 drafts
        store.save_chapter_draft(
            task_id,
            ResearchChapterDraft(
                chapter_index=1,
                title="Historical Evolution",
                content_markdown="Detailed analysis of LLM agents from 2023 to 2026...",
                sources_cited=("https://arxiv.org/abs/2301.0001",),
            ),
        )
        store.save_chapter_draft(
            task_id,
            ResearchChapterDraft(
                chapter_index=2,
                title="Runtime Reliability Bottlenecks",
                content_markdown="Analysis of tool-call failures, PTY deadlocks, and network loops...",
            ),
        )

        # Commit checkpoint representing interrupted state at chapter 3
        ledger.commit_checkpoint(
            ResearchCheckpoint(
                checkpoint_id="chk_crashed_before_ch3",
                task_id=task_id,
                session_id="sess_interrupted",
                current_status=ResearchStatus.IN_PROGRESS,
                completed_chapters=(1, 2),
                pending_chapters=(3, 4),
                total_tokens_consumed=450000,
                total_duration_ms=180000.0,
            )
        )

        plan = engine.prepare_resumption(task_id)
        assert plan.can_resume is True
        assert plan.next_chapter_index == 3
        assert plan.completed_chapters_count == 2
        assert plan.pending_chapters_count == 2
        assert "Resuming Interrupted Long-Horizon Research Task" in plan.context_injection_prompt
        assert "Chapter 1: Historical Evolution" in plan.context_injection_prompt
        assert "Chapter 2: Runtime Reliability Bottlenecks" in plan.context_injection_prompt
        assert "Proceed directly to researching and drafting **Chapter 3**" in plan.context_injection_prompt
        assert "Do NOT re-execute tools or re-draft any previously completed chapters" in plan.context_injection_prompt

        ledger.close()
