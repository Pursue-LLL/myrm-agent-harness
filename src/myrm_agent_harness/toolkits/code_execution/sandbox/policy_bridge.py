"""Bridge between the permission engine's PathPolicy and OS-level SandboxPolicy.

Integrates with SandboxMountSecurityGate to validate and sanitize all mount targets
before injecting them into OS-level SandboxPolicy writable/readable paths.

[INPUT]
- myrm_agent_harness.core.security.types::AccessRoot (POS: Permission engine access root)
- myrm_agent_harness.toolkits.code_execution.sandbox.mount_security_gate::validate_and_sanitize_mounts (POS: Sandbox mount security gate)
- myrm_agent_harness.toolkits.code_execution.sandbox.sandbox_types::SandboxPolicy (POS: Sandbox security policy DTO)

[OUTPUT]
- build_sandbox_policy_from_path_policy: Converts access roots into sanitized SandboxPolicy

[POS]
Layer 2.5 Policy Bridge. Converts high-level PathPolicy roots into OS-level SandboxPolicy boundaries.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.types import AccessRoot
from myrm_agent_harness.toolkits.code_execution.sandbox.mount_security_gate import (
    MountMode,
    MountSpec,
    validate_and_sanitize_mounts,
)
from myrm_agent_harness.toolkits.code_execution.sandbox.sandbox_types import (
    SandboxPolicy,
)


def build_sandbox_policy_from_path_policy(
    work_dir: str,
    access_roots: tuple[AccessRoot, ...] = (),
    allow_network: bool = True,
    extra_writable: tuple[str, ...] = (),
    *,
    extra_readable: tuple[str, ...] = (),
    validate_gate: bool = True,
) -> SandboxPolicy:
    """Create a SandboxPolicy that mirrors writable/readable PathPolicy.access_roots.

    When validate_gate is True (default), all paths pass through SandboxMountSecurityGate
    to prevent path traversal, symlink escapes, dangerous system path mounts, and device injection.
    """
    if not validate_gate:
        writable = {work_dir}
        readable = set()
        for root in access_roots:
            if root.writable:
                writable.add(root.path)
            else:
                readable.add(root.path)
        writable.update(extra_writable)
        readable.update(extra_readable)
        return SandboxPolicy(
            writable_paths=tuple(sorted(writable)),
            readable_paths=tuple(sorted(readable)),
            allow_network=allow_network,
        )

    # Build MountSpecs for gate validation
    mount_specs: list[MountSpec] = [
        MountSpec(source_path=work_dir, mode=MountMode.RW, label="work_dir")
    ]
    for root in access_roots:
        mode = MountMode.RW if root.writable else MountMode.RO
        mount_specs.append(
            MountSpec(source_path=root.path, mode=mode, label=root.label or root.source)
        )
    for p in extra_writable:
        mount_specs.append(
            MountSpec(source_path=p, mode=MountMode.RW, label="extra_writable")
        )
    for p in extra_readable:
        mount_specs.append(
            MountSpec(source_path=p, mode=MountMode.RO, label="extra_readable")
        )

    sanitized = validate_and_sanitize_mounts(mount_specs)

    writable_paths = tuple(
        sorted(s.source_path for s in sanitized if s.mode == MountMode.RW)
    )
    readable_paths = tuple(
        sorted(s.source_path for s in sanitized if s.mode == MountMode.RO)
    )

    return SandboxPolicy(
        writable_paths=writable_paths,
        readable_paths=readable_paths,
        allow_network=allow_network,
    )
