"""Context offload: persist full tool outputs and conversation snapshots to persistent volume.

Provides out-of-the-box context offload callbacks for the Agent runtime.
Business layers inject strategy hooks (quota_checker, checkpointer, access_tracker)
while the framework handles compression, path management, metrics, and cleanup.

Tool output offload:
- Threshold: ≥5000 tokens → write file, <5000 tokens → in-memory compression only
- Path: /persistent/.context/{session_id}/compacted/sha256/{prefix}/{tool}_{hash}_{size}.txt[.gz]
- Compression: >10KB auto gzip for compressible text payloads
- Persistence: Docker Volume, survives Sleep/Destroy, lifecycle-managed by
  session activity and explicit file access records
- Isolation: deployment-level physical isolation; business identity stays outside this framework API
- Scope contract: archive offload requires scope_id; anonymous contexts do not share a default archive directory
- Monitoring: structured logs + metrics

Conversation snapshot:
- Trigger: before each context compression cycle
- Path: /persistent/.context/{session_id}/snapshots/{timestamp}_{uuid}.jsonl[.gz]
- Content: JSONL (one message per line), redacted via redact_leaks()
- Always gzip-compressed (conversation snapshots are large)

Smart cleanup strategy (Session-Aware):
1. Session active within 30 days → keep all files
2. File accessed within 14 days → keep file
3. Otherwise → remove (7-day fallback threshold)

Quota management (optional, via StorageQuotaChecker injection):
- Write-time quota check, raises QuotaExceededError on exceeded

Compression strategy:
- Smart threshold: >10KB to compress (small files have low compression benefit)
- Adaptive level: <100KB level 1, ≥100KB level 6 (based on benchmarks)
- Async compression: >100KB in thread pool (avoids blocking event loop)
- Fallback: auto degrade to uncompressed on failure

[INPUT]
- agent.context_management.infra.schemas::ContextCompressOffloadCallback, (POS: Planner Schema Definitions)
- runtime.quota.errors::QuotaExceededError (POS: Storage quota related errors.)
- runtime.quota.protocol::StorageQuotaChecker (POS: Storage quota checking protocol.)
- runtime.checkpoint_protocol::CheckpointerProtocol (POS: Protocol definition for checkpointer objects.)
- runtime.context.cleanup_ops::* (POS: Runtime context cleanup operations. Owns session directory cleanup and orphan cleanup entrypoints.)
- runtime.context.file_access_tracker::get_file_access_tracker (POS: Context archive access tracking)
- toolkits.code_execution.executors.base::CodeExecutor (POS: Code executor base classes.)

[OUTPUT]
- create_context_snapshot_callback: Build async callback: serialize full messages to gzip-com...
- create_compress_offload_callback: Build async callback: write full tool content before comp...
- cleanup_session_context_files: re-export session context cleanup.
- cleanup_orphan_context_files_async: re-export session-aware orphan cleanup.
- cleanup_orphan_context_files: re-export local orphan cleanup.

[POS]
Context offload: persist full tool outputs and conversation snapshots to persistent volume.
"""

from __future__ import annotations

import json
import logging
import time
from hashlib import sha256
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.context_management.infra.schemas import (
    ContextCompressOffloadCallback,
    ContextOffloadResult,
    ContextSnapshotCallback,
)
from myrm_agent_harness.runtime.compression import (
    compress_content_async,
    get_adaptive_compression_level,
    should_compress,
)
from myrm_agent_harness.runtime.context.archive_store import (
    find_content_addressed_archive,
    store_content_addressed_archive,
)
from myrm_agent_harness.runtime.context.cleanup_ops import (
    cleanup_orphan_context_files,
    cleanup_orphan_context_files_async,
    cleanup_session_context_files,
)
from myrm_agent_harness.runtime.context.instance_metrics import (
    record_compression,
    record_offload_failure,
    record_offload_success,
)
from myrm_agent_harness.runtime.execution_paths import (
    _sanitize_path_segment,
    ensure_context_dir_exists,
    get_snapshot_path,
    get_workspace_relative_path,
)
from myrm_agent_harness.runtime.quota.errors import QuotaExceededError
from myrm_agent_harness.runtime.quota.protocols import StorageQuotaChecker

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage

    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor

logger = logging.getLogger(__name__)

__all__ = [
    "cleanup_orphan_context_files",
    "cleanup_orphan_context_files_async",
    "cleanup_session_context_files",
    "create_compress_offload_callback",
    "create_context_snapshot_callback",
]


async def _record_context_archive_access(path: str, session_id: str) -> None:
    """Record archive creation/access for lifecycle retention decisions."""
    try:
        from myrm_agent_harness.runtime.context.file_access_tracker import (
            get_file_access_tracker,
        )

        tracker = await get_file_access_tracker()
        await tracker.record_access(path, session_id=session_id)
    except Exception as exc:
        logger.debug(
            "Context archive access tracking skipped path=%s session=%s: %s",
            path,
            _sanitize_path_segment(session_id),
            exc,
        )


def _serialize_message(msg: BaseMessage) -> str:
    """Serialize a single LangChain message to a redacted JSON line."""
    from myrm_agent_harness.agent.security.detection.leak_detector import redact_leaks

    try:
        record: dict[str, object] = {
            "type": msg.type,
            "id": getattr(msg, "id", None),
            "content": msg.content,
        }
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            record["tool_calls"] = msg.tool_calls
        if hasattr(msg, "tool_call_id") and msg.tool_call_id:
            record["tool_call_id"] = msg.tool_call_id
        if hasattr(msg, "name") and msg.name:
            record["name"] = msg.name
        if msg.additional_kwargs:
            record["additional_kwargs"] = msg.additional_kwargs

        line = json.dumps(record, ensure_ascii=False, default=str)
        return redact_leaks(line)
    except Exception:
        return json.dumps({"type": msg.type, "error": "serialization_failed"}, ensure_ascii=False)


def create_context_snapshot_callback(
    executor: CodeExecutor,
    quota_checker: StorageQuotaChecker | None = None,
) -> ContextSnapshotCallback:
    """Build async callback: serialize full messages to gzip-compressed JSONL before compaction.

    Each snapshot file contains:
    - Line 1: JSON metadata header (timestamp, message count, session/user IDs)
    - Lines 2+: one message per line, redacted via redact_leaks()

    The file is always gzip-compressed to minimize storage footprint.

    Args:
        executor: Code executor for file operations
        quota_checker: Optional quota checker for write-time quota validation
    """

    async def snapshot(
        *,
        messages: list[BaseMessage],
        chat_id: str | None,
        user_id: str | None,
    ) -> str:
        session_id = chat_id or "default"

        header: dict[str, object] = {
            "_meta": True,
            "timestamp": time.time(),
            "message_count": len(messages),
            "chat_id": chat_id,
            "user_id": user_id,
        }
        lines = [json.dumps(header, ensure_ascii=False)]
        lines.extend(_serialize_message(msg) for msg in messages)

        content = "\n".join(lines)
        content_bytes = content.encode("utf-8")
        original_size = len(content_bytes)

        abs_path = get_snapshot_path(session_id, compressed=True)
        rel_path = get_workspace_relative_path(abs_path)

        start = time.perf_counter()
        try:
            ensure_context_dir_exists(session_id, "snapshots")

            compression_level = get_adaptive_compression_level(original_size)
            compressed_bytes = await compress_content_async(
                content_bytes,
                level=compression_level,
                adaptive=False,
            )
            compressed_size = len(compressed_bytes)

            if quota_checker is not None and not await quota_checker.check_write_allowed(
                session_id,
                compressed_size,
            ):
                remaining = await quota_checker.get_remaining_quota(session_id)
                raise QuotaExceededError(
                    f"Storage quota exceeded for session {session_id}",
                    session_id=session_id,
                    requested_bytes=compressed_size,
                    available_bytes=remaining,
                )

            await executor.write_file_bytes(rel_path, compressed_bytes)
            await _record_context_archive_access(abs_path, session_id)
            duration_ms = (time.perf_counter() - start) * 1000
            ratio = original_size / compressed_size if compressed_size > 0 else 1.0

            logger.info(
                "CONTEXT_SNAPSHOT path=%s session=%s messages=%d bytes=%d compressed=%d ratio=%.2f duration_ms=%.1f",
                rel_path,
                _sanitize_path_segment(session_id),
                len(messages),
                original_size,
                compressed_size,
                ratio,
                duration_ms,
            )
            record_offload_success("context_snapshot", original_size, duration_ms / 1000)
            record_compression(original_size, compressed_size, duration_ms / 1000)

        except QuotaExceededError:
            raise
        except Exception as exc:
            logger.warning(
                "Context snapshot write failed for session=%s: %s",
                _sanitize_path_segment(session_id),
                exc,
            )
            record_offload_failure("context_snapshot")
            return ""

        return rel_path

    return snapshot


def create_compress_offload_callback(
    executor: CodeExecutor,
    enable_compression: bool = True,
    compression_threshold: int = 10240,
    quota_checker: StorageQuotaChecker | None = None,
) -> ContextCompressOffloadCallback:
    """Build async callback: write full tool content before compaction, return workspace-relative path.

    Path format: /persistent/.context/{session_id}/compacted/sha256/{prefix}/{tool}_{hash}_{size}.txt[.gz]
    Isolated by session with content-addressed retry reuse and normalized subdirectory
    structure for batch cleanup.

    Args:
        executor: Code executor for file operations
        enable_compression: Enable gzip compression for large files (default: True)
        compression_threshold: Minimum file size to compress in bytes (default: 10KB)
        quota_checker: Optional quota checker for write-time quota validation
    """

    async def offload(
        *,
        content: str,
        tool_name: str,
        scope_id: str | None,
    ) -> ContextOffloadResult:
        if not scope_id:
            return ContextOffloadResult.failure(
                "unsupported",
                "scope_id is required for context archive offload",
            )

        session_id = scope_id
        content_bytes = content.encode("utf-8")
        original_size = len(content_bytes)
        content_sha = sha256(content_bytes).hexdigest()
        use_compression = enable_compression and should_compress(original_size, compression_threshold)

        start = time.perf_counter()
        try:
            ensure_context_dir_exists(session_id, "compacted")

            async def check_quota(write_size: int) -> None:
                if quota_checker is None:
                    return
                if not await quota_checker.check_write_allowed(session_id, write_size):
                    remaining = await quota_checker.get_remaining_quota(session_id)
                    raise QuotaExceededError(
                        f"Storage quota exceeded for session {session_id}",
                        session_id=session_id,
                        requested_bytes=write_size,
                        available_bytes=remaining,
                    )

            existing_archive = await find_content_addressed_archive(
                executor=executor,
                session_id=session_id,
                tool_name=tool_name,
                content_sha256=content_sha,
                original_bytes=original_size,
                compressed=use_compression,
                restore_source=content,
                before_write=check_quota,
            )
            if existing_archive is not None:
                await _record_context_archive_access(existing_archive.abs_path, session_id)
                duration_seconds = time.perf_counter() - start
                logger.info(
                    "CONTEXT_OFFLOAD_REUSED path=%s tool=%s session=%s bytes=%d stored=%d compressed=%s duration_ms=%.1f",
                    existing_archive.rel_path,
                    _sanitize_path_segment(tool_name),
                    _sanitize_path_segment(session_id),
                    original_size,
                    existing_archive.stored_bytes,
                    use_compression,
                    duration_seconds * 1000,
                )
                return ContextOffloadResult.success(
                    existing_archive.rel_path,
                    reused=True,
                    original_bytes=existing_archive.original_bytes,
                    stored_bytes=existing_archive.stored_bytes,
                )

            content_to_write: bytes | str
            if use_compression:
                compression_start = time.perf_counter()
                try:
                    compression_level = get_adaptive_compression_level(original_size)
                    content_to_write = await compress_content_async(
                        content_bytes,
                        level=compression_level,
                        adaptive=False,
                    )
                    compression_duration = time.perf_counter() - compression_start
                    compressed_size = len(content_to_write)
                    record_compression(original_size, compressed_size, compression_duration)
                except Exception as compression_error:
                    logger.warning(
                        "Compression failed for tool=%s session=%s bytes=%d, writing uncompressed: %s",
                        _sanitize_path_segment(tool_name),
                        _sanitize_path_segment(session_id),
                        original_size,
                        compression_error,
                    )
                    content_to_write = content
                    compressed_size = original_size
                    use_compression = False
            else:
                content_to_write = content
                compressed_size = original_size

            archive_write = await store_content_addressed_archive(
                executor=executor,
                session_id=session_id,
                tool_name=tool_name,
                content_sha256=content_sha,
                original_bytes=original_size,
                stored_content=content_to_write,
                compressed=use_compression,
                restore_source=content,
                before_write=check_quota,
            )
            if archive_write.reused:
                await _record_context_archive_access(archive_write.abs_path, session_id)
                duration_seconds = time.perf_counter() - start
                logger.info(
                    "CONTEXT_OFFLOAD_REUSED path=%s tool=%s session=%s bytes=%d stored=%d compressed=%s duration_ms=%.1f",
                    archive_write.rel_path,
                    _sanitize_path_segment(tool_name),
                    _sanitize_path_segment(session_id),
                    original_size,
                    archive_write.stored_bytes,
                    use_compression,
                    duration_seconds * 1000,
                )
                return ContextOffloadResult.success(
                    archive_write.rel_path,
                    reused=True,
                    original_bytes=archive_write.original_bytes,
                    stored_bytes=archive_write.stored_bytes,
                )

            await _record_context_archive_access(archive_write.abs_path, session_id)
            duration_seconds = time.perf_counter() - start
            duration_ms = duration_seconds * 1000

            compression_ratio = original_size / compressed_size if use_compression else 1.0

            logger.info(
                "CONTEXT_OFFLOAD path=%s tool=%s session=%s bytes=%d compressed=%s ratio=%.2f duration_ms=%.1f",
                archive_write.rel_path,
                _sanitize_path_segment(tool_name),
                _sanitize_path_segment(session_id),
                original_size,
                use_compression,
                compression_ratio,
                duration_ms,
            )

            record_offload_success(tool_name, original_size, duration_seconds)

        except QuotaExceededError:
            raise
        except OSError as exc:
            logger.warning("Context compress offload write failed (OSError): %s", exc)
            record_offload_failure(tool_name)
            return ContextOffloadResult.failure("temporary_failure", str(exc))
        except Exception as exc:
            logger.warning("Context compress offload write failed: %s", exc)
            record_offload_failure(tool_name)
            return ContextOffloadResult.failure("temporary_failure", str(exc))
        return ContextOffloadResult.success(
            archive_write.rel_path,
            reused=False,
            original_bytes=archive_write.original_bytes,
            stored_bytes=archive_write.stored_bytes,
        )

    return offload
