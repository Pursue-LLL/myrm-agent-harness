"""Chunked batch pipeline coordinator with skip-ahead resilient resumption.

Benchmarked against OpenAI Codex Computer Use Principle 2 (Batch Pipeline Chunking):
- Orchestrates multi-step GUI and automated data processing in atomic chunks (3-5 items per batch).
- Integrates with RowCheckpointManifest to atomically record success/failure for every item.
- Implements skip-ahead resumption: automatically bypasses previously completed rows on resume.
- Renders rich GitHub Flavored Markdown progress cards for monitoring and auditing.

[OUTPUT]
- BatchChunkingPipeline: Orchestrates chunked execution and seamless checkpoint resumption.

[INPUT]
- __future__
- collections

[OUTPUT]
- RowProcessCallback
- BatchChunkingPipeline

[POS]
Chunked batch pipeline coordinator with skip-ahead resilient resumption.
"""

from __future__ import annotations

from collections.abc import Callable

from myrm_agent_harness.runtime.gui_chunking.chunking_types import (
    BatchPipelineProgress,
    RowCheckpointItem,
)
from myrm_agent_harness.runtime.gui_chunking.row_checkpoint_manifest import (
    RowCheckpointManifest,
)

# Signature for row processing worker: receives RowCheckpointItem, returns (is_success, proof_path_or_err)
RowProcessCallback = Callable[[RowCheckpointItem], tuple[bool, str]]


class BatchChunkingPipeline:
    """Coordinates batch pipeline execution in manageable chunks with skip-ahead resumption."""

    def __init__(
        self,
        manifest: RowCheckpointManifest,
        default_chunk_size: int = 5,
    ) -> None:
        self.manifest = manifest
        self.chunk_size = max(1, default_chunk_size)

    def run_next_chunk(
        self,
        worker_fn: RowProcessCallback,
        chunk_size: int | None = None,
    ) -> tuple[int, int]:
        """Execute a single atomic chunk of pending items.

        Returns:
            Tuple of (items_processed_in_this_chunk, total_remaining_pending_items).
        """
        batch_limit = chunk_size or self.chunk_size
        pending = self.manifest.get_pending_rows()
        to_process = pending[:batch_limit]

        processed_count = 0
        for item in to_process:
            try:
                success, proof_or_err = worker_fn(item)
                if success:
                    self.manifest.mark_success(item.row_id, proof_path=proof_or_err)
                else:
                    self.manifest.mark_failed(item.row_id, error_msg=proof_or_err)
            except Exception as exc:
                self.manifest.mark_failed(item.row_id, error_msg=str(exc))
                processed_count += 1
                break

            processed_count += 1

        remaining = len(self.manifest.get_pending_rows())
        return processed_count, remaining

    def resume_until_complete(
        self,
        worker_fn: RowProcessCallback,
        chunk_size: int | None = None,
        max_chunks: int = 1000,
    ) -> BatchPipelineProgress:
        """Continuously process chunks with skip-ahead resumption until all rows finish or max_chunks reached."""
        batch_limit = chunk_size or self.chunk_size
        chunk_idx = 0

        while chunk_idx < max_chunks:
            pending = self.manifest.get_pending_rows()
            if not pending:
                break

            self.run_next_chunk(worker_fn, chunk_size=batch_limit)
            chunk_idx += 1

        return self.manifest.get_progress()

    def render_progress_markdown(self, progress: BatchPipelineProgress) -> str:
        """Render a GitHub Flavored Markdown card showing current batch execution progress."""
        pct = (
            int((progress.completed_rows / progress.total_rows) * 100)
            if progress.total_rows > 0
            else 0
        )

        lines: list[str] = [
            "### 📊 GUI 自动化分段批处理进度卡片",
            f"- **流水线 ID**: `{progress.pipeline_id}`",
            f"- **当前阶段**: `{progress.stage.value}`",
            f"- **总行数**: `{progress.total_rows}`",
            f"- **已完成行数**: `{progress.completed_rows}` ({pct}%)",
            f"- **失败行数**: `{progress.failed_rows}`",
            f"- **剩余待处理**: `{progress.remaining_rows}`",
            f"- **清单路径**: `{progress.manifest_path}`",
            "",
        ]

        if progress.is_finished:
            lines.extend(
                [
                    "> [!NOTE]",
                    "> 所有分段行级任务已全量完成，中间状态检查点已完全持久化。",
                ]
            )
        elif progress.failed_rows > 0:
            lines.extend(
                [
                    "> [!WARNING]",
                    f"> 检测到 {progress.failed_rows} 条记录执行失败。断点续跑将自动跳过已成功的 {progress.completed_rows} 行，并仅对未决项发起重试。",
                ]
            )
        else:
            lines.extend(
                [
                    "> [!TIP]",
                    f"> 批处理正常推进中，每次分段提交 {self.chunk_size} 步操作以保障上下文洁净与防假死。",
                ]
            )

        return "\n".join(lines)
