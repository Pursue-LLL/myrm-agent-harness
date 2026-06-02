"""Bridge between the permission engine's PathPolicy and OS-level SandboxPolicy.

Ensures consistent security rules across software and OS layers:
PathPolicy.allowed_roots are automatically propagated as writable paths
in the sandbox, providing a single source of truth.

[INPUT]
- (none)

[OUTPUT]
- build_sandbox_policy_from_path_policy: Create a SandboxPolicy that mirrors PathPolicy.allowed_ro...

[POS]
Bridge between the permission engine's PathPolicy and OS-level SandboxPolicy.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.code_execution.sandbox.sandbox_types import SandboxPolicy


def build_sandbox_policy_from_path_policy(
    work_dir: str,
    allowed_roots: tuple[str, ...] = (),
    allow_network: bool = True,
    extra_writable: tuple[str, ...] = (),
) -> SandboxPolicy:
    """Create a SandboxPolicy that mirrors PathPolicy.allowed_roots.

    Args:
        work_dir: Current workspace directory (always writable).
        allowed_roots: From ``PathPolicy.allowed_roots`` — propagated to writable_paths.
        allow_network: Whether outbound network is allowed.
        extra_writable: Additional writable paths beyond allowed_roots.

    Returns:
        SandboxPolicy with consistent writable paths.
    """
    writable = {work_dir}
    writable.update(allowed_roots)
    writable.update(extra_writable)

    return SandboxPolicy(
        writable_paths=tuple(sorted(writable)),
        allow_network=allow_network,
    )
