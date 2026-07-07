"""Abstract persistent shell session with auto-recovery.

[INPUT]
session.shell_flavor::ShellFlavor (POS: Platform-specific shell command formatting)
session.stream_output_processor::StreamOutputProcessor (POS: Unified tee/SSE output handling)
session.stream_buffer::ExecutionStreamBuffer (POS: Zero-copy byte stream parsing)
executors.models::scrub_sensitive_info (POS: PII scrubbing for output streams)

[OUTPUT]
PersistentSession: Abstract base for stateful persistent shell sessions.
SessionConfig: Configuration dataclass for session parameters.
SessionExecutionResult: Frozen dataclass for command execution results.
SessionState: Lifecycle states enum.

[POS]
Abstract persistent shell session base. Manages subprocess lifecycle, state machine,
execute/stream with auto-tee, auto-recovery, and SSE flood protection.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import os
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.code_execution.platform import (
    PlatformInfo,
    detect_platform,
)
from myrm_agent_harness.toolkits.code_execution.session.shell_flavor import (
    get_flavor,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class SessionState(Enum):
    """Lifecycle states of a persistent session."""

    IDLE = auto()
    STARTING = auto()
    ACTIVE = auto()
    RECOVERING = auto()
    CLOSING = auto()
    TERMINATED = auto()


@dataclass(frozen=True)
class SessionExecutionResult:
    """Result of a command execution in a persistent session."""

    success: bool
    stdout: str
    stderr: str
    exit_code: int
    error: str | None = None
    duration: float = 0.0


@dataclass
class SessionConfig:
    """Configuration for a persistent session."""

    session_id: str
    work_dir: str
    timeout: int = 60
    env: dict[str, str] = field(default_factory=dict)
    sandbox_mode: str = "auto"
    max_memory_mb: int = 2048


def _generate_marker(prefix: str) -> str:
    return f"__MYRM_{prefix}__"


async def _kill_process_tree(
    process: asyncio.subprocess.Process,
    is_windows: bool,
    grace_period: float = 2.0,
) -> None:
    """Kill a process and its entire process group."""
    pid = process.pid
    if pid is None:
        return

    if is_windows:
        try:
            p = await asyncio.create_subprocess_exec(
                "taskkill",
                "/F",
                "/T",
                "/PID",
                str(pid),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await p.wait()
        except Exception:
            process.kill()
        return

    import signal

    try:
        pgid = os.getpgid(pid)
        if pgid == os.getpgid(os.getpid()):
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=grace_period)
            except TimeoutError:
                process.kill()
        else:
            os.killpg(pgid, signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), timeout=grace_period)
            except TimeoutError:
                os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, OSError):
        pass


class PersistentSession(ABC):
    """Abstract base class for persistent shell sessions."""

    _SESSION_DIED_SENTINEL = "Session process ended unexpectedly"

    def __init__(self, config: SessionConfig, platform_info: PlatformInfo | None = None):
        self.config = config
        self._platform = platform_info or detect_platform()
        self._flavor = get_flavor(self._platform)

        self.process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._state = SessionState.IDLE
        self._state_changed = asyncio.Event()

        self._consecutive_failures = 0
        self._last_returncode: int | None = None

    @property
    def state(self) -> SessionState:
        return self._state

    @property
    def is_alive(self) -> bool:
        return self.process is not None and self.process.returncode is None

    async def _transit_state(self, new_state: SessionState) -> None:
        """Atomic state transition with logging."""
        old_state = self._state
        if old_state == new_state:
            return
        self._state = new_state
        self._state_changed.set()
        self._state_changed.clear()
        logger.debug(f" Session {self.config.session_id} state: {old_state.name} -> {new_state.name}")

    async def _ensure_active(self) -> None:
        """Ensure the session is active, waiting for it if it's currently starting/recovering."""
        while True:
            if self._state == SessionState.ACTIVE and self.is_alive:
                return

            if self._state in (
                SessionState.IDLE,
                SessionState.TERMINATED,
                SessionState.CLOSING,
            ) or (self._state == SessionState.ACTIVE and not self.is_alive):
                await self.start()
                return

            if self._state in (SessionState.STARTING, SessionState.RECOVERING):
                await self._state_changed.wait()
                continue

            if self._state == SessionState.CLOSING:
                await self._state_changed.wait()
                continue

    async def start(self) -> None:
        """Locking entry point for starting the session."""
        if self.is_alive and self._state == SessionState.ACTIVE:
            return

        async with self._lock:
            await self._start_unlocked()

    async def _start_unlocked(self) -> None:
        """Core start logic without lock."""
        if self.is_alive and self._state == SessionState.ACTIVE:
            return

        await self._transit_state(SessionState.STARTING)
        try:
            logger.info(f" Starting persistent session: {self.config.session_id}")
            self.process = await self._create_process()
            await self._initialize_shell()
            self._consecutive_failures = 0
            await self._transit_state(SessionState.ACTIVE)
            logger.info(f" Persistent session started: {self.config.session_id}")
        except Exception as e:
            await self._transit_state(SessionState.TERMINATED)
            logger.error(f" Failed to start session: {e}")
            raise

    @abstractmethod
    async def _create_process(self) -> asyncio.subprocess.Process: ...

    async def _initialize_shell(self) -> None:
        init_commands = self._flavor.build_init_commands(
            self.config.work_dir,
            timeout=self.config.timeout,
            max_memory_mb=self.config.max_memory_mb,
        )
        for key, value in self.config.env.items():
            init_commands.append(self._flavor.format_env_set(key, value))

        if not self.process or not self.process.stdin:
            return

        batch = "\n".join(init_commands) + "\n"
        self.process.stdin.write(batch.encode())
        await self.process.stdin.drain()
        await asyncio.sleep(0.15)

    async def execute(self, command: str, timeout: int | None = None) -> SessionExecutionResult:
        """Execute a command with auto-recovery."""
        timeout = timeout or self.config.timeout
        start_time = time.perf_counter()

        await self._ensure_active_unlocked()
        result = await self._execute_core(command, timeout)

        # Auto-recovery logic
        if self._should_recover(result):
            result = await self._recover_and_retry(command, timeout)

        return dataclasses.replace(result, duration=time.perf_counter() - start_time)

    async def _ensure_active_unlocked(self) -> None:
        """Unlocked version of ensure_active."""
        while True:
            if self._state == SessionState.ACTIVE and self.is_alive:
                return
            if self._state in (
                SessionState.IDLE,
                SessionState.TERMINATED,
                SessionState.CLOSING,
            ) or (self._state == SessionState.ACTIVE and not self.is_alive):
                await self._start_unlocked()
                return
            if self._state in (SessionState.STARTING, SessionState.RECOVERING):
                return

    def _should_recover(self, result: SessionExecutionResult) -> bool:
        return (
            result.error is not None and self._SESSION_DIED_SENTINEL in result.error and self._consecutive_failures <= 1
        )

    async def _recover_and_retry(self, command: str, timeout: int) -> SessionExecutionResult:
        await self._transit_state(SessionState.RECOVERING)
        logger.warning(f" Recovering session {self.config.session_id} after crash...")
        try:
            await self._kill_process_group()
            self.process = await self._create_process()
            await self._initialize_shell()
            self._consecutive_failures = 0
            await self._transit_state(SessionState.ACTIVE)
            return await self._execute_core(command, timeout)
        except Exception as e:
            await self._transit_state(SessionState.TERMINATED)
            return SessionExecutionResult(False, "", "", 1, error=f"Recovery failed: {e}")

    async def _execute_core(self, command: str, timeout: int) -> SessionExecutionResult:
        if not self.process or not self.process.stdin or not self.process.stdout:
            return SessionExecutionResult(False, "", "", 1, error="Process unavailable")

        end_marker = _generate_marker("END")
        exit_marker = _generate_marker("EXIT")
        full_cmd = self._flavor.build_wrapped_command(command, exit_marker, end_marker, self._platform.exit_code_var)

        try:
            self.process.stdin.write(full_cmd.encode())
            await self.process.stdin.drain()
        except Exception as e:
            self._consecutive_failures += 1
            return SessionExecutionResult(False, "", str(e), 1, error=f"IPC write failure: {e}")

        import aiofiles

        from myrm_agent_harness.toolkits.code_execution.executors.models import (
            scrub_sensitive_info,
        )
        from myrm_agent_harness.toolkits.code_execution.session.stream_buffer import (
            ExecutionStreamBuffer,
        )
        from myrm_agent_harness.toolkits.code_execution.session.stream_output_processor import (
            StreamOutputProcessor,
        )
        from myrm_agent_harness.utils.event_utils import dispatch_custom_event

        stream_buf = ExecutionStreamBuffer()
        sop = StreamOutputProcessor()
        tee_file_path = sop.setup_tee(self.config.work_dir)

        try:
            async with aiofiles.open(tee_file_path, "w", encoding="utf-8") as tee_file:
                async with asyncio.timeout(timeout):
                    while not stream_buf.done:
                        chunk = await self.process.stdout.read(8192)
                        if not chunk:
                            rc = self.process.returncode
                            self._last_returncode = rc
                            self._consecutive_failures += 1
                            err = f"{self._SESSION_DIED_SENTINEL} (rc={rc})"
                            return SessionExecutionResult(
                                False,
                                stream_buf.get_final_output(),
                                err,
                                rc if rc is not None else 1,
                                error=err,
                            )

                        safe_text = stream_buf.process_bytes(chunk, exit_marker, end_marker)
                        if safe_text:
                            await sop.write_tee(tee_file, safe_text)
                            scrubbed_text = scrub_sensitive_info(safe_text)
                            sse_emit = sop.accumulate_sse(scrubbed_text)
                            if sse_emit:
                                with contextlib.suppress(RuntimeError):
                                    await dispatch_custom_event("tool_stdout_chunk", {"chunk": sse_emit})

                    remaining = sop.flush()
                    if remaining:
                        from contextlib import suppress

                        with suppress(RuntimeError):
                            await dispatch_custom_event("tool_stdout_chunk", {"chunk": remaining})
        except TimeoutError:
            self._consecutive_failures += 1
            return SessionExecutionResult(
                False,
                stream_buf.get_final_output(),
                f"Timeout after {timeout}s",
                124,
                error="Timeout",
            )

        stdout = stream_buf.get_final_output().rstrip("\n")
        exit_code = stream_buf.exit_code

        if getattr(stream_buf, "_is_truncated", False) or sop.tee_truncated:
            stdout += sop.build_truncation_system_note()

        if exit_code == 0:
            success = True
        else:
            from myrm_agent_harness.toolkits.code_execution.executors.common.exit_classify import (
                classify_exit_code,
            )

            success = classify_exit_code(command, exit_code, stdout)

        return SessionExecutionResult(success, stdout, "", exit_code)

    async def execute_stream(self, command: str, timeout: int | None = None) -> AsyncIterator[str]:
        """Yield performance-optimized output stream."""
        timeout = timeout or self.config.timeout
        await self._ensure_active()

        async with self._lock:
            end_marker = _generate_marker("END")
            exit_marker = _generate_marker("EXIT")
            full_cmd = self._flavor.build_wrapped_command(
                command, exit_marker, end_marker, self._platform.exit_code_var
            )

            self.process.stdin.write(full_cmd.encode())
            await self.process.stdin.drain()

            import aiofiles

            from myrm_agent_harness.toolkits.code_execution.session.stream_buffer import (
                ExecutionStreamBuffer,
            )
            from myrm_agent_harness.toolkits.code_execution.session.stream_output_processor import (
                StreamOutputProcessor,
            )

            stream_buf = ExecutionStreamBuffer()
            sop = StreamOutputProcessor()
            tee_file_path = sop.setup_tee(self.config.work_dir)

            try:
                async with aiofiles.open(tee_file_path, "w", encoding="utf-8") as tee_file:
                    async with asyncio.timeout(timeout):
                        while not stream_buf.done:
                            chunk = await self.process.stdout.read(4096)
                            if not chunk:
                                yield f"\n[ERROR] {self._SESSION_DIED_SENTINEL}\n"
                                return
                            safe_text = stream_buf.process_bytes(chunk, exit_marker, end_marker)
                            if safe_text:
                                await sop.write_tee(tee_file, safe_text)
                                sse_emit = sop.accumulate_sse(safe_text)
                                if sse_emit:
                                    yield sse_emit

                        remaining = sop.flush()
                        if remaining:
                            yield remaining
            except TimeoutError:
                yield f"\n[ERROR] Timeout After {timeout}s\n"

    async def _kill_process_group(self, grace_period: float = 2.0) -> None:
        if not self.process or self.process.pid is None:
            return
        try:
            await asyncio.shield(
                _kill_process_tree(self.process, self._platform.is_windows, grace_period)
            )
        except asyncio.CancelledError:
            pass

    async def close(self) -> None:
        async with self._lock:
            await self._close_unlocked()

    async def _close_unlocked(self) -> None:
        if self._state == SessionState.CLOSING:
            return
        await self._transit_state(SessionState.CLOSING)
        try:
            await self._kill_process_group()
        finally:
            self.process = None
            await self._transit_state(SessionState.TERMINATED)

    async def check_health(self) -> bool:
        if not self.is_alive:
            return False
        try:
            res = await self.execute("echo ok", timeout=2)
            return res.success and "ok" in res.stdout
        except Exception:
            return False
