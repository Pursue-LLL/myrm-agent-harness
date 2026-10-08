"""Executable Probe Runner with Shell-free spawning and tri-state classification.

[INPUT]
- Candidate executable paths, required capability flags, optional arguments.

[OUTPUT]
- ExecutableProbeResult with tri-state status (capable / incompatible / broken).

[POS]
- Harness core security engine for Claude-Mem #4167 shell-immune executable probing and tri-state classification.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence

from .types import (
    ExecutableProbeResult,
    ExecutableProbeStatus,
    ProbeOptions,
)


class ExecutableProbeRunner:
    """Probes executable binaries without shell interpretation, classifying capability into tri-state results."""

    def __init__(self, default_options: ProbeOptions | None = None) -> None:
        self._options = default_options or ProbeOptions()

    def _execute_direct(
        self,
        candidate: str,
        args: Sequence[str],
        timeout_sec: float,
    ) -> tuple[int | None, str, str, bool]:
        """Execute candidate directly via argv list without shell. Returns (returncode, stdout, stderr, launch_failed)."""
        cmd = [candidate, *args]
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                shell=False,  # Shell-immune: NEVER pass string to shell
                timeout=timeout_sec,
                check=False,
            )
            return res.returncode, res.stdout.strip(), res.stderr.strip(), False
        except (FileNotFoundError, PermissionError, OSError) as exc:
            return None, "", str(exc), True
        except subprocess.TimeoutExpired as exc:
            return None, "", f"Execution timed out after {timeout_sec}s: {exc}", False

    def probe_executable(
        self,
        candidate: str,
        capability_flags: Sequence[str] = ("--version",),
        version_flag: str = "--version",
        options: ProbeOptions | None = None,
    ) -> ExecutableProbeResult:
        """Probe an executable candidate, distinguishing capable, incompatible, and broken states."""
        opts = options or self._options
        if not candidate or not candidate.strip():
            return ExecutableProbeResult(
                candidate_path=candidate,
                status=ExecutableProbeStatus.BROKEN,
                detail="Empty candidate path provided",
                launch_failed=True,
                is_capable=False,
            )

        trimmed_candidate = candidate.strip()

        # Step 1: Probe full capability flags directly
        ret_code, stdout, stderr, launch_failed = self._execute_direct(
            trimmed_candidate, capability_flags, opts.timeout_sec
        )

        if launch_failed:
            return ExecutableProbeResult(
                candidate_path=trimmed_candidate,
                status=ExecutableProbeStatus.BROKEN,
                detail=f"OS failed to launch binary: {stderr}",
                launch_failed=True,
                is_capable=False,
            )

        if ret_code == 0 and (stdout or stderr):
            version_str = (stdout or stderr).splitlines()[0].strip()
            return ExecutableProbeResult(
                candidate_path=trimmed_candidate,
                status=ExecutableProbeStatus.CAPABLE,
                version=version_str,
                detail="Binary executed and accepted capability flags",
                launch_failed=False,
                is_capable=True,
            )

        # Step 2: Capability probe failed. Run plain version flag to distinguish
        # "runs but rejects capability flags" (incompatible) from "fails plain run" (broken).
        v_code, v_out, v_err, v_launch_failed = self._execute_direct(
            trimmed_candidate, [version_flag], opts.timeout_sec
        )

        if v_launch_failed or v_code != 0:
            return ExecutableProbeResult(
                candidate_path=trimmed_candidate,
                status=ExecutableProbeStatus.BROKEN,
                detail=f"Binary failed plain version probe: {v_err or stderr or 'non-zero exit'}",
                launch_failed=v_launch_failed,
                is_capable=False,
            )

        # Plain version probe succeeded!
        version_str = (
            (v_out or v_err).splitlines()[0].strip() if (v_out or v_err) else "unknown"
        )

        # Step 3: Warm-up retry if enabled (in case cold-start timed out or glitched on first attempt)
        if opts.warm_up_retry:
            ret2, out2, err2, _ = self._execute_direct(
                trimmed_candidate, capability_flags, opts.timeout_sec
            )
            if ret2 == 0 and (out2 or err2):
                v_recovered = (out2 or err2).splitlines()[0].strip()
                return ExecutableProbeResult(
                    candidate_path=trimmed_candidate,
                    status=ExecutableProbeStatus.CAPABLE,
                    version=v_recovered,
                    detail="Binary accepted capability flags after warm-up retry",
                    launch_failed=False,
                    is_capable=True,
                )

        # Reached here: runs plain version, but genuinely rejects capability flags
        return ExecutableProbeResult(
            candidate_path=trimmed_candidate,
            status=ExecutableProbeStatus.INCOMPATIBLE,
            version=version_str,
            detail=f"Binary rejected capability flags: {stderr or 'exit code ' + str(ret_code)}",
            launch_failed=False,
            is_capable=False,
        )
