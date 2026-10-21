"""Surge/Clash self-healing rule generator and transparent HTTP bypass engine.

Provides automated in-app bypass configurations and operator-facing rule snippets
for Surge, Clash, Clash Verge, and generic proxies to eliminate loopback deadlocks.

[OUTPUT]
- SurgeClashSelfHealer: Generates client transport kwargs and proxy bypass directives.

[INPUT]
- __future__

[OUTPUT]
- SurgeClashSelfHealer

[POS]
Surge/Clash self-healing rule generator and transparent HTTP bypass engine.
"""

from __future__ import annotations

from myrm_agent_harness.core.network.loopback_types import (
    HealthStatus,
    LoopbackProbeResult,
    ProxyRemediationRule,
    ProxySoftwareKind,
)


class SurgeClashSelfHealer:
    """Provides automated bypass rules and client kwargs to self-heal loopback routing."""

    @staticmethod
    def generate_bypass_rule(software: ProxySoftwareKind) -> ProxyRemediationRule:
        """Produce the canonical, copy-pasteable bypass rule for the chosen proxy software."""
        if software == ProxySoftwareKind.SURGE:
            return ProxyRemediationRule(
                software=ProxySoftwareKind.SURGE,
                rule_directive="IP-CIDR,127.0.0.0/8,DIRECT,no-resolve",
                target_config_section="[Rule]",
                human_explanation=(
                    "Add this directive near the top of the [Rule] section in your Surge configuration "
                    "to prevent Surge from intercepting 127.0.0.1 loopback daemon traffic."
                ),
            )

        if software in (ProxySoftwareKind.CLASH, ProxySoftwareKind.CLASH_VERGE):
            return ProxyRemediationRule(
                software=software,
                rule_directive="- IP-CIDR,127.0.0.0/8,DIRECT,no-resolve",
                target_config_section="rules:",
                human_explanation=(
                    "Add this rule at the beginning of the 'rules:' array in your Clash/Clash Verge "
                    "profile to directly route all local 127.0.0.0/8 traffic without DNS resolution."
                ),
            )

        return ProxyRemediationRule(
            software=ProxySoftwareKind.GENERIC,
            rule_directive='export NO_PROXY="127.0.0.1,localhost,::1,127.0.0.0/8,*.local"',
            target_config_section="~/.bashrc or ~/.zshrc",
            human_explanation=(
                "Export NO_PROXY in your user shell environment so HTTP clients do not forward "
                "local daemon requests to the upstream proxy."
            ),
        )

    @staticmethod
    def build_direct_client_kwargs() -> dict[str, bool]:
        """Return HTTP client kwargs (e.g. for httpx.AsyncClient) enforcing direct connection.

        Disabling `trust_env` instructs httpx to ignore system-wide HTTP_PROXY/ALL_PROXY
        environment variables, guaranteeing direct socket establishment for loopback endpoints.
        """
        return {"trust_env": False}

    @classmethod
    def synthesize_diagnostic_card(
        cls,
        probe: LoopbackProbeResult,
        software: ProxySoftwareKind = ProxySoftwareKind.SURGE,
    ) -> str:
        """Render a user-facing diagnostic alert card with copy-pasteable remediation."""
        rule = cls.generate_bypass_rule(software)
        lines: list[str] = [
            f"### 🛡️ Local Loopback Proxy Conflict Detected ({probe.target_host}:{probe.target_port})",
            "",
        ]

        if probe.status == HealthStatus.INTERCEPTED:
            lines.extend(
                [
                    "> [!WARNING]",
                    f"> Inbound requests to local endpoint `{probe.target_host}:{probe.target_port}` "
                    "are being intercepted or dropped by a system-wide proxy.",
                    "> This causes connection refused errors or infinite request timeouts.",
                    "",
                    f"**Suggested Fix for {software.value.upper()}**:",
                    f"1. Open your `{rule.target_config_section}` configuration section.",
                    "2. Add the following rule directive at the top:",
                    "```text",
                    rule.rule_directive,
                    "```",
                    f"*{rule.human_explanation}*",
                ]
            )
        else:
            lines.extend(
                [
                    "> [!NOTE]",
                    f"> Endpoint `{probe.target_host}:{probe.target_port}` is {probe.status.value} "
                    f"(latency: {probe.latency_ms:.1f}ms).",
                ]
            )

        return "\n".join(lines)
