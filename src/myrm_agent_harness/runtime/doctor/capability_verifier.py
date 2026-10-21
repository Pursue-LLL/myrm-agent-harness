"""Agent capability assertion consistency verifier.

Performs non-destructive dependency probes and dry-run verifications to validate
that declared tools (e.g. bash execution, file I/O, git operations) are genuinely
operable in the current execution environment, eliminating silent capability outages.

[OUTPUT]
- CapabilityAssertionVerifier: Automated tool readiness and assertion tester.

[INPUT]
- __future__
- asyncio
- shutil
- tempfile
- time
- collections

[OUTPUT]
- CapabilityAssertionVerifier

[POS]
Agent capability assertion consistency verifier.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import time
from collections.abc import Iterable
from pathlib import Path

from myrm_agent_harness.runtime.doctor.doctor_types import CapabilityAssertion


class CapabilityAssertionVerifier:
    """Verifies that declared agent tools and capabilities are genuinely functional."""

    def __init__(self, workspace_root: Path | str | None = None) -> None:
        self.workspace_root: Path = (
            Path(workspace_root).resolve() if workspace_root else Path.cwd()
        )

    async def verify_tool_capability(self, tool_name: str) -> CapabilityAssertion:
        """Run a lightweight, non-destructive probe to verify a single declared tool."""
        start_ts = time.perf_counter()
        normalized = tool_name.strip().lower()

        try:
            if "bash" in normalized or "shell" in normalized:
                verified, err = await self._probe_bash_capability()
            elif "git" in normalized:
                verified, err = self._probe_git_capability()
            elif "read" in normalized:
                verified, err = self._probe_read_capability()
            elif "write" in normalized or "edit" in normalized:
                verified, err = self._probe_write_capability()
            else:
                # Generic fallback check: assume verified if tool is loaded
                verified, err = True, None

            latency_ms = (time.perf_counter() - start_ts) * 1000.0
            return CapabilityAssertion(
                name=tool_name,
                kind="tool",
                declared=True,
                verified=verified,
                latency_ms=round(latency_ms, 2),
                error_detail=err,
            )

        except Exception as exc:
            latency_ms = (time.perf_counter() - start_ts) * 1000.0
            return CapabilityAssertion(
                name=tool_name,
                kind="tool",
                declared=True,
                verified=False,
                latency_ms=round(latency_ms, 2),
                error_detail=str(exc),
            )

    async def _probe_bash_capability(self) -> tuple[bool, str | None]:
        """Verify shell interpreter exists and can execute a benign echo command."""
        shell_bin = shutil.which("bash") or shutil.which("sh")
        if not shell_bin:
            return False, "Neither 'bash' nor 'sh' was found in system PATH."

        proc = await asyncio.create_subprocess_exec(
            shell_bin,
            "-c",
            "echo __probe_ok__",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0 and b"__probe_ok__" in stdout:
            return True, None
        return False, f"Shell probe failed (code {proc.returncode}): {stderr.decode()}"

    def _probe_git_capability(self) -> tuple[bool, str | None]:
        """Verify git executable is installed in PATH."""
        git_bin = shutil.which("git")
        if not git_bin:
            return False, "Git binary not found in system PATH."
        return True, None

    def _probe_read_capability(self) -> tuple[bool, str | None]:
        """Verify reading permissions in the workspace directory."""
        if not self.workspace_root.exists():
            return False, f"Workspace path does not exist: {self.workspace_root}"
        try:
            # Check directory listing
            list(self.workspace_root.iterdir())
            return True, None
        except Exception as exc:
            return False, f"Cannot read workspace directory: {exc}"

    def _probe_write_capability(self) -> tuple[bool, str | None]:
        """Verify writing permissions via a temporary file write and deletion."""
        try:
            with tempfile.NamedTemporaryFile(
                dir=self.workspace_root if self.workspace_root.is_dir() else None,
                prefix="__probe_",
                delete=True,
            ) as tmp:
                tmp.write(b"ok")
                tmp.flush()
            return True, None
        except Exception as exc:
            return False, f"Cannot write to workspace storage: {exc}"

    async def verify_all_declared(
        self,
        declared_tool_names: Iterable[str],
    ) -> tuple[CapabilityAssertion, ...]:
        """Verify an entire collection of declared tool capabilities concurrently."""
        tasks = [
            self.verify_tool_capability(name)
            for name in declared_tool_names
            if name.strip()
        ]
        if not tasks:
            return ()

        results = await asyncio.gather(*tasks)
        return tuple(results)
