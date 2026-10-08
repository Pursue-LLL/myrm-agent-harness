"""Egress Security Policy Validator and Codebase Telemetry Scraper.

[INPUT]
- Egress rules, dependency manifests, or project directory paths.

[OUTPUT]
- DLPScanResult detailing safety verdict, matched signatures, and audit explanations.

[POS]
- Harness core security validator enforcing enterprise DLP and telemetry egress barriers.
"""

from __future__ import annotations

import re
from pathlib import Path

from myrm_agent_harness.core.security.egress_dlp.signatures import (
    TelemetrySignatureRegistry,
)
from myrm_agent_harness.core.security.egress_dlp.types import (
    DLPScanResult,
    DLPScanViolationError,
    DLPVerdict,
    EgressRule,
    TelemetryEgressBlockedError,
    TelemetrySignature,
)

_SPLIT_PKG_REGEX = re.compile(r"^[a-zA-Z0-9_\-\[\]]+")


class EgressSecurityPolicyValidator:
    """Enterprise Data Loss Prevention validator inspecting network egress rules and dependencies."""

    def __init__(self, registry: type[TelemetrySignatureRegistry] = TelemetrySignatureRegistry) -> None:
        self._registry = registry

    def validate_egress_rules(
        self,
        rules: list[EgressRule],
        allowed_exceptions: set[str] | None = None,
    ) -> DLPScanResult:
        """Inspect outbound network egress rules against telemetry signatures and evasion patterns."""
        exceptions = allowed_exceptions or set()
        matched_signatures: list[TelemetrySignature] = []
        offending_rules: list[EgressRule] = []

        for rule in rules:
            host, evasion_verdict = self._registry.normalize_host(rule.destination)
            if evasion_verdict:
                return DLPScanResult(
                    is_safe=False,
                    verdict=evasion_verdict,
                    offending_rules=(rule,),
                    audit_trail=f"Rejected rule destination '{rule.destination}' due to evasion attempt: {evasion_verdict.value}",
                )

            if host in exceptions:
                continue

            sig = self._registry.match_host(host)
            if sig:
                matched_signatures.append(sig)
                offending_rules.append(rule)

        if offending_rules:
            first_sig = matched_signatures[0]
            first_rule = offending_rules[0]
            return DLPScanResult(
                is_safe=False,
                verdict=DLPVerdict.BLOCKED_TELEMETRY_DOMAIN,
                detected_signatures=tuple(matched_signatures),
                offending_rules=tuple(offending_rules),
                audit_trail=(
                    f"Blocked egress destination '{first_rule.destination}' matching {first_sig.framework_name} "
                    f"telemetry domain '{first_sig.target_domain}' (Risk: {first_sig.risk_level.value})."
                ),
            )

        return DLPScanResult(
            is_safe=True,
            verdict=DLPVerdict.ALLOWED,
            audit_trail="All egress policy destinations passed enterprise DLP validation.",
        )

    def scan_dependencies(self, manifest_content: str) -> DLPScanResult:
        """Scan dependency file contents (requirements.txt, etc.) for telemetry SDK libraries."""
        detected_pkgs: list[str] = []

        for line in manifest_content.splitlines():
            cleaned = line.strip()
            if not cleaned or cleaned.startswith("#"):
                continue

            # Extract base package name
            match = _SPLIT_PKG_REGEX.match(cleaned)
            if match:
                raw_pkg = match.group(0)
                if self._registry.match_package(raw_pkg):
                    detected_pkgs.append(raw_pkg)

        if detected_pkgs:
            return DLPScanResult(
                is_safe=False,
                verdict=DLPVerdict.BLOCKED_TELEMETRY_DEPENDENCY,
                detected_dependencies=tuple(detected_pkgs),
                audit_trail=f"Detected telemetry tracking dependencies in manifest: {', '.join(detected_pkgs)}.",
            )

        return DLPScanResult(
            is_safe=True,
            verdict=DLPVerdict.ALLOWED,
            audit_trail="Dependency manifest contains no prohibited telemetry SDKs.",
        )

    def scan_codebase_telemetry(self, project_dir: str | Path) -> DLPScanResult:
        """Scan project files for telemetry dependency inclusions and hardcoded telemetry endpoints."""
        p = Path(project_dir)
        if not p.is_dir():
            return DLPScanResult(
                is_safe=True,
                verdict=DLPVerdict.ALLOWED,
                audit_trail=f"Project directory '{project_dir}' does not exist or is not a directory.",
            )

        # 1. Scan requirements.txt if present
        req_file = p / "requirements.txt"
        if req_file.is_file():
            dep_res = self.scan_dependencies(req_file.read_text(encoding="utf-8"))
            if not dep_res.is_safe:
                return dep_res

        # 2. Scan core python files for telemetry domains
        candidate_files = list(p.glob("*.py"))[:20]  # Cap search to immediate relevant files
        signatures = self._registry.list_signatures()

        for f in candidate_files:
            try:
                content = f.read_text(encoding="utf-8").lower()
                for sig in signatures:
                    if sig.target_domain in content:
                        return DLPScanResult(
                            is_safe=False,
                            verdict=DLPVerdict.BLOCKED_TELEMETRY_DOMAIN,
                            detected_signatures=(sig,),
                            audit_trail=f"File '{f.name}' references telemetry endpoint '{sig.target_domain}'.",
                        )
            except Exception:
                pass

        return DLPScanResult(
            is_safe=True,
            verdict=DLPVerdict.ALLOWED,
            audit_trail="Static codebase scan found no known telemetry endpoints or libraries.",
        )

    def assert_compliant(
        self,
        rules: list[EgressRule],
        allowed_exceptions: set[str] | None = None,
        project_dir: str | Path | None = None,
    ) -> DLPScanResult:
        """Evaluate egress rules and codebase, raising an exception if DLP policies are violated."""
        rule_res = self.validate_egress_rules(rules=rules, allowed_exceptions=allowed_exceptions)
        if not rule_res.is_safe:
            if rule_res.verdict == DLPVerdict.BLOCKED_TELEMETRY_DOMAIN:
                raise TelemetryEgressBlockedError(rule_res.audit_trail)
            raise DLPScanViolationError(rule_res.audit_trail)

        if project_dir:
            dir_res = self.scan_codebase_telemetry(project_dir=project_dir)
            if not dir_res.is_safe:
                raise DLPScanViolationError(dir_res.audit_trail)

        return rule_res
