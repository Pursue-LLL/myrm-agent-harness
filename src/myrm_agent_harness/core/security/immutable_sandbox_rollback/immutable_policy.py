"""Policy engine enforcing read-only immutable host system directories and blast radius assessment."""

from __future__ import annotations

import logging
import re

from myrm_agent_harness.core.security.immutable_sandbox_rollback.types import (
    BlastRadiusTier,
    CommandBlastRadiusAssessment,
    SandboxMountSpec,
)

logger = logging.getLogger(__name__)

# Core immutable system directories that cannot be mutated by sandboxed agents
DEFAULT_IMMUTABLE_SYSTEM_PATHS: tuple[str, ...] = (
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/lib64",
    "/etc",
    "/System",
    "/Library",
    "/var/root",
)

# Patterns that attempt to pipe to root shell or write to immutable system paths
_CRITICAL_MUTATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"curl\s+[^|]+\|\s*(sudo\s+)?(bash|sh|zsh)", re.IGNORECASE),
    re.compile(r"wget\s+[^|]+\|\s*(sudo\s+)?(bash|sh|zsh)", re.IGNORECASE),
    re.compile(r"(sudo\s+)?(apt|apt-get|pacman|yum|dnf|apk|zypper)\s+(install|remove|purge|-S|-R|-U)", re.IGNORECASE),
    re.compile(r"(sudo\s+)?rm\s+-rf?\s+(/\s*|/usr|/bin|/etc|/System)", re.IGNORECASE),
    re.compile(r"(>|>>)\s*(/usr|/bin|/sbin|/etc|/System|/lib)", re.IGNORECASE),
)


class ImmutableSandboxPolicyEngine:
    """Enforces immutable OS root paths and evaluates shell command blast radius."""

    def __init__(self, immutable_paths: tuple[str, ...] | None = None) -> None:
        self._immutable_paths: tuple[str, ...] = immutable_paths or DEFAULT_IMMUTABLE_SYSTEM_PATHS

    def generate_mount_spec(self, workspace_path: str = "/workspace") -> SandboxMountSpec:
        """Generate hardened container mount specification with read-only root and bind mounts."""
        return SandboxMountSpec(
            read_only_root=True,
            read_only_bind_mounts=list(self._immutable_paths),
            writable_workspace_path=workspace_path,
            tmpfs_mounts=["/tmp", "/run"],
            drop_all_capabilities=True,
        )

    def generate_docker_flags(self, spec: SandboxMountSpec) -> list[str]:
        """Translate mount specification into deterministic CLI arguments for Docker/Podman."""
        flags: list[str] = []
        if spec.read_only_root:
            flags.append("--read-only")

        for ro_path in spec.read_only_bind_mounts:
            flags.extend(["-v", f"{ro_path}:{ro_path}:ro"])

        flags.extend(["-v", f"{spec.writable_workspace_path}:{spec.writable_workspace_path}:rw"])

        for tmpfs in spec.tmpfs_mounts:
            flags.extend(["--tmpfs", f"{tmpfs}:rw,noexec,nosuid,size=64m"])

        if spec.drop_all_capabilities:
            flags.extend(["--cap-drop=ALL"])

        return flags

    def assess_command_blast_radius(self, command: str) -> CommandBlastRadiusAssessment:
        """Assess the blast radius of a prospective shell execution before dispatching to sandbox.

        Mechanically enforced:
        - Commands attempting curl-pipe-to-sh or mutating /usr, /bin, /etc are blocked fail-closed.
        """
        stripped_cmd = command.strip()
        targeted_paths: list[str] = []

        # Check explicit path targets
        for p in self._immutable_paths:
            if re.search(rf"\b{re.escape(p)}(\b|/)", stripped_cmd) and any(
                kw in stripped_cmd for kw in (">", "rm ", "cp ", "mv ", "chmod ", "chown ", "install ")
            ):
                targeted_paths.append(p)

        # Check critical patterns
        matches_pattern = any(pattern.search(stripped_cmd) for pattern in _CRITICAL_MUTATION_PATTERNS)

        if targeted_paths or matches_pattern:
            return CommandBlastRadiusAssessment(
                command=stripped_cmd,
                tier=BlastRadiusTier.CRITICAL_HOST_POLLUTION,
                blocked=True,
                targeted_immutable_paths=sorted(set(targeted_paths)),
                mitigation_applied=(
                    "Command blocked by immutable host sandbox policy. "
                    "Mutations to core system paths (/usr, /etc, host binaries) are mechanically prohibited."
                ),
            )

        # Non-critical, evaluate if it mutates local workspace
        is_workspace_mutation = any(kw in stripped_cmd for kw in ("rm ", "touch ", "mkdir ", "git ", "npm ", "pip "))
        tier = BlastRadiusTier.MODERATE_MUTATION if is_workspace_mutation else BlastRadiusTier.ZERO_CONTAINED

        return CommandBlastRadiusAssessment(
            command=stripped_cmd,
            tier=tier,
            blocked=False,
            targeted_immutable_paths=[],
            mitigation_applied="",
        )
