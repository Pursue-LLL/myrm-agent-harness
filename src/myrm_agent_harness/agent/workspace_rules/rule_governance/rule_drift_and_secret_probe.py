# [INPUT]: DriftAuditReport, DriftInspectionTarget, RuleGovernanceConfig, RuleSecretScanResult, ShadowedRuleFinding
# [OUTPUT]: RuleDriftAndSecretProbe
# [POS]: agent/workspace_rules/rule_governance/rule_drift_and_secret_probe.py

"""Probe auditing rule drift against workspace realities, secret leaks, and shadowed sibling files.

[INPUT]
- DriftAuditReport, DriftInspectionTarget: Output data structures capturing drift findings.
- RuleGovernanceConfig: Tunables governing scans.
- RuleSecretScanResult: Output model for credential scanning and redaction.
- ShadowedRuleFinding: Output model reporting eclipsed rule files in identical directories.

[OUTPUT]
- RuleDriftAndSecretProbe: Inspection engine detecting stale claims, secrets, and shadowed files.

[POS]
Active verification and security gate layer for persistent workspace rules.
"""

from __future__ import annotations

import os
import re
import time
from typing import Mapping, Sequence

from .governance_types import (
    DriftAuditReport,
    DriftInspectionTarget,
    RuleGovernanceConfig,
    RuleSecretScanResult,
    ShadowedRuleFinding,
)


class RuleDriftAndSecretProbe:
    """Audits rule integrity by checking stale references, redacting leaks, and uncovering eclipsed files."""

    _SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
        ("Anthropic_API_Key", re.compile(r"sk-ant-[a-zA-Z0-9_\-]{20,}", re.IGNORECASE)),
        ("OpenAI_API_Key", re.compile(r"sk-[a-zA-Z0-9_\-]{20,}", re.IGNORECASE)),
        ("GitHub_Token", re.compile(r"ghp_[a-zA-Z0-9]{36,}", re.IGNORECASE)),
        ("Bearer_Token", re.compile(r"Bearer\s+[a-zA-Z0-9_\-\.]{24,}", re.IGNORECASE)),
        ("Generic_Secret_Assignment", re.compile(r"(?:api_key|secret_key|private_key)\s*=\s*['\"][^'\"]{16,}['\"]", re.IGNORECASE)),
        ("Private_Key_Block", re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----", re.IGNORECASE)),
    )

    _COMMAND_PATTERN = re.compile(
        r"(?:运行|执行|使用|run|use|execute)\s*[`'\"]?((?:npm|bun|pnpm|yarn|poetry|pytest|cargo|go)\s+[\w\-]+)[`'\"]?",
        re.IGNORECASE,
    )

    _PATH_PATTERN = re.compile(
        r"(?:文件|目录|路径|path|file|dir)\s*[`'\"]?([\w\.\-/]+\.(?:py|ts|js|json|md|yaml|yml|toml))[`'\"]?",
        re.IGNORECASE,
    )

    def __init__(self, config: RuleGovernanceConfig | None = None) -> None:
        self._config = config or RuleGovernanceConfig()

    def sanitize_secrets_in_content(self, content: str) -> RuleSecretScanResult:
        """Detects and redacts credentials or private keys embedded in rule text before prompt injection."""
        if not self._config.enable_secret_redaction or not content:
            return RuleSecretScanResult(
                has_violation=False,
                redacted_content=content,
                detected_token_kinds=(),
                alert_banner=None,
            )

        redacted = content
        detected_kinds: list[str] = []

        for kind, pattern in self._SECRET_PATTERNS:
            matches = list(pattern.finditer(redacted))
            if matches:
                detected_kinds.append(kind)
                redacted = pattern.sub(f"[REDACTED_CREDENTIAL:{kind}]", redacted)

        has_violation = len(detected_kinds) > 0
        banner = None
        if has_violation:
            banner = (
                f"🚨 [载入域保密越界] 常驻规则中检测到敏感凭证 ({', '.join(detected_kinds)})，"
                f"已在注入上下文前自动脱敏，防止跨会话凭证泄露。"
            )

        return RuleSecretScanResult(
            has_violation=has_violation,
            redacted_content=redacted,
            detected_token_kinds=tuple(detected_kinds),
            alert_banner=banner,
        )

    def audit_rule_drift(
        self,
        rule_file_path: str,
        content: str,
        workspace_files: Sequence[str] | set[str],
        toolchain_manifest: Mapping[str, bool] | None = None,
    ) -> DriftAuditReport:
        """Cross-checks claimed commands and referenced paths in rule text against actual workspace state."""
        manifest = toolchain_manifest or {}
        existing_files_set = set(workspace_files)

        drift_items: list[DriftInspectionTarget] = []

        lines = content.splitlines()
        for line in lines[: self._config.max_drift_scan_items]:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            # Check claimed commands
            cmd_match = self._COMMAND_PATTERN.search(stripped)
            if cmd_match:
                cmd = cmd_match.group(1).strip()
                primary_tool = cmd.split()[0].lower()
                # If toolchain declared absent in workspace, flag drift
                if primary_tool in manifest and not manifest[primary_tool]:
                    drift_items.append(
                        DriftInspectionTarget(
                            rule_text=stripped,
                            claimed_command=cmd,
                            evidence_found=False,
                            drift_reason=f"Claimed tool '{primary_tool}' is not available or has been replaced in project.",
                        )
                    )

            # Check claimed file paths
            path_match = self._PATH_PATTERN.search(stripped)
            if path_match:
                claimed_path = path_match.group(1).strip()
                # If relative path is asserted but does not exist in workspace files
                if claimed_path not in existing_files_set and not any(f.endswith(claimed_path) for f in existing_files_set):
                    drift_items.append(
                        DriftInspectionTarget(
                            rule_text=stripped,
                            claimed_path=claimed_path,
                            evidence_found=False,
                            drift_reason=f"Referenced path '{claimed_path}' does not exist in active workspace.",
                        )
                    )

        return DriftAuditReport(
            scanned_files=(rule_file_path,),
            drift_count=len(drift_items),
            drift_items=tuple(drift_items),
            timestamp=time.time(),
        )

    def detect_shadowed_rules(
        self,
        directory_path: str,
        found_rule_files: Sequence[str],
        precedence_order: Sequence[str] = ("SOUL.md", "MEMORY.md", "AGENTS.md", "CLAUDE.md"),
    ) -> ShadowedRuleFinding | None:
        """Detects if lower-precedence rule files are being silently dropped in the same directory."""
        if not self._config.enable_shadow_audit or len(found_rule_files) <= 1:
            return None

        # Determine dominant rule file based on precedence
        dominant: str | None = None
        for candidate in precedence_order:
            if candidate in found_rule_files:
                dominant = candidate
                break

        if dominant is None:
            dominant = found_rule_files[0]

        shadowed = [f for f in found_rule_files if f != dominant]
        if not shadowed:
            return None

        notice = (
            f"⚠️ 检测到同目录下存在多规则文件遮蔽：已优先采用最高优先级《{dominant}》，"
            f"以下规则文件已被遮蔽未载入：{', '.join(shadowed)}。建议审视是否存在遗漏规范。"
        )

        return ShadowedRuleFinding(
            directory_path=directory_path,
            dominant_file=dominant,
            shadowed_files=tuple(shadowed),
            warning_notice=notice,
        )
