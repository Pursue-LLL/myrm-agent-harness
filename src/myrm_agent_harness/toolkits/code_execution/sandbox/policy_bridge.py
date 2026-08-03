"""Bridge between the permission engine's PathPolicy and OS-level SandboxPolicy."""

from __future__ import annotations

from myrm_agent_harness.agent.security.types import AccessRoot
from myrm_agent_harness.toolkits.code_execution.sandbox.sandbox_types import SandboxPolicy


def build_sandbox_policy_from_path_policy(
    work_dir: str,
    access_roots: tuple[AccessRoot, ...] = (),
    allow_network: bool = True,
    extra_writable: tuple[str, ...] = (),
) -> SandboxPolicy:
    """Create a SandboxPolicy that mirrors writable PathPolicy.access_roots."""
    writable = {work_dir}
    for root in access_roots:
        if root.writable:
            writable.add(root.path)
    writable.update(extra_writable)

    return SandboxPolicy(
        writable_paths=tuple(sorted(writable)),
        allow_network=allow_network,
    )
