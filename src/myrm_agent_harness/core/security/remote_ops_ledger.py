"""Remote Operations Audit Ledger and Action Recovery.

Provides device-scoped action auditing, fingerprinting, execution tracking,
and symmetric recovery hint generation for remote sandbox and fleet management.

[INPUT]
  Tool calls, command strings, execution outputs, and device identifiers.

[OUTPUT]
  - ActionRecoveryHint: structured suggested recovery command/action.
  - RemoteOpsActionRecord: immutable structured action audit log entry.
  - derive_recovery_hint(): pure function extracting symmetric recovery clues.
  - compute_action_fingerprint(): deterministic action hash for idempotency.

[POS]
Foundation layer in core/security. Zero agent-internal dependencies.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ActionRecoveryHint:
    """Symmetric recovery action clue for quick incident mitigation (MTTR reduction)."""

    recovery_type: (
        str  # e.g., "shell_command", "file_restore", "service_restart", "manual_check"
    )
    recovery_command: str | None = None
    target_path: str | None = None
    description: str = ""
    is_automated: bool = False


@dataclass(frozen=True, slots=True)
class RemoteOpsActionRecord:
    """Device-level structured audit log entry."""

    action_id: str
    device_id: str
    tool_name: str
    action_type: str
    fingerprint: str
    timestamp: float = field(default_factory=time.time)
    args_summary: str = ""
    status: str = "pending"  # "pending", "success", "failed", "denied"
    exit_code: int | None = None
    error_message: str | None = None
    recovery_hint: ActionRecoveryHint | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "action_id": self.action_id,
            "device_id": self.device_id,
            "tool_name": self.tool_name,
            "action_type": self.action_type,
            "fingerprint": self.fingerprint,
            "timestamp": round(self.timestamp, 3),
            "args_summary": self.args_summary,
            "status": self.status,
            "exit_code": self.exit_code,
            "error_message": self.error_message,
        }
        if self.recovery_hint:
            result["recovery_hint"] = {
                "recovery_type": self.recovery_hint.recovery_type,
                "recovery_command": self.recovery_hint.recovery_command,
                "target_path": self.recovery_hint.target_path,
                "description": self.recovery_hint.description,
                "is_automated": self.recovery_hint.is_automated,
            }
        return result


def compute_action_fingerprint(tool_name: str, args: dict[str, Any]) -> str:
    """Compute a deterministic hash for tool invocation to ensure idempotency and auditing."""
    normalized_keys = sorted(args.keys())
    parts: list[str] = [f"tool={tool_name}"]
    for k in normalized_keys:
        val = args[k]
        if isinstance(val, (str, int, float, bool)):
            parts.append(f"{k}={val}")
        elif val is None:
            parts.append(f"{k}=null")
    payload = "&".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


_SERVICE_STOP_RE = re.compile(
    r"\b(?:systemctl\s+(?:stop|disable)|service\s+([a-zA-Z0-9_\-\.]+)\s+(?:stop|disable))\s*([a-zA-Z0-9_\-\.]*)",
    re.IGNORECASE,
)
_SERVICE_START_RE = re.compile(
    r"\b(?:systemctl\s+(?:start|enable)|service\s+([a-zA-Z0-9_\-\.]+)\s+(?:start|enable))\s*([a-zA-Z0-9_\-\.]*)",
    re.IGNORECASE,
)
_PKILL_RE = re.compile(
    r"\b(?:pkill|killall)\s+(?:-[a-zA-Z0-9]+\s+)?([a-zA-Z0-9_\-\.]+)", re.IGNORECASE
)


def derive_recovery_hint(
    tool_name: str,
    args: dict[str, Any],
    *,
    backup_path: str | None = None,
) -> ActionRecoveryHint | None:
    """Derive a symmetric recovery clue for a given mutating operation."""
    if backup_path:
        target_path = str(args.get("path") or args.get("file_path") or "")
        return ActionRecoveryHint(
            recovery_type="file_restore",
            target_path=target_path,
            recovery_command=(
                f"cp -p '{backup_path}' '{target_path}'" if target_path else None
            ),
            description=f"Restore original file from backup snapshot: {backup_path}",
            is_automated=True,
        )

    if tool_name in ("shell_exec", "code_interpreter", "bash_code_execute_tool"):
        cmd = str(args.get("command", "") or args.get("code", "")).strip()

        # Service stop recovery
        m_stop = _SERVICE_STOP_RE.search(cmd)
        if m_stop:
            svc = m_stop.group(1) or m_stop.group(2)
            if svc:
                return ActionRecoveryHint(
                    recovery_type="service_restart",
                    recovery_command=f"systemctl start {svc}",
                    description=f"Restart stopped system service: {svc}",
                    is_automated=True,
                )

        # Service start reverse check
        m_start = _SERVICE_START_RE.search(cmd)
        if m_start:
            svc = m_start.group(1) or m_start.group(2)
            if svc:
                return ActionRecoveryHint(
                    recovery_type="service_stop",
                    recovery_command=f"systemctl stop {svc}",
                    description=f"Stop service if started unintentionally: {svc}",
                    is_automated=True,
                )

        # Process kill recovery
        m_kill = _PKILL_RE.search(cmd)
        if m_kill:
            proc = m_kill.group(1)
            return ActionRecoveryHint(
                recovery_type="manual_check",
                recovery_command=None,
                description=f"Verify and relaunch terminated process: {proc}",
                is_automated=False,
            )

    return None


__all__ = [
    "ActionRecoveryHint",
    "RemoteOpsActionRecord",
    "compute_action_fingerprint",
    "derive_recovery_hint",
]
