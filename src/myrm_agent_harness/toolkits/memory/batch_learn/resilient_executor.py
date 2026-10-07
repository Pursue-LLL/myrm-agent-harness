"""[POS]: src/myrm_agent_harness/toolkits/memory/batch_learn/resilient_executor.py
[INPUT]: Raw chunk processor callable, chunk data, and ChunkRetryConfig.
[OUTPUT]: Resilient execution with exponential backoff and jitter, yielding typed ChunkExecutionRecord.
"""

import random
import time
from collections.abc import Callable

from myrm_agent_harness.toolkits.memory.batch_learn.models import (
    BatchRawChunk,
    ChunkExecutionRecord,
    ChunkProcessingStatus,
    ChunkRetryConfig,
)


class TransientMemoryProcessingError(Exception):
    """Exception representing transient errors such as rate limits (429) or network timeouts (503)."""


class PermanentMemoryProcessingError(Exception):
    """Exception representing unrecoverable schema validation or authorization errors."""


def is_transient_error(exc: Exception) -> bool:
    """Classify whether an exception qualifies for exponential retry."""
    if isinstance(exc, TransientMemoryProcessingError):
        return True
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True

    msg = str(exc).lower()
    transient_indicators = (
        "429",
        "502",
        "503",
        "504",
        "rate limit",
        "ratelimit",
        "too many requests",
        "timeout",
        "temporarily unavailable",
        "connection reset",
        "overloaded",
    )
    return any(indicator in msg for indicator in transient_indicators)


class ResilientChunkRetryExecutor:
    """Executes chunk-level extraction logic with isolated retry boundaries and jittered backoff."""

    def __init__(self, config: ChunkRetryConfig | None = None) -> None:
        self.config = config or ChunkRetryConfig()

    def execute_chunk(
        self,
        chunk: BatchRawChunk,
        processor_fn: Callable[[BatchRawChunk], list[str]],
    ) -> tuple[list[str], ChunkExecutionRecord]:
        """Execute extraction on a single chunk, handling transient errors without failing the parent batch."""
        start_time = time.time()
        last_error_message: str | None = None
        extracted_results: list[str] = []

        for attempt in range(self.config.max_retries + 1):
            try:
                extracted_results = processor_fn(chunk)
                elapsed_ms = (time.time() - start_time) * 1000.0
                status = (
                    ChunkProcessingStatus.RETRIED_SUCCESS
                    if attempt > 0
                    else ChunkProcessingStatus.SUCCESS
                )
                record = ChunkExecutionRecord(
                    chunk_index=chunk.chunk_index,
                    status=status,
                    attempt_count=attempt + 1,
                    elapsed_ms=elapsed_ms,
                    extracted_items_count=len(extracted_results),
                )
                return extracted_results, record

            except Exception as exc:
                last_error_message = f"{type(exc).__name__}: {exc}"
                if not is_transient_error(exc) or attempt >= self.config.max_retries:
                    elapsed_ms = (time.time() - start_time) * 1000.0
                    final_status = (
                        ChunkProcessingStatus.FAILED_TRANSIENT
                        if is_transient_error(exc)
                        else ChunkProcessingStatus.FAILED_PERMANENT
                    )
                    record = ChunkExecutionRecord(
                        chunk_index=chunk.chunk_index,
                        status=final_status,
                        attempt_count=attempt + 1,
                        elapsed_ms=elapsed_ms,
                        error_message=last_error_message,
                        extracted_items_count=0,
                    )
                    return [], record

                # Compute exponential backoff with full jitter
                base_delay = self.config.initial_delay_sec * (self.config.backoff_factor**attempt)
                capped_delay = min(self.config.max_delay_sec, base_delay)
                sleep_duration = (
                    random.uniform(0.0, capped_delay) if self.config.enable_jitter else capped_delay
                )
                time.sleep(sleep_duration)

        # Fallback safeguard
        elapsed_ms = (time.time() - start_time) * 1000.0
        record = ChunkExecutionRecord(
            chunk_index=chunk.chunk_index,
            status=ChunkProcessingStatus.FAILED_TRANSIENT,
            attempt_count=self.config.max_retries + 1,
            elapsed_ms=elapsed_ms,
            error_message=last_error_message or "Max retries exceeded",
            extracted_items_count=0,
        )
        return [], record
