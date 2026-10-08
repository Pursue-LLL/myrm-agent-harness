"""Runtime Skill Integrity Verifier and Static Capability Inspector.

[INPUT]
- SKILL.md content string, optional SkillIntegrityManifest, signing key.

[OUTPUT]
- SkillAuditReport detailing signature validation, detected sensitive capabilities,
  and mandatory user consent requirements.

[POS]
- Harness core security module. Treats Agent Skills as first-class executable code,
  preventing prompt injection, supply-chain poisoning, and covert permission escalation.
"""

from __future__ import annotations

import hashlib
import hmac
import re

from myrm_agent_harness.core.security.secops_audit.types import (
    SkillAuditReport,
    SkillIntegrityManifest,
    SkillPermission,
)

_PERMISSION_PATTERNS: tuple[tuple[SkillPermission, tuple[re.Pattern[str], ...]], ...] = (
    (
        SkillPermission.EXECUTE_SHELL,
        (
            re.compile(r"\b(bash|sh|zsh|subprocess|os\.system|shell_exec|exec_command|run_command)\b", re.IGNORECASE),
            re.compile(r"`{3}(bash|sh|zsh|shell)", re.IGNORECASE),
            re.compile(r"\[执行\s*Shell\s*命令\]", re.IGNORECASE),
        ),
    ),
    (
        SkillPermission.NETWORK_EGRESS,
        (
            re.compile(r"\b(https?://|curl|wget|httpx|requests|fetch|socket|urllib)\b", re.IGNORECASE),
            re.compile(r"\[访问网络\]", re.IGNORECASE),
        ),
    ),
    (
        SkillPermission.FILE_SYSTEM_WRITE,
        (
            re.compile(r"\b(write_to_file|replace_file_content|rm\s+-rf|unlink|delete_file|create_file)\b", re.IGNORECASE),
            re.compile(r"open\s*\([^)]*['\"][wa\+]", re.IGNORECASE),
            re.compile(r"\[写入文件\]", re.IGNORECASE),
        ),
    ),
    (
        SkillPermission.ENV_SECRET_READ,
        (
            re.compile(r"\b(os\.environ|env_var|SECRET_KEY|API_KEY|TOKEN|PRIVATE_KEY)\b", re.IGNORECASE),
            re.compile(r"\[读取凭据\]", re.IGNORECASE),
        ),
    ),
)


class RuntimeSkillIntegrityVerifier:
    """Verifier for Agent Skill definitions, signatures, and capability declarations."""

    @staticmethod
    def compute_content_hash(content: str) -> str:
        """Compute SHA-256 fingerprint of skill content."""
        normalized = content.strip().encode("utf-8")
        return hashlib.sha256(normalized).hexdigest()

    @classmethod
    def detect_permissions(cls, content: str) -> tuple[SkillPermission, ...]:
        """Scan skill content statically for sensitive execution capabilities."""
        detected: set[SkillPermission] = set()
        for perm, patterns in _PERMISSION_PATTERNS:
            for pattern in patterns:
                if pattern.search(content):
                    detected.add(perm)
                    break
        # Sort deterministically
        return tuple(sorted(detected, key=lambda p: p.value))

    @classmethod
    def sign_manifest(
        cls,
        skill_name: str,
        skill_version: str,
        content: str,
        secret_key: str,
        signed_by: str = "security-team",
    ) -> SkillIntegrityManifest:
        """Generate a cryptographically signed integrity manifest for a Skill."""
        content_hash = cls.compute_content_hash(content)
        detected_perms = cls.detect_permissions(content)

        sign_payload = f"{skill_name}:{skill_version}:{content_hash}:{','.join(p.value for p in detected_perms)}"
        signature = hmac.new(
            secret_key.encode("utf-8"),
            sign_payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return SkillIntegrityManifest(
            skill_name=skill_name,
            skill_version=skill_version,
            content_hash=content_hash,
            declared_permissions=detected_perms,
            signature=signature,
            signed_by=signed_by,
        )

    @classmethod
    def verify_skill(
        cls,
        skill_name: str,
        content: str,
        manifest: SkillIntegrityManifest | None = None,
        secret_key: str | None = None,
    ) -> SkillAuditReport:
        """Audit a skill prior to mounting or execution.

        Checks hash integrity, signature validity, and unapproved capabilities.
        """
        content_hash = cls.compute_content_hash(content)
        detected_perms = cls.detect_permissions(content)
        violations: list[str] = []
        sig_verified = False

        unapproved: list[SkillPermission] = []
        if manifest:
            # 1. Content hash check
            if content_hash != manifest.content_hash:
                violations.append(
                    f"Content hash mismatch: actual '{content_hash[:8]}...' != manifest '{manifest.content_hash[:8]}...'. "
                    "Skill has been tampered with after signing."
                )

            # 2. Signature verification
            if secret_key:
                sign_payload = (
                    f"{manifest.skill_name}:{manifest.skill_version}:{manifest.content_hash}:"
                    f"{','.join(p.value for p in manifest.declared_permissions)}"
                )
                expected_sig = hmac.new(
                    secret_key.encode("utf-8"),
                    sign_payload.encode("utf-8"),
                    hashlib.sha256,
                ).hexdigest()
                if hmac.compare_digest(manifest.signature, expected_sig):
                    sig_verified = True
                else:
                    violations.append("Cryptographic signature verification failed.")
            else:
                # No key provided to verify, mark unverified
                sig_verified = False

            # 3. Capability escalation check
            declared_set = set(manifest.declared_permissions)
            for p in detected_perms:
                if p not in declared_set:
                    unapproved.append(p)
                    violations.append(
                        f"Undeclared sensitive permission detected: '{p.value}'. "
                        "Possible covert capability escalation."
                    )
        else:
            # Unsigned skill
            violations.append("Skill lacks cryptographic integrity manifest (unsigned).")

        is_valid = len(violations) == 0 and sig_verified
        # Requires explicit consent if any dangerous permission is present or skill is unsigned
        dangerous_perms = {
            SkillPermission.EXECUTE_SHELL,
            SkillPermission.NETWORK_EGRESS,
            SkillPermission.FILE_SYSTEM_WRITE,
        }
        has_dangerous = any(p in dangerous_perms for p in detected_perms)
        requires_consent = has_dangerous or not is_valid

        return SkillAuditReport(
            skill_name=skill_name,
            is_valid=is_valid,
            content_hash=content_hash,
            detected_permissions=detected_perms,
            unapproved_permissions=tuple(unapproved),
            signature_verified=sig_verified,
            requires_user_consent=requires_consent,
            violations=tuple(violations),
        )
