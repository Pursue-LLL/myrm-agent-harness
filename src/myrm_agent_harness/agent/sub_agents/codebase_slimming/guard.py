"""Behavior invariance assertion and regression guard for slimming refactors.

[INPUT]
- .types::EquivalenceVerdict (POS: Verdict data structures)

[OUTPUT]
- EquivalenceInvarianceGuard: Executes regression test suites and asserts behavior consistency.

[POS]
Safety barrier enforcing that refactored code passes all deterministic tests before merge.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from myrm_agent_harness.agent.sub_agents.codebase_slimming.types import EquivalenceVerdict


class EquivalenceInvarianceGuard:
    """Executes deterministic test commands against a workspace and asserts behavior invariance."""

    @classmethod
    async def assert_invariance(
        cls,
        workspace_dir: Path | str,
        test_command: str = "pytest",
        timeout_seconds: float = 30.0,
    ) -> EquivalenceVerdict:
        cwd = Path(workspace_dir).resolve()
        if not cwd.exists():
            return EquivalenceVerdict(
                passed=False,
                test_command=test_command,
                exit_code=-1,
                output_summary="",
                failure_reason=f"Workspace directory {cwd} does not exist",
            )

        try:
            proc = await asyncio.create_subprocess_shell(
                test_command,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_data, stderr_data = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_seconds
            )
            out_str = stdout_data.decode("utf-8", errors="ignore")
            err_str = stderr_data.decode("utf-8", errors="ignore")
            combined_summary = (out_str + "\n" + err_str).strip()[:1000]

            if proc.returncode == 0:
                return EquivalenceVerdict(
                    passed=True,
                    test_command=test_command,
                    exit_code=0,
                    output_summary=combined_summary,
                )
            else:
                return EquivalenceVerdict(
                    passed=False,
                    test_command=test_command,
                    exit_code=proc.returncode or 1,
                    output_summary=combined_summary,
                    failure_reason=f"Tests failed with exit code {proc.returncode}",
                )
        except asyncio.TimeoutError:
            return EquivalenceVerdict(
                passed=False,
                test_command=test_command,
                exit_code=124,
                output_summary="",
                failure_reason=f"Test command timed out after {timeout_seconds}s",
            )
        except Exception as exc:
            return EquivalenceVerdict(
                passed=False,
                test_command=test_command,
                exit_code=-1,
                output_summary="",
                failure_reason=f"Execution error: {exc}",
            )
