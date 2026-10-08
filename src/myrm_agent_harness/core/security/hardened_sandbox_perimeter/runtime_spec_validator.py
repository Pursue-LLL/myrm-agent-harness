"""
[POS] src/myrm_agent_harness/core/security/hardened_sandbox_perimeter/runtime_spec_validator.py
[INPUT] .types (HardenedSandboxSpec, RuntimeSpecValidationResult, RuntimeSpecValidationVerdictEnum)
[OUTPUT] RuntimeSpecValidator

Validates that sandbox operational specifications satisfy strict production hardening invariants:
Non-root execution, read-only root filesystem, tmpfs noexec flags, dedicated persistent volume mounts,
and cgroups v2 resource ceilings.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from .types import (
    HardenedSandboxSpec,
    RuntimeSpecValidationResult,
    RuntimeSpecValidationVerdictEnum,
)


class RuntimeSpecValidator:
    """Rigid validator for sandbox container and MicroVM runtime specifications."""

    def validate_spec(self, spec: HardenedSandboxSpec) -> RuntimeSpecValidationResult:
        """Evaluate a HardenedSandboxSpec against production hardening baselines."""
        violations: list[str] = []
        primary_verdict = RuntimeSpecValidationVerdictEnum.VALID

        # Check 1: Non-root user requirements
        if not spec.is_non_root or spec.uid == 0 or spec.gid == 0:
            violations.append(
                f"Sandbox must run as non-root user (is_non_root={spec.is_non_root}, uid={spec.uid}, gid={spec.gid})."
            )
            if primary_verdict == RuntimeSpecValidationVerdictEnum.VALID:
                primary_verdict = RuntimeSpecValidationVerdictEnum.INVALID_ROOT_USER

        # Check 2: Read-only root filesystem
        if not spec.read_only_rootfs:
            violations.append("Root filesystem must be mounted strictly read-only to prevent tampering.")
            if primary_verdict == RuntimeSpecValidationVerdictEnum.VALID:
                primary_verdict = RuntimeSpecValidationVerdictEnum.INVALID_WRITABLE_ROOTFS

        # Check 3: tmpfs noexec flag
        if not spec.tmpfs_noexec:
            violations.append("Temporary in-memory directories (/tmp) must be mounted with noexec flag.")
            if primary_verdict == RuntimeSpecValidationVerdictEnum.VALID:
                primary_verdict = RuntimeSpecValidationVerdictEnum.INVALID_MISSING_TMPFS_NOEXEC

        # Check 4: Dedicated persistent volume path
        if not spec.persistent_volume_path or not spec.persistent_volume_path.startswith("/"):
            violations.append(
                f"Persistent volume path must be a valid absolute mount target (got: '{spec.persistent_volume_path}')."
            )
            if primary_verdict == RuntimeSpecValidationVerdictEnum.VALID:
                primary_verdict = RuntimeSpecValidationVerdictEnum.INVALID_NO_PERSISTENT_VOLUME

        # Check 5: Resource bounds (cgroups limits)
        if spec.memory_limit_mb < 64 or spec.memory_limit_mb > 32768:
            violations.append(f"Memory limit {spec.memory_limit_mb}MB is out of safe bounds [64MB, 32768MB].")
            if primary_verdict == RuntimeSpecValidationVerdictEnum.VALID:
                primary_verdict = RuntimeSpecValidationVerdictEnum.INVALID_RESOURCE_BOUNDS

        if spec.cpu_quota_pct <= 0.0 or spec.cpu_quota_pct > 64.0:
            violations.append(f"CPU quota {spec.cpu_quota_pct} is out of safe bounds (0.0, 64.0].")
            if primary_verdict == RuntimeSpecValidationVerdictEnum.VALID:
                primary_verdict = RuntimeSpecValidationVerdictEnum.INVALID_RESOURCE_BOUNDS

        if spec.pids_max < 10 or spec.pids_max > 2048:
            violations.append(f"Process limit pids_max={spec.pids_max} is out of safe bounds [10, 2048].")
            if primary_verdict == RuntimeSpecValidationVerdictEnum.VALID:
                primary_verdict = RuntimeSpecValidationVerdictEnum.INVALID_RESOURCE_BOUNDS

        is_valid = len(violations) == 0
        return RuntimeSpecValidationResult(
            is_valid=is_valid,
            verdict=primary_verdict if not is_valid else RuntimeSpecValidationVerdictEnum.VALID,
            violations=violations,
        )
