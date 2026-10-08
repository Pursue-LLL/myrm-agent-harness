"""Real-time Sandbox Health and Container Escape Prevention Self-Audit Probe."""

from __future__ import annotations

import re
import uuid

from .types import (
    IsolationLevel,
    ProbeCategory,
    ProbeCheckItem,
    ProbeCheckStatus,
    SandboxHealthAuditReport,
)

_CRITICAL_HOST_PATHS: frozenset[str] = frozenset({
    "/etc/shadow",
    "/root",
    "/var/run/docker.sock",
    "~/.ssh",
    "~/.aws",
})

_SENSITIVE_ENV_KEYS: frozenset[str] = frozenset({
    "AWS_SECRET_ACCESS_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "STRIPE_SECRET_KEY",
    "DATABASE_URL",
})


class SandboxHealthSelfAuditProbe:
    """Probes the sandbox runtime environment for containment integrity and escape vulnerabilities."""

    def run_audit(
        self,
        environment_id: str,
        isolation_level: IsolationLevel,
        mounted_paths: list[str] | None = None,
        env_vars: dict[str, str] | None = None,
        is_root: bool = False,
        egress_monitored: bool = True,
    ) -> SandboxHealthAuditReport:
        """Execute diagnostic checks across filesystem, environment, network, and capabilities."""
        checks: list[ProbeCheckItem] = []
        score = 100

        # 1. Filesystem Mount Diagnostic (FS_01)
        mounts = mounted_paths or []
        leaked_mounts: list[str] = []
        for path in mounts:
            normalized = path.strip()
            if any(crit in normalized for crit in _CRITICAL_HOST_PATHS):
                leaked_mounts.append(normalized)

        if leaked_mounts:
            checks.append(
                ProbeCheckItem(
                    check_id="FS_01",
                    category=ProbeCategory.FILESYSTEM,
                    description="Host root and sensitive credential directory mount containment",
                    status=ProbeCheckStatus.FAIL,
                    details=f"Critical host paths exposed inside sandbox: {', '.join(leaked_mounts)}",
                )
            )
            score -= 40
        else:
            checks.append(
                ProbeCheckItem(
                    check_id="FS_01",
                    category=ProbeCategory.FILESYSTEM,
                    description="Host root and sensitive credential directory mount containment",
                    status=ProbeCheckStatus.PASS,
                    details="Filesystem boundary isolated: no critical host paths mounted read-write",
                )
            )

        # 2. Environment Variable Sanitization Diagnostic (ENV_01)
        environ = env_vars or {}
        exposed_keys: list[str] = []
        for k in environ:
            upper_k = k.upper()
            if upper_k in _SENSITIVE_ENV_KEYS or re.search(r"(?:SECRET|API_KEY|PASSWORD|TOKEN)", upper_k):
                exposed_keys.append(k)

        if exposed_keys:
            checks.append(
                ProbeCheckItem(
                    check_id="ENV_01",
                    category=ProbeCategory.ENVIRONMENT,
                    description="Host master API keys and raw credential env sanitization",
                    status=ProbeCheckStatus.FAIL if len(exposed_keys) > 1 else ProbeCheckStatus.WARNING,
                    details=f"Unsanitized sensitive environment variables found: {', '.join(exposed_keys)}",
                )
            )
            score -= 25 if len(exposed_keys) > 1 else 15
        else:
            checks.append(
                ProbeCheckItem(
                    check_id="ENV_01",
                    category=ProbeCategory.ENVIRONMENT,
                    description="Host master API keys and raw credential env sanitization",
                    status=ProbeCheckStatus.PASS,
                    details="Environment sanitized: zero master credentials or private keys resident",
                )
            )

        # 3. Network Outbound Sentinel Watchdog Diagnostic (NET_01)
        if not egress_monitored:
            checks.append(
                ProbeCheckItem(
                    check_id="NET_01",
                    category=ProbeCategory.NETWORK,
                    description="Pre-outbound Sentinel egress review watchdog connection",
                    status=ProbeCheckStatus.FAIL,
                    details="Unrestricted network egress: Sentinel watchdog is NOT active",
                )
            )
            score -= 30
        else:
            checks.append(
                ProbeCheckItem(
                    check_id="NET_01",
                    category=ProbeCategory.NETWORK,
                    description="Pre-outbound Sentinel egress review watchdog connection",
                    status=ProbeCheckStatus.PASS,
                    details="Egress secured: Sentinel review proxy actively screening outbound calls",
                )
            )

        # 4. Privilege & Capabilities Containment (CAP_01)
        if is_root and isolation_level == IsolationLevel.HOST_DIRECT_FULL_TRUST:
            checks.append(
                ProbeCheckItem(
                    check_id="CAP_01",
                    category=ProbeCategory.CAPABILITIES,
                    description="Unprivileged execution and container escape capability bounds",
                    status=ProbeCheckStatus.WARNING,
                    details="Host-direct mode running as root without container sandbox isolation",
                )
            )
            score -= 20
        else:
            checks.append(
                ProbeCheckItem(
                    check_id="CAP_01",
                    category=ProbeCategory.CAPABILITIES,
                    description="Unprivileged execution and container escape capability bounds",
                    status=ProbeCheckStatus.PASS,
                    details="Privilege containment satisfied: unprivileged execution or strict VM namespace",
                )
            )

        final_score = max(0, min(100, score))
        passed = all(c.status != ProbeCheckStatus.FAIL for c in checks)
        report_id = f"audit_rep_{uuid.uuid4().hex[:12]}"

        return SandboxHealthAuditReport(
            report_id=report_id,
            environment_id=environment_id,
            isolation_level=isolation_level,
            checks=checks,
            passed=passed,
            score=final_score,
        )
