"""Super-CLI Controlled Wrapper for Legacy CLI Tools with Memory-Only Credential Injection."""

from __future__ import annotations

import logging
import os
import subprocess

from .redaction_gate import RedactionSanitizationGate
from .types import SuperCliCommandSpec, SuperCliExecutionResult

logger = logging.getLogger(__name__)


class SuperCliWrapper:
    """Controlled wrapper executing legacy CLI tools with memory-only token injection and stream redaction.

    Guarantees:
    1. Credentials injected purely into subprocess transient memory, never written to disk or container fs.
    2. Process stdout and stderr streams pass through the RedactionSanitizationGate.
    3. Transparency notices are appended if secrets are detected and redacted.
    """

    def __init__(
        self,
        redaction_gate: RedactionSanitizationGate | None = None,
    ) -> None:
        self.redaction_gate = redaction_gate or RedactionSanitizationGate()

    def execute_command(self, spec: SuperCliCommandSpec) -> SuperCliExecutionResult:
        """Execute a target CLI command with transient environment variables and redacted output streams."""
        # Build ephemeral execution environment
        ephemeral_env = dict(os.environ)
        ephemeral_env.update(spec.injected_env)

        full_cmd = [spec.target_cli, *spec.args]

        try:
            # Subprocess execution in transient memory
            proc = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                env=ephemeral_env,
                timeout=spec.timeout_seconds,
                check=False,
            )
            raw_stdout = proc.stdout
            raw_stderr = proc.stderr
            exit_code = proc.returncode
        except subprocess.TimeoutExpired as exc:
            raw_stdout = exc.stdout or "" if isinstance(exc.stdout, str) else ""
            raw_stderr = f"Command timed out after {spec.timeout_seconds}s: {exc}"
            exit_code = 124
        except Exception as exc:
            raw_stdout = ""
            raw_stderr = f"Execution failed: {exc}"
            exit_code = 1

        # Sanitize stdout and stderr through redaction gate
        sanitized_stdout_res = self.redaction_gate.sanitize(raw_stdout)
        sanitized_stderr_res = self.redaction_gate.sanitize(raw_stderr)

        total_redacted = (
            sanitized_stdout_res.redacted_count + sanitized_stderr_res.redacted_count
        )
        notice = (
            sanitized_stdout_res.transparency_notice
            or sanitized_stderr_res.transparency_notice
        )

        return SuperCliExecutionResult(
            exit_code=exit_code,
            stdout=sanitized_stdout_res.sanitized_text,
            stderr=sanitized_stderr_res.sanitized_text,
            redacted_count=total_redacted,
            transparency_notice=notice,
        )

    def simulate_mock_execution(
        self,
        spec: SuperCliCommandSpec,
        simulated_stdout: str,
        simulated_stderr: str = "",
        exit_code: int = 0,
    ) -> SuperCliExecutionResult:
        """Simulate a CLI execution for hermetic testing and verification."""
        sanitized_stdout_res = self.redaction_gate.sanitize(simulated_stdout)
        sanitized_stderr_res = self.redaction_gate.sanitize(simulated_stderr)

        total_redacted = (
            sanitized_stdout_res.redacted_count + sanitized_stderr_res.redacted_count
        )
        notice = (
            sanitized_stdout_res.transparency_notice
            or sanitized_stderr_res.transparency_notice
        )

        return SuperCliExecutionResult(
            exit_code=exit_code,
            stdout=sanitized_stdout_res.sanitized_text,
            stderr=sanitized_stderr_res.sanitized_text,
            redacted_count=total_redacted,
            transparency_notice=notice,
        )
