"""
[POS] src/myrm_agent_harness/core/security/introspection_shield/blackhole_policy.py
[INPUT] fnmatch, logging, pathlib, time, typing
[OUTPUT] IntrospectionBlackholePolicy

Implements blackhole path containment and fake-root redirection for sandbox runtime introspection shielding.
Blocks snooping into host paths, container entrypoints, framework source code, and host configuration.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import fnmatch
import logging
import time
from pathlib import Path

from .types import (
    IntrospectionProbeType,
    ProbeEvaluationResult,
    ShieldActionEnum,
)

logger = logging.getLogger(__name__)

DEFAULT_BLACKHOLE_PATTERNS: tuple[str, ...] = (
    # Host & container deployment roots (Meta Muse leak prevention)
    "/opt/**",
    "/opt/hatch/**",
    "/app/entrypoint*",
    "/docker-entrypoint*",
    "/var/run/**",
    # Host OS system configs and runtime introspection pseudofiles
    "/proc/self/**",
    "/proc/1/**",
    "/proc/version",
    "/proc/cmdline",
    "/sys/class/**",
    "/etc/passwd",
    "/etc/shadow",
    "/etc/sudoers",
    "/etc/myrm/**",
    # Harness framework source code directories and internal hooks
    "**/myrm_agent_harness/**",
    "**/site-packages/myrm*/**",
    # Sensitive cloud & versioning control metadata
    "**/.git/config",
    "**/.ssh/**",
    "**/.aws/**",
    "**/.docker/**",
)


class IntrospectionBlackholePolicy:
    """Evaluates requested filesystem target paths against introspection blackhole patterns."""

    def __init__(
        self,
        custom_patterns: tuple[str, ...] | None = None,
        enable_fake_root: bool = True,
    ) -> None:
        self._patterns: list[str] = list(custom_patterns or DEFAULT_BLACKHOLE_PATTERNS)
        self._enable_fake_root: bool = enable_fake_root

    @property
    def patterns(self) -> tuple[str, ...]:
        """Active blackhole matching patterns."""
        return tuple(self._patterns)

    def add_custom_pattern(self, pattern: str) -> None:
        """Register an additional blackhole pattern."""
        if pattern and pattern not in self._patterns:
            self._patterns.append(pattern)

    def evaluate_path(
        self,
        target_path: str,
        workspace_root: Path | None = None,
    ) -> ProbeEvaluationResult:
        """Evaluate whether a path probe attempts to inspect protected internal infrastructure."""
        normalized = target_path.strip()
        if not normalized:
            return ProbeEvaluationResult(
                is_blocked=False,
                probe_type=None,
                attempted_target=target_path,
                action_taken=ShieldActionEnum.ALLOW_UNRESTRICTED,
                sanitized_path=target_path,
                explanation="Empty target path allowed.",
                timestamp=time.time(),
            )

        # Standardize path representation for fnmatch
        path_obj = Path(normalized)
        test_str = str(path_obj).replace("\\", "/")

        probe_type = self._detect_probe_type(test_str)
        is_hit = False

        for pattern in self._patterns:
            if fnmatch.fnmatch(test_str, pattern) or fnmatch.fnmatch(normalized, pattern):
                is_hit = True
                break

        if not is_hit:
            return ProbeEvaluationResult(
                is_blocked=False,
                probe_type=None,
                attempted_target=target_path,
                action_taken=ShieldActionEnum.ALLOW_UNRESTRICTED,
                sanitized_path=target_path,
                explanation="Target path is outside introspection blackholes.",
                timestamp=time.time(),
            )

        # Matched blackhole pattern: block or fake root redirect
        if self._enable_fake_root and workspace_root is not None:
            fake_redirect = str(workspace_root / "virtual_root" / path_obj.name)
            logger.warning(
                "Sandbox introspection probe redirected to fake root: %s → %s",
                target_path,
                fake_redirect,
            )
            return ProbeEvaluationResult(
                is_blocked=True,
                probe_type=probe_type,
                attempted_target=target_path,
                action_taken=ShieldActionEnum.FAKE_ROOT_REDIRECT,
                sanitized_path=fake_redirect,
                explanation=(
                    "Introspection probe detected against protected pattern. "
                    "Redirected to safe virtual fake root."
                ),
                timestamp=time.time(),
            )

        logger.warning("Sandbox introspection probe blackholed: %s", target_path)
        return ProbeEvaluationResult(
            is_blocked=True,
            probe_type=probe_type,
            attempted_target=target_path,
            action_taken=ShieldActionEnum.BLOCK_BLACKHOLE,
            sanitized_path="/dev/null",
            explanation=(
                "Access blocked by Introspection Shield: target matches blackhole pattern. "
                "Snooping into system infrastructure or framework source is prohibited."
            ),
            timestamp=time.time(),
        )

    @staticmethod
    def _detect_probe_type(path_str: str) -> IntrospectionProbeType:
        """Classify probe attack vector from target path signature."""
        if "/opt" in path_str or "/app/entrypoint" in path_str:
            return IntrospectionProbeType.HOST_PATH_PROBE
        if "/proc" in path_str or "/sys" in path_str:
            return IntrospectionProbeType.ENVIRONMENT_LEAK_PROBE
        if "/etc" in path_str:
            return IntrospectionProbeType.SYSTEM_CONFIG_INSPECTION
        if "myrm_agent_harness" in path_str or "site-packages" in path_str:
            return IntrospectionProbeType.FRAMEWORK_SOURCE_SNOOPING
        return IntrospectionProbeType.CONTAINER_TOPOLOGY_PROBE
