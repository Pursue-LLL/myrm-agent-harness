"""[INPUT] types.py, stream_cleaner.py.
[OUTPUT] ExternalCliAgentAdapter: Process lifecycle orchestrator for heterogeneous CLI agents.
[POS] Core subprocess bridge with timeouts, graceful kill escalation, and verifiable receipt generation.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from typing import ClassVar

from myrm_agent_harness.agent.sub_agents.cli_adapter.stream_cleaner import (
    compute_receipt_hash,
    sanitize_cli_output,
)
from myrm_agent_harness.agent.sub_agents.cli_adapter.types import (
    ExternalAgentConfig,
    ProcessExecutionRequest,
    ProcessLaneStatus,
    ProcessReceipt,
)


class ExternalCliAgentAdapter:
    """Manages spawning, execution, timeout enforcement, and receipts for external CLI agents."""

    _DEFAULT_GRACE_PERIOD_S: ClassVar[float] = 2.0

    def __init__(self) -> None:
        self._configs: dict[str, ExternalAgentConfig] = {}
        self._receipts: dict[str, list[ProcessReceipt]] = {}
        self._lock = threading.Lock()

    def register_agent(self, config: ExternalAgentConfig) -> None:
        """Register an external CLI agent profile."""
        with self._lock:
            self._configs[config.agent_id] = config
            if config.agent_id not in self._receipts:
                self._receipts[config.agent_id] = []

    def get_agent(self, agent_id: str) -> ExternalAgentConfig | None:
        """Fetch registered agent config."""
        with self._lock:
            return self._configs.get(agent_id)

    def list_agents(self) -> list[ExternalAgentConfig]:
        """List all registered external CLI agents."""
        with self._lock:
            return list(self._configs.values())

    def unregister_agent(self, agent_id: str) -> bool:
        """Unregister an agent."""
        with self._lock:
            self._receipts.pop(agent_id, None)
            return self._configs.pop(agent_id, None) is not None

    def probe_health(self, agent_id: str) -> bool:
        """Verify executable presence in system PATH or filesystem."""
        config = self.get_agent(agent_id)
        if not config:
            return False

        # If absolute path, check file existence and execute permission
        if os.path.isabs(config.command):
            return os.path.isfile(config.command) and os.access(config.command, os.X_OK)

        # Otherwise look up in PATH
        return shutil.which(config.command) is not None

    def execute(
        self,
        agent_id: str,
        request: ProcessExecutionRequest,
    ) -> ProcessReceipt:
        """Synchronously execute a task through the external CLI agent with timeout protection."""
        config = self.get_agent(agent_id)
        if not config:
            raise KeyError(f"External agent not registered: {agent_id}")

        full_cmd = [config.command, *config.args, *request.extra_args]
        merged_env = os.environ.copy()
        merged_env.update(config.env)

        start_time = time.time()
        status = ProcessLaneStatus.RUNNING
        exit_code: int | None = None
        raw_stdout = ""
        raw_stderr = ""

        try:
            proc = subprocess.Popen(
                full_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=config.cwd,
                env=merged_env,
                text=True,
            )

            try:
                raw_stdout, raw_stderr = proc.communicate(
                    input=request.input_text,
                    timeout=config.timeout_seconds,
                )
                exit_code = proc.returncode
                status = (
                    ProcessLaneStatus.COMPLETED
                    if exit_code == 0
                    else ProcessLaneStatus.FAILED
                )
            except subprocess.TimeoutExpired:
                # Graceful SIGTERM escalation to SIGKILL
                status = ProcessLaneStatus.TIMED_OUT
                proc.terminate()
                try:
                    raw_stdout, raw_stderr = proc.communicate(timeout=self._DEFAULT_GRACE_PERIOD_S)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    raw_stdout, raw_stderr = proc.communicate()
                exit_code = proc.returncode
        except Exception as exc:
            status = ProcessLaneStatus.FAILED
            raw_stderr = f"Process spawning error: {exc}"
            exit_code = -1

        duration_ms = int((time.time() - start_time) * 1000)
        stdout_summary = sanitize_cli_output(raw_stdout)
        stderr_summary = sanitize_cli_output(raw_stderr)

        receipt_hash = compute_receipt_hash(
            execution_id=request.execution_id,
            agent_id=agent_id,
            exit_code=exit_code,
            stdout_summary=stdout_summary,
        )

        receipt = ProcessReceipt(
            execution_id=request.execution_id,
            agent_id=agent_id,
            kind=config.kind,
            status=status,
            exit_code=exit_code,
            duration_ms=duration_ms,
            stdout_summary=stdout_summary,
            stderr_summary=stderr_summary,
            receipt_hash=receipt_hash,
            created_at=time.time(),
        )

        with self._lock:
            self._receipts.setdefault(agent_id, []).append(receipt)

        return receipt

    def get_receipts(self, agent_id: str) -> list[ProcessReceipt]:
        """Fetch historical receipts for an agent lane."""
        with self._lock:
            return list(self._receipts.get(agent_id, []))

    def clear_receipts(self, agent_id: str) -> int:
        """Clear execution receipts history for an agent."""
        with self._lock:
            existing = self._receipts.get(agent_id, [])
            count = len(existing)
            self._receipts[agent_id] = []
            return count
