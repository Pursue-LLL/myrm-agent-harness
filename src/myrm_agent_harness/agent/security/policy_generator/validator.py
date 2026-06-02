"""Validation logic for generated security policies.

Checks generated configs for safety issues, conflicts with existing rules,
and structural correctness.

[INPUT]
- Generated policy config dict (from parser.py)
- Optional current config for conflict detection

[OUTPUT]
- validate_generated_policy(): (is_valid, warnings)
- PolicyWarning: typed warning with severity

[POS]
Safety guard for LLM-generated policies. Deterministic, no LLM calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class WarningSeverity(StrEnum):
    """Severity level of a policy validation warning."""

    INFO = "info"
    WARNING = "warning"
    DANGER = "danger"


@dataclass(frozen=True, slots=True)
class PolicyWarning:
    """A single validation warning for a generated policy."""

    message: str
    severity: WarningSeverity
    field: str


_DANGEROUS_PERMISSION_PATTERNS = frozenset({
    ("shell_exec", "*", "allow"),
    ("code_interpreter", "*", "allow"),
    ("browser_evaluate", "*", "allow"),
    ("file_delete", "*", "allow"),
})


def validate_generated_policy(
    generated: dict[str, object],
    current_config: dict[str, object] | None = None,
) -> tuple[bool, list[PolicyWarning]]:
    """Validate a generated policy config for safety and correctness.

    Args:
        generated: The generated SecurityConfig dict from the parser.
        current_config: Optional current config for conflict detection.

    Returns:
        Tuple of (is_valid, list_of_warnings). A config can be valid but
        still have warnings (e.g. overly permissive rules).
    """
    warnings: list[PolicyWarning] = []

    if not generated:
        warnings.append(PolicyWarning(
            message="Generated policy is empty — no changes will be applied",
            severity=WarningSeverity.WARNING,
            field="root",
        ))
        return True, warnings

    _check_permissions(generated, warnings)
    _check_path_policy(generated, warnings)
    _check_privacy_policy(generated, warnings)
    _check_network_allowlist(generated, warnings)

    if current_config:
        _check_conflicts(generated, current_config, warnings)

    has_danger = any(w.severity == WarningSeverity.DANGER for w in warnings)
    return not has_danger, warnings


def _check_permissions(config: dict[str, object], warnings: list[PolicyWarning]) -> None:
    """Check permission rules for dangerous patterns."""
    permissions = config.get("permissions")
    if not isinstance(permissions, dict):
        return

    for perm, value in permissions.items():
        if isinstance(value, str) and value == "allow":
            if (perm, "*", "allow") in _DANGEROUS_PERMISSION_PATTERNS:
                warnings.append(PolicyWarning(
                    message=f"Allowing all '{perm}' operations is dangerous",
                    severity=WarningSeverity.DANGER,
                    field=f"permissions.{perm}",
                ))
        elif isinstance(value, dict):
            for pattern, action in value.items():
                if action == "allow" and pattern == "*" and (perm, "*", "allow") in _DANGEROUS_PERMISSION_PATTERNS:
                    warnings.append(PolicyWarning(
                        message=f"Allowing all '{perm}' operations is dangerous",
                        severity=WarningSeverity.DANGER,
                        field=f"permissions.{perm}.{pattern}",
                    ))


def _check_path_policy(config: dict[str, object], warnings: list[PolicyWarning]) -> None:
    """Check path policy for issues."""
    path_policy = config.get("pathPolicy")
    if not isinstance(path_policy, dict):
        return

    allowed_roots = path_policy.get("allowedRoots")
    if isinstance(allowed_roots, list):
        for root in allowed_roots:
            root_str = str(root)
            if root_str in ("/", "~", "C:\\"):
                warnings.append(PolicyWarning(
                    message=f"Allowing root path '{root_str}' as allowed_root bypasses path protection",
                    severity=WarningSeverity.DANGER,
                    field="pathPolicy.allowedRoots",
                ))
            elif root_str.startswith("/etc") or root_str.startswith("/sys"):
                warnings.append(PolicyWarning(
                    message=f"System path '{root_str}' in allowedRoots is unusual",
                    severity=WarningSeverity.WARNING,
                    field="pathPolicy.allowedRoots",
                ))


def _check_privacy_policy(config: dict[str, object], warnings: list[PolicyWarning]) -> None:
    """Check privacy policy for issues."""
    privacy = config.get("privacyPolicy")
    if not isinstance(privacy, dict):
        return

    if privacy.get("enabled") and privacy.get("s3Action") == "warn":
        warnings.append(PolicyWarning(
            message="S3 (confidential) data set to 'warn' only — ID cards and bank cards will not be protected",
            severity=WarningSeverity.WARNING,
            field="privacyPolicy.s3Action",
        ))


def _check_network_allowlist(config: dict[str, object], warnings: list[PolicyWarning]) -> None:
    """Check network allowlist for overly broad entries."""
    allowlist = config.get("networkAllowlist")
    if not isinstance(allowlist, list):
        return

    for domain in allowlist:
        domain_str = str(domain)
        if domain_str == "*" or domain_str == "*.*":
            warnings.append(PolicyWarning(
                message="Wildcard '*' in network allowlist disables all domain approval checks",
                severity=WarningSeverity.DANGER,
                field="networkAllowlist",
            ))


def _check_conflicts(
    generated: dict[str, object],
    current: dict[str, object],
    warnings: list[PolicyWarning],
) -> None:
    """Detect conflicts between generated and current config."""
    gen_perms = generated.get("permissions")
    cur_perms = current.get("permissions")

    if not isinstance(gen_perms, dict) or not isinstance(cur_perms, dict):
        return

    for perm, gen_value in gen_perms.items():
        if perm not in cur_perms:
            continue

        cur_value = cur_perms[perm]
        gen_action = gen_value if isinstance(gen_value, str) else None
        cur_action = cur_value if isinstance(cur_value, str) else None

        if (
            gen_action
            and cur_action
            and gen_action != cur_action
            and gen_action == "allow"
            and cur_action == "deny"
        ):
            warnings.append(PolicyWarning(
                message=f"Overriding existing DENY on '{perm}' with ALLOW",
                severity=WarningSeverity.WARNING,
                field=f"permissions.{perm}",
            ))
