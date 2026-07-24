"""Stdin writes for live background bash registry entries.

[INPUT]
- _background_registry_consume::BackgroundRegistryEntry (POS: live proc handle)

[OUTPUT]
- write_background_stdin: Send bytes to a running child's stdin (optional newline / EOF)

[POS]
Isolated stdin I/O helper — keeps BackgroundProcessRegistry under size budget.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.agent.meta_tools.bash._background_registry_consume import (
        BackgroundRegistryEntry,
    )

logger = logging.getLogger(__name__)

_STDIN_MAX_BYTES = 64 * 1024


async def write_background_stdin(
    entry: BackgroundRegistryEntry,
    data: str,
    *,
    append_newline: bool = False,
    close: bool = False,
) -> dict[str, object]:
    """Write to a background job's stdin. Returns structured status for tools/REST."""
    if entry.info.status != "running":
        return {
            "ok": False,
            "error": "not_running",
            "status": entry.info.status,
            "pid": entry.info.pid,
        }

    stdin = entry.proc.stdin
    if stdin is None:
        return {
            "ok": False,
            "error": "no_stdin",
            "pid": entry.info.pid,
        }

    payload = data.encode("utf-8")
    if append_newline:
        payload = payload + b"\n"
    if len(payload) > _STDIN_MAX_BYTES:
        return {
            "ok": False,
            "error": "stdin_too_large",
            "max_bytes": _STDIN_MAX_BYTES,
            "pid": entry.info.pid,
        }

    if entry.stdin_lock is None:
        entry.stdin_lock = asyncio.Lock()

    async with entry.stdin_lock:
        if close and not payload:
            writer = stdin
            if hasattr(writer, "close"):
                writer.close()  # type: ignore[union-attr]
                if hasattr(writer, "wait_closed"):
                    await writer.wait_closed()  # type: ignore[union-attr]
            return {
                "ok": True,
                "pid": entry.info.pid,
                "bytes_written": 0,
                "closed": True,
            }

        writer = stdin
        if not hasattr(writer, "write"):
            return {"ok": False, "error": "stdin_not_writable", "pid": entry.info.pid}

        writer.write(payload)  # type: ignore[union-attr]
        if hasattr(writer, "drain"):
            await writer.drain()  # type: ignore[union-attr]

        if close and hasattr(writer, "close"):
            writer.close()  # type: ignore[union-attr]
            if hasattr(writer, "wait_closed"):
                await writer.wait_closed()  # type: ignore[union-attr]

    logger.info(
        "background stdin pid=%s bytes=%d newline=%s close=%s",
        entry.info.pid,
        len(payload),
        append_newline,
        close,
    )
    return {
        "ok": True,
        "pid": entry.info.pid,
        "bytes_written": len(payload),
        "append_newline": append_newline,
        "closed": close,
    }
