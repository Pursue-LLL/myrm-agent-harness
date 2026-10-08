"""
[POS] src/myrm_agent_harness/core/security/dynamic_toolchain_provenance/jit_sandbox_confiner.py
[INPUT] time, uuid, logging, typing, .types
[OUTPUT] JITSandboxConfiner

Just-In-Time (JIT) least-privilege sandbox confinement policy generator.
Converts manifest-declared capabilities into rigid sandbox enforcement profiles,
strictly forbidding broad system access, root path mountings, and core credentials.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import time
import uuid

from .types import SandboxConfinementPolicy, SkillProvenanceManifest

logger = logging.getLogger(__name__)


class JITSandboxConfiner:
    """Generates and evaluates strict JIT sandbox confinement boundaries for external skills."""

    FORBIDDEN_ROOT_PATHS: tuple[str, ...] = (
        "/",
        "/etc",
        "/usr",
        "/bin",
        "/sbin",
        "/var",
        "~/.ssh",
        "~/.gnupg",
        "C:\\Windows",
        "C:\\Program Files",
    )

    FORBIDDEN_ENV_SECRETS: tuple[str, ...] = (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "GITHUB_TOKEN",
        "DATABASE_URL",
        "MYRM_MASTER_SECRET",
    )

    def issue_confinement_policy(self, manifest: SkillProvenanceManifest) -> SandboxConfinementPolicy:
        """Issue least-privilege confinement profile based on declared capabilities."""
        now = time.time()
        policy_id = f"confine-{uuid.uuid4().hex[:12]}"

        # 1. Filter and normalize allowed paths (strip forbidden system paths)
        sanitized_paths: list[str] = []
        for path in manifest.declared_paths:
            normalized = path.strip()
            if any(normalized == fp or normalized.startswith(f"{fp}/") for fp in self.FORBIDDEN_ROOT_PATHS):
                logger.warning(
                    "Stripped forbidden root path '%s' from skill '%s' declared capabilities.",
                    normalized,
                    manifest.skill_id,
                )
                continue
            if normalized:
                sanitized_paths.append(normalized)

        # 2. Filter allowed environment variables (strip master credentials)
        sanitized_envs: list[str] = []
        for env_key in manifest.declared_env_keys:
            key_upper = env_key.strip().upper()
            if key_upper in self.FORBIDDEN_ENV_SECRETS:
                logger.warning(
                    "Stripped forbidden master secret key '%s' from skill '%s' declared envs.",
                    env_key,
                    manifest.skill_id,
                )
                continue
            if env_key:
                sanitized_envs.append(env_key.strip())

        # 3. Normalize allowed network domains
        sanitized_domains: list[str] = [
            domain.strip().lower() for domain in manifest.declared_domains if domain.strip()
        ]

        policy = SandboxConfinementPolicy(
            policy_id=policy_id,
            skill_id=manifest.skill_id,
            allowed_domains=sanitized_domains,
            allowed_paths=sanitized_paths,
            allowed_env_keys=sanitized_envs,
            is_confined=True,
            created_at=now,
        )

        logger.info(
            "Issued JIT sandbox confinement policy %s for skill '%s' (domains=%d, paths=%d, envs=%d)",
            policy_id,
            manifest.skill_id,
            len(sanitized_domains),
            len(sanitized_paths),
            len(sanitized_envs),
        )
        return policy

    def is_network_call_permitted(self, policy: SandboxConfinementPolicy, domain: str) -> bool:
        """Evaluate if outbound network target is permitted under confinement policy."""
        target_domain = domain.strip().lower()
        for allowed in policy.allowed_domains:
            if target_domain == allowed or target_domain.endswith(f".{allowed}"):
                return True
        return False

    def is_path_access_permitted(self, policy: SandboxConfinementPolicy, path: str) -> bool:
        """Evaluate if filesystem target is permitted under confinement policy."""
        target_path = path.strip()
        return any(
            target_path == allowed or target_path.startswith(f"{allowed}/")
            for allowed in policy.allowed_paths
        )

    def is_env_access_permitted(self, policy: SandboxConfinementPolicy, env_key: str) -> bool:
        """Evaluate if environment variable query is permitted under confinement policy."""
        target_key = env_key.strip()
        return target_key in policy.allowed_env_keys
