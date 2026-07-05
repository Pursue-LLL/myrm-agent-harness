"""Local persistent shell session with sandbox support.

[INPUT]
session.persistent_session::PersistentSession (POS: Abstract persistent shell session base)
sandbox::detect_sandbox_provider (POS: Sandbox detection and provider selection)

[OUTPUT]
LocalPersistentSession: Concrete local shell session with OS-level sandbox support.
create_persistent_session: Factory function for creating sessions.

[POS]
Concrete PersistentSession for local execution. Integrates OS-level sandbox
(bwrap/seatbelt/AppContainer) and manages the actual shell subprocess creation.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.code_execution.platform import PlatformInfo
from myrm_agent_harness.toolkits.code_execution.session.persistent_session import (
    PersistentSession,
    SessionConfig,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.code_execution.sandbox import (
        SandboxPolicy,
        SandboxStatus,
    )

logger = logging.getLogger(__name__)


class LocalPersistentSession(PersistentSession):
    """Concrete implementation for local shell execution."""

    def __init__(
        self,
        config: SessionConfig,
        platform_info: PlatformInfo | None = None,
        sandbox_policy: SandboxPolicy | None = None,
    ):
        super().__init__(config, platform_info)
        self._sandbox_policy = sandbox_policy
        self._init_sandbox()

    def _init_sandbox(self) -> None:
        from myrm_agent_harness.toolkits.code_execution.sandbox import (
            SandboxMode,
            SandboxPolicy,
            detect_sandbox_provider,
        )

        mode = SandboxMode(self.config.sandbox_mode)
        self._sandbox_provider, self._sandbox_status = detect_sandbox_provider(mode=mode, platform_info=self._platform)
        if self._sandbox_policy is None:
            self._sandbox_policy = SandboxPolicy(writable_paths=(self.config.work_dir,))

    @property
    def sandbox_status(self) -> SandboxStatus:
        from myrm_agent_harness.toolkits.code_execution.sandbox import SandboxStatus

        return self._sandbox_status or SandboxStatus(False, "null", "not initialized")

    @property
    def is_sandboxed(self) -> bool:
        return self._sandbox_status is not None and self._sandbox_status.enabled

    async def close(self) -> None:
        await super().close()
        if hasattr(self._sandbox_provider, "cleanup"):
            self._sandbox_provider.cleanup()

    async def _create_process(self) -> asyncio.subprocess.Process:
        p = self._platform
        shell_path, shell_args = p.shell_path, p.shell_args
        merged_env = {**os.environ, **self.config.env}

        if self._sandbox_status and self._sandbox_status.enabled and self._sandbox_policy:
            native_proc = await self._sandbox_provider.create_process(
                shell_path=shell_path,
                shell_args=shell_args,
                work_dir=self.config.work_dir,
                policy=self._sandbox_policy,
                env=merged_env,
            )
            if native_proc is not None:
                logger.info(f" Shell launch (native sandbox): {self._sandbox_provider.name}")
                return native_proc

            shell_path, shell_args = self._sandbox_provider.wrap_command(
                shell_path=shell_path,
                shell_args=shell_args,
                work_dir=self.config.work_dir,
                policy=self._sandbox_policy,
            )

        kwargs: dict[str, object] = {
            "stdin": asyncio.subprocess.PIPE,
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.STDOUT,
            "cwd": self.config.work_dir,
            "env": merged_env,
        }
        if p.is_windows:
            kwargs["creationflags"] = p.process_group_creation_flag
        elif not (self._sandbox_status and self._sandbox_status.enabled):
            kwargs["start_new_session"] = True

        logger.info(f" Shell launch: {shell_path} {shell_args}")
        return await asyncio.create_subprocess_exec(shell_path, *shell_args, **kwargs)  # type: ignore


def create_persistent_session(
    config: SessionConfig, sandbox_policy: SandboxPolicy | None = None
) -> LocalPersistentSession:
    """Factory function for creating local persistent sessions."""
    return LocalPersistentSession(config, sandbox_policy=sandbox_policy)
