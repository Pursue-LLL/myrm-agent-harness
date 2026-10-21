"""Unit tests for RowCheckpointManifest and BatchChunkingPipeline.

Tests benchmarked against OpenAI Codex Computer Use Principle 2 (Chunked Pipelines & Checkpoint Files):
1. Atomic filesystem persistence of row checkpoints and full state recovery on reload.
2. Step-by-step chunked batch execution (3-5 items per batch).
3. Skip-ahead resilient resumption: guarantees previously completed rows are never re-executed.
4. Markdown progress card rendering.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from myrm_agent_harness.runtime.gui_chunking import (
    BatchChunkingPipeline,
    PipelineStageKind,
    RowCheckpointItem,
    RowCheckpointManifest,
    RowProcessingStatus,
)


def test_row_checkpoint_manifest_atomic_persistence() -> None:
    """Test initializing manifest, updating row status, and reloading from disk."""
    with tempfile.TemporaryDirectory() as tmpdir:
        manifest_file = Path(tmpdir) / "progress_manifest.json"
        manifest = RowCheckpointManifest(manifest_file)

        initial_rows = [
            ("row_1", {"customer_id": "cust_101", "amount": "500"}),
            ("row_2", {"customer_id": "cust_102", "amount": "1200"}),
            ("row_3", {"customer_id": "cust_103", "amount": "300"}),
        ]

        manifest.init_manifest("pipe_test_01", initial_rows, PipelineStageKind.BATCH_EXECUTION)
        assert manifest_file.exists()

        # Update row_1 as success with screenshot proof
        manifest.mark_success("row_1", proof_path="outputs/proofs/row_1.png")
        # Update row_2 as failed
        manifest.mark_failed("row_2", error_msg="Form input validation error")

        # Reload from disk into a fresh manifest instance
        reloaded = RowCheckpointManifest(manifest_file)
        assert reloaded.pipeline_id == "pipe_test_01"
        assert reloaded.stage == PipelineStageKind.BATCH_EXECUTION

        r1 = reloaded.get_row("row_1")
        assert r1 is not None
        assert r1.status == RowProcessingStatus.SUCCESS
        assert r1.proof_artifact_path == "outputs/proofs/row_1.png"

        r2 = reloaded.get_row("row_2")
        assert r2 is not None
        assert r2.status == RowProcessingStatus.FAILED
        assert "Form input validation error" in r2.error_message

        progress = reloaded.get_progress()
        assert progress.total_rows == 3
        assert progress.completed_rows == 1
        assert progress.failed_rows == 1
        assert progress.remaining_rows == 2  # row_2 (failed) and row_3 (pending)


def test_batch_chunking_pipeline_execution() -> None:
    """Test chunked execution in batches of 3 items."""
    with tempfile.TemporaryDirectory() as tmpdir:
        manifest_file = Path(tmpdir) / "manifest_chunks.json"
        manifest = RowCheckpointManifest(manifest_file)

        rows = [(f"item_{i}", {"index": str(i)}) for i in range(7)]
        manifest.init_manifest("pipe_chunks", rows)

        pipeline = BatchChunkingPipeline(manifest, default_chunk_size=3)

        # Execution function
        def worker(item: RowCheckpointItem) -> tuple[bool, str]:
            return True, f"outputs/{item.row_id}.png"

        # Chunk 1: processes 3, remaining 4
        processed, remaining = pipeline.run_next_chunk(worker)
        assert processed == 3
        assert remaining == 4

        # Chunk 2: processes 3, remaining 1
        processed, remaining = pipeline.run_next_chunk(worker)
        assert processed == 3
        assert remaining == 1

        # Chunk 3: processes 1, remaining 0
        processed, remaining = pipeline.run_next_chunk(worker)
        assert processed == 1
        assert remaining == 0

        progress = manifest.get_progress()
        assert progress.is_finished is True
        assert progress.completed_rows == 7


def test_skip_ahead_resilient_resume_on_interruption() -> None:
    """Test skip-ahead resumption: previously completed items are 100% skipped upon restart."""
    with tempfile.TemporaryDirectory() as tmpdir:
        manifest_file = Path(tmpdir) / "manifest_resume.json"
        manifest = RowCheckpointManifest(manifest_file)

        rows = [(f"tx_{i}", {"data": f"record_{i}"}) for i in range(5)]
        manifest.init_manifest("pipe_interrupted", rows)

        call_log: list[str] = []

        def worker_flaky(item: RowCheckpointItem) -> tuple[bool, str]:
            call_log.append(item.row_id)
            if item.row_id == "tx_2":
                # Simulated crash / network disruption at tx_2
                raise ConnectionResetError("Simulated network drop")
            return True, "proof.png"

        pipeline = BatchChunkingPipeline(manifest, default_chunk_size=10)

        # Run until crash occurs at tx_2
        pipeline.run_next_chunk(worker_flaky)

        # Verify tx_0, tx_1 succeeded, tx_2 marked failed
        assert manifest.get_row("tx_0") is not None and manifest.get_row("tx_0").status == RowProcessingStatus.SUCCESS  # type: ignore[union-attr]
        assert manifest.get_row("tx_1") is not None and manifest.get_row("tx_1").status == RowProcessingStatus.SUCCESS  # type: ignore[union-attr]
        assert manifest.get_row("tx_2") is not None and manifest.get_row("tx_2").status == RowProcessingStatus.FAILED  # type: ignore[union-attr]

        # RESTART PHASE: new process re-opens manifest
        manifest_resumed = RowCheckpointManifest(manifest_file)
        pipeline_resumed = BatchChunkingPipeline(manifest_resumed, default_chunk_size=10)

        call_log_resume: list[str] = []

        def worker_healthy(item: RowCheckpointItem) -> tuple[bool, str]:
            call_log_resume.append(item.row_id)
            return True, "proof_resumed.png"

        # Resume execution
        final_progress = pipeline_resumed.resume_until_complete(worker_healthy)

        # CRITICAL ASSERTION: tx_0 and tx_1 must NEVER be re-invoked
        assert "tx_0" not in call_log_resume
        assert "tx_1" not in call_log_resume
        # tx_2 (failed earlier), tx_3, tx_4 are processed
        assert call_log_resume == ["tx_2", "tx_3", "tx_4"]
        assert final_progress.is_finished is True
        assert final_progress.completed_rows == 5


def test_progress_markdown_card_rendering() -> None:
    """Test formatting and badge rendering of execution progress markdown cards."""
    with tempfile.TemporaryDirectory() as tmpdir:
        manifest_file = Path(tmpdir) / "manifest_md.json"
        manifest = RowCheckpointManifest(manifest_file)
        manifest.init_manifest("pipe_md", [("r1", {}), ("r2", {})])
        pipeline = BatchChunkingPipeline(manifest)

        # In-progress card
        prog_running = manifest.get_progress()
        md_running = pipeline.render_progress_markdown(prog_running)
        assert "### 📊 GUI 自动化分段批处理进度卡片" in md_running
        assert "> [!TIP]" in md_running

        # Completed card
        manifest.mark_success("r1")
        manifest.mark_success("r2")
        prog_done = manifest.get_progress()
        md_done = pipeline.render_progress_markdown(prog_done)
        assert "> [!NOTE]" in md_done
        assert "所有分段行级任务已全量完成" in md_done
