"""Subprocess-based test execution for skill evolution TDE.

[INPUT]
- toolkits.code_execution.utils.workspace_path::WorkspacePathResolver (POS: Workspace path resolver with intelligent auto-detection.)
- toolkits.code_execution.security.audit_sandbox::install (POS: Install PEP 578 audit hook)

[OUTPUT]
- TestExecutionResult: Result of running a generated evolution test.
- SubprocessCodeExecutor: Run generated evolution tests in an isolated subprocess.

[POS]
Subprocess-based test execution for skill evolution TDE.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["SubprocessCodeExecutor", "TestExecutionResult"]


@dataclass(slots=True)
class TestExecutionResult:
    """Result of running a generated evolution test."""

    __test__ = False

    passed: bool
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool
    duration_seconds: float


class SubprocessCodeExecutor:
    """Run generated evolution tests in an isolated subprocess."""

    def __init__(
        self,
        timeout_seconds: float = 10.0,
        memory_limit_mb: int = 512,
        allow_network: bool = True,
    ) -> None:
        self._timeout_seconds = max(1.0, timeout_seconds)
        self._memory_limit_bytes = max(64, memory_limit_mb) * 1024 * 1024
        self._allow_network = allow_network

    async def run_tests(
        self,
        skill_content: str,
        test_code: str,
        skill_name: str,
        skill_dir: Path | None = None,
        old_skill_content: str | None = None,
    ) -> TestExecutionResult:
        """Run generated tests against a candidate skill.

        If old_skill_content is provided, enforces Red-Green testing:
        The test MUST fail on the old code (Red) and pass on the new code (Green).
        This mathematically proves the test actually targets the bug/feature.
        """
        return await asyncio.to_thread(
            self._run_tests_sync,
            skill_content,
            test_code,
            skill_name,
            skill_dir,
            old_skill_content,
        )

    def _run_tests_sync(
        self,
        skill_content: str,
        test_code: str,
        skill_name: str,
        skill_dir: Path | None = None,
        old_skill_content: str | None = None,
    ) -> TestExecutionResult:
        """Run tests in a temporary workspace."""
        with tempfile.TemporaryDirectory(prefix="myrm_evolution_") as temp_dir:
            workspace = Path(temp_dir)
            skill_path = workspace / "skill_under_test.md"
            test_path = workspace / "test_generated_evolution.py"

            skill_path.write_text(skill_content, encoding="utf-8")
            test_path.write_text(test_code, encoding="utf-8")

            # Copy existing regression tests if available
            if skill_dir and skill_dir.exists() and skill_dir.is_dir():
                import shutil

                for item in skill_dir.iterdir():
                    if item.is_file() and (
                        item.name.startswith("test_") or item.name.endswith("_test.py")
                    ):
                        try:
                            shutil.copy2(item, workspace / item.name)
                            logger.debug(
                                "Copied regression test %s to TDE workspace", item.name
                            )
                        except Exception as e:
                            logger.warning(
                                "Failed to copy regression test %s: %s", item.name, e
                            )

            env = os.environ.copy()
            env["EVOLUTION_SKILL_PATH"] = str(skill_path)
            env["EVOLUTION_SKILL_NAME"] = skill_name
            env["PYTHONUNBUFFERED"] = "1"
            env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"

            # Map TMPDIR inside the workspace so audit hook allows pytest cache/temp writes
            workspace_tmp = workspace / ".tmp"
            workspace_tmp.mkdir(exist_ok=True)
            env["TMPDIR"] = str(workspace_tmp)

            from myrm_agent_harness.toolkits.code_execution.utils.workspace_path import (
                WorkspacePathResolver,
            )

            parent_pythonpath = str(WorkspacePathResolver.resolve_workspace_root())
            existing_pythonpath = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = os.pathsep.join(
                part for part in (parent_pythonpath, existing_pythonpath) if part
            )

            # Build the pytest command wrapped with PEP 578 audit sandbox
            pytest_cmd_args = [
                "-c",
                "import os; import sys; "
                "from myrm_agent_harness.toolkits.code_execution.security import audit_sandbox; "
                f"audit_sandbox.install(os.getcwd(), allow_network={self._allow_network}); "
                "import pytest; "
                "sys.exit(pytest.main(['-q', '.']))",
            ]

            from myrm_agent_harness.toolkits.code_execution.sandbox import detect_sandbox_provider
            from myrm_agent_harness.toolkits.code_execution.sandbox.sandbox_types import SandboxPolicy

            provider, sandbox_status = detect_sandbox_provider()
            if sandbox_status.enabled:
                policy = SandboxPolicy(
                    writable_paths=(str(workspace),),
                    allow_network=self._allow_network,
                )
                wrapped_cmd, wrapped_args = provider.wrap_command(
                    sys.executable, tuple(pytest_cmd_args), str(workspace), policy,
                )
                pytest_cmd = [wrapped_cmd, *wrapped_args]
            else:
                pytest_cmd = [sys.executable, *pytest_cmd_args]

            # Red-Green Testing: First test against old code (must fail)
            if old_skill_content:
                skill_path.write_text(old_skill_content, encoding="utf-8")
                try:
                    old_completed = subprocess.run(
                        pytest_cmd,
                        cwd=workspace,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=self._timeout_seconds,
                        process_group=0,
                        preexec_fn=self._build_resource_limiter(),
                        check=False,
                    )
                    if old_completed.returncode == 0:
                        # Test passed on old code! The test is invalid (does not target the bug).
                        logger.warning(
                            "TDE Red-Green violation: Generated test passed on old code for '%s'",
                            skill_name,
                        )
                        return TestExecutionResult(
                            passed=False,
                            stdout=old_completed.stdout,
                            stderr="[Red-Green Violation] The generated test passed on the OLD code. This means the test is trivial or invalid and does not actually reproduce the bug or test the new feature.",
                            returncode=1,
                            timed_out=False,
                            duration_seconds=0.0,
                        )
                except subprocess.TimeoutExpired:
                    # Timeout on old code is technically a failure (Red), so we can proceed
                    pass
                except Exception:
                    # Other exceptions on old code, proceed
                    pass

                # Restore new code for the Green phase
                skill_path.write_text(skill_content, encoding="utf-8")

            start_time = time.perf_counter()
            try:
                # Run pytest on the entire workspace to include both generated and regression tests
                completed = subprocess.run(
                    pytest_cmd,
                    cwd=workspace,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout_seconds,
                    process_group=0,
                    preexec_fn=self._build_resource_limiter(),
                    check=False,
                )
                duration_seconds = time.perf_counter() - start_time
                return TestExecutionResult(
                    passed=completed.returncode == 0,
                    stdout=completed.stdout,
                    stderr=completed.stderr,
                    returncode=completed.returncode,
                    timed_out=False,
                    duration_seconds=duration_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                duration_seconds = time.perf_counter() - start_time
                stdout = exc.stdout if isinstance(exc.stdout, str) else ""
                stderr = exc.stderr if isinstance(exc.stderr, str) else ""
                logger.warning(
                    "Evolution test timed out after %.1fs for skill '%s'",
                    self._timeout_seconds,
                    skill_name,
                )
                return TestExecutionResult(
                    passed=False,
                    stdout=stdout,
                    stderr=(stderr + "\n[Timed out]").strip(),
                    returncode=124,
                    timed_out=True,
                    duration_seconds=duration_seconds,
                )

    def _build_resource_limiter(self) -> Callable[[], None] | None:
        """Build a best-effort resource limiter for the subprocess."""
        try:
            import resource
        except (ImportError, TypeError):
            return None

        cpu_limit = max(1, int(self._timeout_seconds) + 1)
        memory_limit = self._memory_limit_bytes

        def _limit() -> None:
            with contextlib.suppress(ValueError, OSError):
                resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit, cpu_limit))

            with contextlib.suppress(AttributeError, ValueError, OSError):
                resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))

            with contextlib.suppress(AttributeError, ValueError, OSError):
                resource.setrlimit(resource.RLIMIT_FSIZE, (100 * 1024 * 1024, 100 * 1024 * 1024))

            with contextlib.suppress(AttributeError, ValueError, OSError):
                resource.setrlimit(resource.RLIMIT_NOFILE, (1024, 1024))

        return _limit
