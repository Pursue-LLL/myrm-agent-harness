"""Stdout/stderr reader loop for a single background bash registry entry.

[INPUT]
- agent.meta_tools.bash._background_types::BackgroundProcessInfo (POS: job snapshot)
- toolkits.code_execution.executors.models::AsyncProcessProtocol (POS: async process handle)

[OUTPUT]
- BackgroundRegistryEntry: Live registry row with ring buffers and spill writer
- consume_background_entry: Read pipes until exit, persist terminal state, invoke finish hook

[POS]
I/O consumer for BackgroundProcessRegistry — keeps registry orchestration separate from pipe reading.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.meta_tools.bash._background_types import (
    BackgroundProcessInfo,
    FinishListener,
    ProgressListener,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.code_execution.executors.models import AsyncProcessProtocol
    from myrm_agent_harness.agent.meta_tools.bash._background_output_spill import (
        BackgroundOutputSpillWriter,
    )

logger = logging.getLogger(__name__)

_LINE_MAX_BYTES = 32 * 1024


@dataclass
class BackgroundRegistryEntry:
    """Internal registry record (carries the live process handle).

    Each buffered line is stored as ``(cursor, text)``. ``cursor`` is a
    process-wide monotonically increasing integer shared between stdout and
    stderr; this lets ``get_output(since_cursor=...)`` filter both streams
    against the same cursor without confusing rates (a busy stderr will not
    eat into stdout's quota or vice versa).
    """

    info: BackgroundProcessInfo
    proc: AsyncProcessProtocol
    stdout_buffer: deque[tuple[int, str]]
    stderr_buffer: deque[tuple[int, str]]
    reader_task: asyncio.Task[None] | None = None
    finish_listener: FinishListener | None = None
    progress_listener: ProgressListener | None = None
    spill_writer: BackgroundOutputSpillWriter | None = None
    cursor: int = 0
    empty_poll_streak: int = 0
    stdin_lock: asyncio.Lock | None = None


async def consume_background_entry(
    entry: BackgroundRegistryEntry,
    *,
    snapshot: Callable[[BackgroundRegistryEntry], BackgroundProcessInfo],
    schedule_reap: Callable[[int], None],
    clear_session_if_idle: Callable[[str | None], None],
) -> None:
    """Read stdout/stderr until the child exits; persist state and notify listeners."""
    from myrm_agent_harness.agent.meta_tools.bash._background_progress import (
        try_parse_progress_line,
    )

    async def _emit_progress(progress: dict[str, object]) -> None:
        entry.info.last_progress = {**progress, "updated_at": time.time()}
        listener = entry.progress_listener
        if listener is None:
            return
        try:
            await listener(entry.info, progress)
        except Exception as exc:  # pragma: no cover — best-effort
            logger.debug(
                "background progress listener for pid=%s failed: %s",
                entry.info.pid,
                exc,
            )

    async def _pipe(stream: object, sink: deque[tuple[int, str]]) -> None:
        reader = getattr(stream, "readline", None)
        if reader is None:
            return
        while True:
            try:
                chunk = await reader()
            except asyncio.LimitOverrunError as exc:
                drain_method = getattr(stream, "readexactly", None)
                if drain_method is not None:
                    with suppress(asyncio.IncompleteReadError, ConnectionError, OSError):
                        await drain_method(exc.consumed)
                entry.cursor += 1
                sink.append((entry.cursor, f"[output line >{exc.consumed} bytes truncated]"))
                continue
            except (ConnectionError, OSError, asyncio.CancelledError):
                return
            if not chunk:
                break
            raw = (chunk.decode("utf-8", errors="replace") if isinstance(chunk, bytes) else str(chunk)).rstrip()
            if len(raw) > _LINE_MAX_BYTES:
                text = raw[:_LINE_MAX_BYTES] + f"... [+{len(raw) - _LINE_MAX_BYTES} bytes truncated]"
            else:
                text = raw
            from myrm_agent_harness.agent.security.redact import redact_sensitive_text

            text = redact_sensitive_text(text)
            spill = entry.spill_writer
            if spill is not None:
                stream_name = "stderr" if sink is entry.stderr_buffer else "stdout"
                spill.append_line(stream_name, text)
                if spill.vault_log_ref and entry.info.vault_log_ref != spill.vault_log_ref:
                    entry.info.vault_log_ref = spill.vault_log_ref
                    from myrm_agent_harness.agent.meta_tools.bash._background_registry_store_sync import (
                        persist_vault_log_ref,
                    )

                    persist_vault_log_ref(entry.info)
            entry.cursor += 1
            sink.append((entry.cursor, text))
            progress = try_parse_progress_line(text)
            if progress is not None:
                await _emit_progress(progress)

    try:
        await asyncio.gather(
            _pipe(entry.proc.stdout, entry.stdout_buffer),
            _pipe(entry.proc.stderr, entry.stderr_buffer),
            return_exceptions=True,
        )
        exit_code = await entry.proc.wait()
        entry.info.exit_code = exit_code
        if entry.info.status == "running":
            entry.info.status = "exited"
        from myrm_agent_harness.agent.meta_tools.bash.bash_tool_background_listeners import (
            classify_background_exit,
        )

        entry.info.error_category = classify_background_exit(entry.info)
        from myrm_agent_harness.agent.meta_tools.bash._background_registry_store_sync import (
            persist_terminal_state,
        )

        persist_terminal_state(entry.info)
    except asyncio.CancelledError:
        return
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("background reader for pid=%s crashed: %s", entry.info.pid, exc)
    finally:
        listener = entry.finish_listener
        if listener is not None:
            try:
                await listener(snapshot(entry))
            except Exception as exc:  # pragma: no cover — best-effort
                logger.debug(
                    "background finish listener for pid=%s failed: %s",
                    entry.info.pid,
                    exc,
                )
        clear_session_if_idle(entry.info.session_id)
        schedule_reap(entry.info.pid)


__all__ = ["BackgroundRegistryEntry", "consume_background_entry"]
