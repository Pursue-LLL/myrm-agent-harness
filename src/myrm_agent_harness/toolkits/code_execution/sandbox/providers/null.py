"""No-op sandbox provider — transparent passthrough.

Used when:
- sandbox mode is DISABLE
- running inside a container (isolation already exists)
- no OS-level sandbox tool is available on the host

[INPUT]
- toolkits.code_execution.sandbox.sandbox_types::SandboxPolicy (POS: Foundation layer — all sandbox modules import from here.)

[OUTPUT]
- NullProvider: Passthrough provider that applies no OS-level restrictions.

[POS]
No-op sandbox provider — transparent passthrough.
"""

from __future__ import annotations

import asyncio

from myrm_agent_harness.toolkits.code_execution.sandbox.sandbox_types import (
    SandboxPolicy,
)


class NullProvider:
    """Passthrough provider that applies no OS-level restrictions."""

    @property
    def name(self) -> str:
        return "null"

    def wrap_command(
        self,
        shell_path: str,
        shell_args: tuple[str, ...],
        work_dir: str,
        policy: SandboxPolicy,
    ) -> tuple[str, tuple[str, ...]]:
        return shell_path, shell_args

    def is_available(self) -> bool:
        return True

    async def create_process(
        self,
        shell_path: str,
        shell_args: tuple[str, ...],
        work_dir: str,
        policy: SandboxPolicy,
        env: dict[str, str],
    ) -> asyncio.subprocess.Process | None:
        return None
