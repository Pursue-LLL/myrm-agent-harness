"""Native file operations mixin for LocalExecutor.

[INPUT]
infra.atomic_write::async_atomic_write (POS: Atomic file writing utility)

[OUTPUT]
LocalFileOpsMixin: Mixin providing pathlib-based file I/O with read-only guard.

[POS]
Native file operations for local executor. Provides zero-subprocess-overhead
file read/write/delete/grep using pathlib and ripgrep, with read-only path enforcement.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Protocol, runtime_checkable

from myrm_agent_harness.infra.atomic_write import async_atomic_write

logger = logging.getLogger(__name__)


from myrm_agent_harness.toolkits.code_execution.interceptor import trigger_destructive_action_hook


@runtime_checkable
class _ExecutorProtocol(Protocol):
    """Minimal interface required from the host executor."""

    _readonly_paths: list[str]
    _current_workspace: Path | None

    async def resolve_path(self, path: str) -> str: ...
    def _log_context_file_access(self, path: str, success: bool) -> None: ...
    async def _exec_bash(self, command: str) -> object: ...
    @property
    def workspace_path(self) -> str: ...


class LocalFileOpsMixin:
    """Mixin providing local file operations via pathlib (zero subprocess overhead).

    Requires the host class to provide: ``resolve_path``, ``_guard_write``,
    ``_log_context_file_access``, ``_exec_bash``, and ``workspace_path``.
    """

    def _is_readonly(self, resolved_path: str) -> bool:
        rp = Path(resolved_path).resolve()
        return any(
            rp == Path(p).resolve() or rp.is_relative_to(Path(p).resolve())
            for p in self._readonly_paths  # type: ignore[attr-defined]
        )

    def _guard_write(self, resolved_path: str) -> None:
        if self._is_readonly(resolved_path):
            raise PermissionError(f"Write denied: path is read-only — {resolved_path}")

    async def read_file(self, path: str) -> str:
        safe = await self.resolve_path(path)  # type: ignore[attr-defined]
        self._log_context_file_access(safe, success=True)  # type: ignore[attr-defined]
        p = Path(safe)
        if not p.exists():
            self._log_context_file_access(safe, success=False)  # type: ignore[attr-defined]
            raise FileNotFoundError(f"File not found: {path}")

        if safe.endswith(".gz"):
            import gzip

            return gzip.decompress(p.read_bytes()).decode("utf-8")

        return p.read_text(encoding="utf-8")

    async def read_file_bytes(self, path: str) -> bytes:
        safe = await self.resolve_path(path)  # type: ignore[attr-defined]
        p = Path(safe)
        if not p.exists():
            raise FileNotFoundError(f"File not found: {path}")
        return p.read_bytes()

    async def write_file(self, path: str, content: str) -> None:
        safe = await self.resolve_path(path)  # type: ignore[attr-defined]
        self._guard_write(safe)

        # Trigger auto-snapshot hook
        await trigger_destructive_action_hook(
            workspace_path=self.workspace_path,  # type: ignore[attr-defined]
            action_type="file_write",
            payload={"path": safe, "size": len(content)},
        )

        p = Path(safe)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    async def write_file_bytes(self, path: str, content: bytes) -> None:
        safe = await self.resolve_path(path)  # type: ignore[attr-defined]
        self._guard_write(safe)

        await trigger_destructive_action_hook(
            workspace_path=self.workspace_path,  # type: ignore[attr-defined]
            action_type="file_write",
            payload={"path": safe, "size": len(content)},
        )

        p = Path(safe)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)

    async def write_file_atomic(self, path: str, content: str) -> None:
        safe = await self.resolve_path(path)  # type: ignore[attr-defined]
        self._guard_write(safe)

        await trigger_destructive_action_hook(
            workspace_path=self.workspace_path,  # type: ignore[attr-defined]
            action_type="file_write",
            payload={"path": safe, "size": len(content)},
        )

        await async_atomic_write(safe, content)

    async def write_file_bytes_atomic(self, path: str, content: bytes) -> None:
        safe = await self.resolve_path(path)  # type: ignore[attr-defined]
        self._guard_write(safe)

        await trigger_destructive_action_hook(
            workspace_path=self.workspace_path,  # type: ignore[attr-defined]
            action_type="file_write",
            payload={"path": safe, "size": len(content)},
        )

        await async_atomic_write(safe, content)

    async def append_file(self, path: str, content: str) -> None:
        safe = await self.resolve_path(path)  # type: ignore[attr-defined]
        self._guard_write(safe)

        await trigger_destructive_action_hook(
            workspace_path=self.workspace_path,  # type: ignore[attr-defined]
            action_type="file_append",
            payload={"path": safe, "size": len(content)},
        )

        with open(safe, "a", encoding="utf-8") as f:
            f.write(content)

    async def delete_file(self, path: str) -> None:
        safe = await self.resolve_path(path)  # type: ignore[attr-defined]
        self._guard_write(safe)

        await trigger_destructive_action_hook(
            workspace_path=self.workspace_path,  # type: ignore[attr-defined]
            action_type="file_delete",
            payload={"path": safe},
        )

        Path(safe).unlink(missing_ok=True)

    async def file_exists(self, path: str) -> bool:
        safe = await self.resolve_path(path)  # type: ignore[attr-defined]
        return Path(safe).exists()

    async def is_file(self, path: str) -> bool:
        safe = await self.resolve_path(path)  # type: ignore[attr-defined]
        return Path(safe).is_file()

    async def is_dir(self, path: str) -> bool:
        safe = await self.resolve_path(path)  # type: ignore[attr-defined]
        return Path(safe).is_dir()

    async def mkdir(self, path: str) -> None:
        safe = await self.resolve_path(path)  # type: ignore[attr-defined]
        Path(safe).mkdir(parents=True, exist_ok=True)

    async def list_files(self, path: str = ".", pattern: str = "*") -> list[str]:
        safe = await self.resolve_path(path)  # type: ignore[attr-defined]
        return [str(f) for f in Path(safe).glob(pattern) if f.is_file()]

    async def grep(
        self,
        pattern: str,
        path: str = ".",
        use_regex: bool = False,
        case_sensitive: bool = True,
    ) -> str:
        """Search files using ripgrep (preferred) or grep (fallback).

        Args:
            pattern: Search pattern.
            path: Search path relative to workspace.
            use_regex: Use regex matching (default: False, literal match).
            case_sensitive: Case-sensitive matching (default: True).

        Returns:
            Search results in ``file:line:content`` format.
        """
        start = time.time()
        safe = await self.resolve_path(path)  # type: ignore[attr-defined]

        if not hasattr(self, "_has_ripgrep"):
            check_rg = await self._exec_bash("which rg 2>/dev/null")  # type: ignore[attr-defined]
            self._has_ripgrep = bool(check_rg.success and check_rg.stdout.strip())

        tool = "ripgrep" if self._has_ripgrep else "grep"

        if self._has_ripgrep:
            flags = ["--line-number"]
            if not use_regex:
                flags.append("--fixed-strings")
            if not case_sensitive:
                flags.append("--ignore-case")

            flags_str = " ".join(flags)
            result = await self._exec_bash(  # type: ignore[attr-defined]
                f"rg {flags_str} '{pattern}' '{safe}' 2>/dev/null || true"
            )
        else:
            flags = ["-rn"]
            if not use_regex:
                flags.append("F")
            if not case_sensitive:
                flags.append("i")

            flags_str = "-" + "".join(flags)
            result = await self._exec_bash(  # type: ignore[attr-defined]
                f"grep {flags_str} '{pattern}' '{safe}' || true"
            )

        elapsed = time.time() - start
        stdout: str = str(result.stdout)
        match_count = len(stdout.splitlines()) if stdout else 0
        logger.debug(
            f"grep: tool={tool}, regex={use_regex}, case_sensitive={case_sensitive}, "
            f"elapsed={elapsed:.4f}s, pattern_len={len(pattern)}, matches={match_count}"
        )

        return stdout

    async def glob_files(self, pattern: str) -> list[str]:
        wp = Path(self.workspace_path)  # type: ignore[attr-defined]
        return [str(f) for f in wp.glob(pattern) if f.is_file()]
