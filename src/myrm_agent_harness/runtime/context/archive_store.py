"""Content-addressed context archive storage.

[INPUT]
- runtime.execution_paths::* (POS: stable context archive paths)
- toolkits.code_execution.executors.base::CodeExecutor (POS: sandbox file operations)

[OUTPUT]
- ContentAddressedArchiveWrite: stored archive write/reuse result.
- find_content_addressed_archive: look up a previously written archive without rewriting.
- store_content_addressed_archive: session-scoped idempotent archive write helper with atomic payload,
  metadata, and restore-map sidecar writes.

[POS]
Runtime context archive store. Provides retry-safe, session-scoped content-addressed writes and
targeted restore-map sidecars for large tool-result offload without cross-user deduplication.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING

from myrm_agent_harness.runtime.context.restore_map_contract import (
    build_restore_map_json,
    restore_map_payload_is_valid,
)
from myrm_agent_harness.runtime.execution_paths import (
    get_content_addressed_compacted_metadata_path,
    get_content_addressed_compacted_output_path,
    get_content_addressed_compacted_restore_map_path,
    get_workspace_relative_path,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor

_ARCHIVE_SCHEMA_VERSION = 1
_archive_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


@dataclass(frozen=True, slots=True)
class ContentAddressedArchiveWrite:
    """Result of a content-addressed archive write attempt."""

    abs_path: str
    rel_path: str
    metadata_abs_path: str
    metadata_rel_path: str
    restore_map_abs_path: str
    restore_map_rel_path: str
    reused: bool
    original_bytes: int
    stored_bytes: int


async def store_content_addressed_archive(
    *,
    executor: CodeExecutor,
    session_id: str,
    tool_name: str,
    content_sha256: str,
    original_bytes: int,
    stored_content: bytes | str,
    compressed: bool,
    restore_source: str | None = None,
    before_write: Callable[[int], Awaitable[None]] | None = None,
) -> ContentAddressedArchiveWrite:
    """Write compacted output once per session/content hash and reuse it on retry.

    The lock prevents duplicate writes inside one agent-server process. Cross-process
    races are still safe because contenders write the same content to the same path,
    and metadata is validated before reuse on later calls.
    """
    abs_path = get_content_addressed_compacted_output_path(
        session_id,
        tool_name,
        content_sha256,
        original_bytes,
        compressed=compressed,
    )
    metadata_abs_path = get_content_addressed_compacted_metadata_path(
        session_id,
        tool_name,
        content_sha256,
        original_bytes,
        compressed=compressed,
    )
    restore_map_abs_path = get_content_addressed_compacted_restore_map_path(
        session_id,
        tool_name,
        content_sha256,
        original_bytes,
        compressed=compressed,
    )
    rel_path = get_workspace_relative_path(abs_path)
    metadata_rel_path = get_workspace_relative_path(metadata_abs_path)
    restore_map_rel_path = get_workspace_relative_path(restore_map_abs_path)
    stored_bytes = _content_size(stored_content)
    stored_sha256 = _content_sha256(stored_content)
    restore_map_json = build_restore_map_json(rel_path, restore_source)
    lock = _archive_locks[rel_path]

    async with lock:
        if await _existing_archive_is_valid(
            executor=executor,
            rel_path=rel_path,
            metadata_rel_path=metadata_rel_path,
            content_sha256=content_sha256,
            original_bytes=original_bytes,
            stored_bytes=stored_bytes,
            stored_sha256=stored_sha256,
            compressed=compressed,
        ):
            if restore_map_json is not None and not await _restore_map_is_valid(
                executor,
                restore_map_rel_path=restore_map_rel_path,
                archive_path=rel_path,
            ):
                if before_write is not None:
                    await before_write(_content_size(restore_map_json))
                await executor.write_file_atomic(restore_map_rel_path, restore_map_json)
            return ContentAddressedArchiveWrite(
                abs_path=abs_path,
                rel_path=rel_path,
                metadata_abs_path=metadata_abs_path,
                metadata_rel_path=metadata_rel_path,
                restore_map_abs_path=restore_map_abs_path,
                restore_map_rel_path=restore_map_rel_path,
                reused=True,
                original_bytes=original_bytes,
                stored_bytes=stored_bytes,
            )

        if before_write is not None:
            await before_write(stored_bytes + (_content_size(restore_map_json) if restore_map_json is not None else 0))

        if isinstance(stored_content, bytes):
            await executor.write_file_bytes_atomic(rel_path, stored_content)
        else:
            await executor.write_file_atomic(rel_path, stored_content)
        if restore_map_json is not None:
            await executor.write_file_atomic(restore_map_rel_path, restore_map_json)
        await executor.write_file_atomic(
            metadata_rel_path,
            json.dumps(
                {
                    "schema_version": _ARCHIVE_SCHEMA_VERSION,
                    "tool_name": tool_name,
                    "content_sha256": content_sha256,
                    "original_bytes": original_bytes,
                    "stored_bytes": stored_bytes,
                    "stored_sha256": stored_sha256,
                    "compressed": compressed,
                    "created_at": time.time(),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        )

    return ContentAddressedArchiveWrite(
        abs_path=abs_path,
        rel_path=rel_path,
        metadata_abs_path=metadata_abs_path,
        metadata_rel_path=metadata_rel_path,
        restore_map_abs_path=restore_map_abs_path,
        restore_map_rel_path=restore_map_rel_path,
        reused=False,
        original_bytes=original_bytes,
        stored_bytes=stored_bytes,
    )


async def find_content_addressed_archive(
    *,
    executor: CodeExecutor,
    session_id: str,
    tool_name: str,
    content_sha256: str,
    original_bytes: int,
    compressed: bool,
    restore_source: str | None = None,
    before_write: Callable[[int], Awaitable[None]] | None = None,
) -> ContentAddressedArchiveWrite | None:
    """Return an existing valid content-addressed archive, if present."""
    abs_path = get_content_addressed_compacted_output_path(
        session_id,
        tool_name,
        content_sha256,
        original_bytes,
        compressed=compressed,
    )
    metadata_abs_path = get_content_addressed_compacted_metadata_path(
        session_id,
        tool_name,
        content_sha256,
        original_bytes,
        compressed=compressed,
    )
    restore_map_abs_path = get_content_addressed_compacted_restore_map_path(
        session_id,
        tool_name,
        content_sha256,
        original_bytes,
        compressed=compressed,
    )
    rel_path = get_workspace_relative_path(abs_path)
    metadata_rel_path = get_workspace_relative_path(metadata_abs_path)
    restore_map_rel_path = get_workspace_relative_path(restore_map_abs_path)
    metadata = await _read_valid_metadata(
        executor=executor,
        rel_path=rel_path,
        metadata_rel_path=metadata_rel_path,
        content_sha256=content_sha256,
        original_bytes=original_bytes,
        compressed=compressed,
    )
    if metadata is None:
        return None
    restore_map_json = build_restore_map_json(rel_path, restore_source)
    if restore_map_json is not None and not await _restore_map_is_valid(
        executor,
        restore_map_rel_path=restore_map_rel_path,
        archive_path=rel_path,
    ):
        if before_write is not None:
            await before_write(_content_size(restore_map_json))
        await executor.write_file_atomic(restore_map_rel_path, restore_map_json)
    stored_bytes = metadata.get("stored_bytes")
    return ContentAddressedArchiveWrite(
        abs_path=abs_path,
        rel_path=rel_path,
        metadata_abs_path=metadata_abs_path,
        metadata_rel_path=metadata_rel_path,
        restore_map_abs_path=restore_map_abs_path,
        restore_map_rel_path=restore_map_rel_path,
        reused=True,
        original_bytes=original_bytes,
        stored_bytes=stored_bytes if isinstance(stored_bytes, int) and stored_bytes >= 0 else 0,
    )


async def _existing_archive_is_valid(
    *,
    executor: CodeExecutor,
    rel_path: str,
    metadata_rel_path: str,
    content_sha256: str,
    original_bytes: int,
    stored_bytes: int,
    stored_sha256: str,
    compressed: bool,
) -> bool:
    metadata = await _read_valid_metadata(
        executor=executor,
        rel_path=rel_path,
        metadata_rel_path=metadata_rel_path,
        content_sha256=content_sha256,
        original_bytes=original_bytes,
        compressed=compressed,
    )
    if metadata is None:
        return False
    return metadata.get("stored_bytes") == stored_bytes and metadata.get("stored_sha256") == stored_sha256


async def _read_valid_metadata(
    *,
    executor: CodeExecutor,
    rel_path: str,
    metadata_rel_path: str,
    content_sha256: str,
    original_bytes: int,
    compressed: bool,
) -> dict[str, object] | None:
    if not await executor.file_exists(rel_path):
        return None
    if not await executor.file_exists(metadata_rel_path):
        return None

    try:
        metadata = json.loads(await executor.read_file(metadata_rel_path))
    except Exception:
        return None

    if not isinstance(metadata, dict):
        return None
    if (
        metadata.get("schema_version") == _ARCHIVE_SCHEMA_VERSION
        and metadata.get("content_sha256") == content_sha256
        and metadata.get("original_bytes") == original_bytes
        and metadata.get("compressed") is compressed
    ):
        stored_bytes = metadata.get("stored_bytes")
        stored_sha256 = metadata.get("stored_sha256")
        if not isinstance(stored_bytes, int) or stored_bytes < 0:
            return None
        if not isinstance(stored_sha256, str) or not stored_sha256:
            return None
        try:
            stored_content = await executor.read_file_bytes(rel_path)
        except Exception:
            return None
        if len(stored_content) != stored_bytes:
            return None
        if sha256(stored_content).hexdigest() != stored_sha256:
            return None
        return metadata
    return None


def _content_size(content: bytes | str) -> int:
    if isinstance(content, bytes):
        return len(content)
    return len(content.encode("utf-8"))


def _content_sha256(content: bytes | str) -> str:
    if isinstance(content, str):
        content = content.encode("utf-8")
    return sha256(content).hexdigest()


async def _restore_map_is_valid(
    executor: CodeExecutor,
    *,
    restore_map_rel_path: str,
    archive_path: str,
) -> bool:
    if not await executor.file_exists(restore_map_rel_path):
        return False
    try:
        payload = json.loads(await executor.read_file(restore_map_rel_path))
    except Exception:
        return False
    return restore_map_payload_is_valid(payload, archive_path)
