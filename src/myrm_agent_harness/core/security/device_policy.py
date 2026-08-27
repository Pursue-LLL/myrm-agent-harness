"""Device Security Policy and Batch High-Risk Risk Assessment.

Provides device-level security configuration SSOT and dual-insurance risk assessment
for batch operations across remote devices, cloud sandboxes, and multi-agent coordination.

[INPUT]
  ToolCall sequences, command strings, and device security policies.

[OUTPUT]
  - DeviceSecurityPolicy: frozen policy configuration model.
  - BatchRiskAssessment: evaluation result with impact radius and dual insurance gates.
  - evaluate_batch_risk(): pure function evaluating a sequence of tool calls.

[POS]
Foundation layer in core/security. Zero internal dependencies on agent runtime.
Consumed by agent/middlewares/approval/batch_processor.py and server tool policy overlays.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain_core.messages import ToolCall

_DEFAULT_MAX_BATCH_SIZE: int = 15

# Standard destructive or mutating permission types
_MUTATING_PERMISSIONS: frozenset[str] = frozenset({
    "file_write",
    "file_edit",
    "file_delete",
    "shell_exec",
    "code_interpreter",
    "browser_evaluate",
    "browser_fill",
    "browser_upload",
    "browser_download",
    "skill_manage",
    "cron_manage",
    "desktop_control",
    "system_manage",
})

# High-risk verbs that trigger dual insurance in batch execution or compound commands
_DEFAULT_HIGH_RISK_VERBS: frozenset[str] = frozenset({
    "rm",
    "del",
    "erase",
    "shred",
    "pkill",
    "kill",
    "killall",
    "systemctl",
    "service",
    "reboot",
    "shutdown",
    "mkfs",
    "dd",
    "format",
    "truncate",
    "drop",
})

_COMPOUND_SPLIT_REGEX = re.compile(r"\s*(?:&&|\|\||;)\s*")


@dataclass(frozen=True, slots=True)
class DeviceSecurityPolicy:
    """Device-level security policy SSOT for fleet management and sandboxes."""

    device_id: str | None = None
    max_batch_size: int = _DEFAULT_MAX_BATCH_SIZE
    high_risk_verbs: frozenset[str] = _DEFAULT_HIGH_RISK_VERBS
    enforce_dual_insurance: bool = True
    destructive_batch_size_threshold: int = 3
    restricted_paths: frozenset[str] = frozenset({".env", ".key", ".pem", ".git", "id_rsa"})

    @classmethod
    def default(cls) -> DeviceSecurityPolicy:
        return cls()


@dataclass(frozen=True, slots=True)
class BatchRiskAssessment:
    """Assessment result for a batch of tool calls."""

    is_batch: bool
    batch_size: int
    is_high_risk: bool
    requires_dual_insurance: bool
    allow_always_blocked: bool
    reasons: tuple[str, ...] = ()
    impacted_targets: tuple[str, ...] = ()
    mutating_count: int = 0
    read_only_count: int = 0

    @property
    def has_violations(self) -> bool:
        return len(self.reasons) > 0


def _extract_target_from_args(args: dict[str, Any]) -> str | None:
    for key in ("path", "file_path", "target_path", "target", "url", "command", "code", "name"):
        val = args.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _detect_compound_command_risk(
    command: str,
    high_risk_verbs: frozenset[str],
) -> tuple[bool, int, list[str]]:
    """Detect if a single compound shell command contains multiple high-risk segments."""
    segments = [s.strip() for s in _COMPOUND_SPLIT_REGEX.split(command) if s.strip()]
    if len(segments) <= 1:
        # Check single command verb
        first_word = command.strip().split()[0].lower() if command.strip() else ""
        if first_word in high_risk_verbs:
            return True, 1, [command.strip()]
        return False, len(segments), []

    high_risk_found: list[str] = []
    for seg in segments:
        words = seg.split()
        if words and words[0].lower() in high_risk_verbs:
            high_risk_found.append(seg)

    return len(high_risk_found) > 0, len(segments), high_risk_found


def evaluate_batch_risk(
    tool_calls: list[ToolCall | dict[str, Any]],
    policy: DeviceSecurityPolicy | None = None,
    *,
    permission_resolver: Any = None,
) -> BatchRiskAssessment:
    """Evaluate batch risk and impact radius against DeviceSecurityPolicy.

    Pure function with microsecond execution time and 0 prompt token overhead.
    """
    effective_policy = policy or DeviceSecurityPolicy.default()
    batch_size = len(tool_calls)
    reasons: list[str] = []
    impacted_targets: list[str] = []

    mutating_count = 0
    read_only_count = 0
    high_risk_verbs_hit: list[str] = []
    restricted_path_hit: list[str] = []

    # 1. Inspect inter-tool batch
    for tc in tool_calls:
        name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
        args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
        if not isinstance(args, dict):
            args = {}

        target = _extract_target_from_args(args)
        if target:
            impacted_targets.append(target)

        # Check restricted path hit
        if target:
            for rp in effective_policy.restricted_paths:
                if rp in target:
                    restricted_path_hit.append(target)
                    break

        # Check shell command compound risk inside single tool
        if name in ("shell_exec", "code_interpreter", "bash_code_execute_tool"):
            cmd = str(args.get("command", "") or args.get("code", "") or args.get("data", ""))
            has_hr, _seg_count, hr_segs = _detect_compound_command_risk(cmd, effective_policy.high_risk_verbs)
            if has_hr:
                high_risk_verbs_hit.extend(hr_segs)
            mutating_count += 1
            continue

        # Check tool permission type
        perm = "unknown"
        if permission_resolver and callable(permission_resolver):
            try:
                perm = permission_resolver(name, args)
            except Exception:
                perm = "unknown"
        elif name.startswith("file_delete") or name.startswith("file_write") or name.startswith("file_edit"):
            perm = "file_write" if "write" in name or "edit" in name else "file_delete"
        elif name.startswith("file_read") or name.startswith("read_file"):
            perm = "file_read"

        if perm in _MUTATING_PERMISSIONS or "delete" in name or "write" in name or "edit" in name or "kill" in name:
            mutating_count += 1
        else:
            read_only_count += 1

    # 2. Threshold and Policy Evaluations
    is_batch = batch_size > 1 or (mutating_count >= 1 and len(high_risk_verbs_hit) > 1)

    if batch_size > effective_policy.max_batch_size:
        reasons.append(f"Batch size {batch_size} exceeds maximum permitted limit {effective_policy.max_batch_size}")

    if restricted_path_hit:
        reasons.append(f"Batch targets sensitive protected paths: {', '.join(restricted_path_hit[:3])}")

    if high_risk_verbs_hit:
        reasons.append(f"Batch contains high-risk destructive operations: {', '.join(high_risk_verbs_hit[:3])}")

    if mutating_count >= effective_policy.destructive_batch_size_threshold:
        reasons.append(
            f"Batch contains {mutating_count} mutating operations (threshold: {effective_policy.destructive_batch_size_threshold})"
        )

    is_high_risk = len(reasons) > 0 or (mutating_count > 0 and len(high_risk_verbs_hit) > 0)
    requires_dual_insurance = bool(effective_policy.enforce_dual_insurance and is_high_risk and mutating_count > 0)
    allow_always_blocked = bool(requires_dual_insurance or is_high_risk)

    return BatchRiskAssessment(
        is_batch=is_batch,
        batch_size=batch_size,
        is_high_risk=is_high_risk,
        requires_dual_insurance=requires_dual_insurance,
        allow_always_blocked=allow_always_blocked,
        reasons=tuple(reasons),
        impacted_targets=tuple(impacted_targets),
        mutating_count=mutating_count,
        read_only_count=read_only_count,
    )


__all__ = [
    "BatchRiskAssessment",
    "DeviceSecurityPolicy",
    "evaluate_batch_risk",
]
