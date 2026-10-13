"""Tiered Risk HITL Evaluator and Dynamic Brake Gate.

[INPUT]
- None (standard typing & dataclasses)

[OUTPUT]
- RiskTier, TieredRiskEvaluation, TieredRiskEvaluator

[POS]
Three-tier risk classification engine for Human-in-the-Loop tool governance.
Classifies operations into READ (fast-pass), WRITE (summary & dry-run), and HIGH_RISK (mandatory NEED_CONFIRMATION brake).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Literal

RiskTier = Literal["READ", "WRITE", "HIGH_RISK"]

READ_VERBS: frozenset[str] = frozenset(
    {
        "get",
        "list",
        "read",
        "query",
        "search",
        "view",
        "fetch",
        "describe",
        "show",
        "cat",
        "head",
        "tail",
        "grep",
        "find",
        "status",
        "check",
        "inspect",
        "diff",
        "export",
    }
)

WRITE_VERBS: frozenset[str] = frozenset(
    {
        "create",
        "update",
        "write",
        "edit",
        "modify",
        "patch",
        "import",
        "touch",
        "cp",
        "mv",
        "mkdir",
        "add",
        "insert",
        "save",
        "sync",
        "build",
        "compile",
        "install",
    }
)

HIGH_RISK_VERBS: frozenset[str] = frozenset(
    {
        "delete",
        "remove",
        "drop",
        "truncate",
        "destroy",
        "kill",
        "rm",
        "rmdir",
        "unlink",
        "format",
        "reset",
        "purge",
        "approve",
        "reject",
        "cancel",
        "terminate",
        "pay",
        "transfer",
        "revoke",
        "flush",
        "poweroff",
        "shutdown",
        "reboot",
    }
)

DANGEROUS_SHELL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\brm\s+-(?:r|f|rf|fr)\b", re.IGNORECASE),
    re.compile(r"\bdrop\s+(?:table|database|schema)\b", re.IGNORECASE),
    re.compile(r"\btruncate\s+table\b", re.IGNORECASE),
    re.compile(r"\bkill\s+-9\b", re.IGNORECASE),
    re.compile(r"\bgit\s+reset\s+--hard\b", re.IGNORECASE),
    re.compile(r"\bchmod\s+-R\s+777\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class TieredRiskEvaluation:
    """Evaluation output for tool execution risk level and brake requirement."""

    tier: RiskTier
    tool_name: str
    target_entity: str | None = None
    risk_reasons: tuple[str, ...] = field(default_factory=tuple)
    supports_dry_run: bool = False
    is_dry_run: bool = False
    need_confirmation: bool = False
    confirmation_token: str | None = None
    suggested_action: str = "allow"
    param_summary: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, str | bool | list[str] | dict[str, str] | None]:
        return {
            "tier": self.tier,
            "tool_name": self.tool_name,
            "target_entity": self.target_entity,
            "risk_reasons": list(self.risk_reasons),
            "supports_dry_run": self.supports_dry_run,
            "is_dry_run": self.is_dry_run,
            "need_confirmation": self.need_confirmation,
            "confirmation_token": self.confirmation_token,
            "suggested_action": self.suggested_action,
            "param_summary": self.param_summary,
        }


class TieredRiskEvaluator:
    """Classifies tool invocations into 3 tiers of risk with dynamic brake semantics."""

    @staticmethod
    def _extract_primary_verb(tool_name: str) -> str:
        clean = tool_name.lower().replace("-", "_").strip()
        parts = clean.split("_")
        return parts[0] if parts else clean

    @staticmethod
    def _extract_target_entity(args: dict[str, object]) -> str | None:
        for key in ("path", "target", "file", "target_file", "table", "url", "entity", "id", "name"):
            val = args.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        cmd = args.get("command") or args.get("cmd") or args.get("command_line") or args.get("CommandLine")
        if isinstance(cmd, str) and cmd.strip():
            return cmd.strip().split()[0]
        return None

    @staticmethod
    def _format_param_summary(args: dict[str, object]) -> dict[str, str]:
        summary: dict[str, str] = {}
        for k, v in args.items():
            if isinstance(v, (str, int, float, bool)):
                str_v = str(v)
                summary[k] = str_v[:100] + "..." if len(str_v) > 100 else str_v
            elif v is None:
                summary[k] = "null"
            else:
                summary[k] = f"<{type(v).__name__}>"
        return summary

    def evaluate(self, tool_name: str, args: dict[str, object] | None = None) -> TieredRiskEvaluation:
        safe_args = args or {}
        verb = self._extract_primary_verb(tool_name)
        target = self._extract_target_entity(safe_args)
        param_summary = self._format_param_summary(safe_args)
        is_dry_run = bool(safe_args.get("dry_run", False))

        reasons: list[str] = []

        # 1. Shell commands special deep inspect
        cmd = (
            safe_args.get("command")
            or safe_args.get("cmd")
            or safe_args.get("command_line")
            or safe_args.get("CommandLine")
        )
        if isinstance(cmd, str):
            for pat in DANGEROUS_SHELL_PATTERNS:
                if pat.search(cmd):
                    reasons.append(f"Dangerous command pattern matched: '{pat.pattern}'")
                    break

        # 2. Check High-Risk verbs
        if verb in HIGH_RISK_VERBS or any(
            f"_{v}_" in tool_name or tool_name.endswith(f"_{v}") for v in ("delete", "remove", "drop", "kill")
        ):
            reasons.append(f"Irreversible mutation operation: '{tool_name}' ({verb})")

        if reasons:
            token = f"tok_{uuid.uuid4().hex[:16]}"
            return TieredRiskEvaluation(
                tier="HIGH_RISK",
                tool_name=tool_name,
                target_entity=target,
                risk_reasons=tuple(reasons),
                supports_dry_run=True,
                is_dry_run=is_dry_run,
                need_confirmation=True,
                confirmation_token=token,
                suggested_action="NEED_CONFIRMATION",
                param_summary=param_summary,
            )

        # 3. Check Write verbs
        if verb in WRITE_VERBS or any(
            f"_{v}_" in tool_name or tool_name.endswith(f"_{v}") for v in ("create", "update", "write", "modify")
        ):
            return TieredRiskEvaluation(
                tier="WRITE",
                tool_name=tool_name,
                target_entity=target,
                risk_reasons=("State-mutating operation",),
                supports_dry_run=True,
                is_dry_run=is_dry_run,
                need_confirmation=False,
                suggested_action="review_summary" if not is_dry_run else "dry_run_simulated",
                param_summary=param_summary,
            )

        # 4. Default / Read verbs
        return TieredRiskEvaluation(
            tier="READ",
            tool_name=tool_name,
            target_entity=target,
            risk_reasons=(),
            supports_dry_run=False,
            is_dry_run=is_dry_run,
            need_confirmation=False,
            suggested_action="pass",
            param_summary=param_summary,
        )
