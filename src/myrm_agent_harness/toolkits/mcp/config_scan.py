"""MCP configuration and runtime surface security scanners.

[INPUT]
- myrm_agent_harness.core.security.detection.leak_detector::scan_for_leaks (POS: credential leak pattern detector)
- config_scan_patterns::INJECTION_PATTERN_SPECS (POS: compiled MCP security regex patterns)

[OUTPUT]
- MCPScanSeverity, MCPScanFinding, MCPConfigSnapshot, MCPConfigScanResult
- MCPRuntimeToolSurface, MCPRuntimeScanResult
- scan_mcp_config(), scan_mcp_runtime_surface(), format_mcp_scan_block_message()

[POS]
Static pre-flight and runtime-surface scanners for MCP integrations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from myrm_agent_harness.core.security.detection.leak_detector import scan_for_leaks

from .config_scan_patterns import (
    EXFILTRATION_URL_PATTERNS,
    INJECTION_PATTERN_SPECS,
    NAME_INJECTION_PATTERNS,
    NPX_AUTO_INSTALL,
    RISKY_SERVER_PATTERNS,
    SECRET_REF_PREFIX,
    SENSITIVE_PATH_PATTERN,
)


class MCPScanSeverity(StrEnum):
    """Severity for MCP configuration and runtime surface findings."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


_SEVERITY_ORDER: tuple[MCPScanSeverity, ...] = (
    MCPScanSeverity.INFO,
    MCPScanSeverity.LOW,
    MCPScanSeverity.MEDIUM,
    MCPScanSeverity.HIGH,
    MCPScanSeverity.CRITICAL,
)

_INJECTION_PATTERNS: tuple[tuple[re.Pattern[str], str, MCPScanSeverity, str], ...] = tuple(
    (pattern, threat_type, MCPScanSeverity(severity_label), recommendation)
    for pattern, threat_type, severity_label, recommendation in INJECTION_PATTERN_SPECS
)


@dataclass(frozen=True, slots=True)
class MCPScanFinding:
    """A single MCP security finding."""

    threat_type: str
    severity: MCPScanSeverity
    description: str
    field: str = ""
    recommendation: str = ""


@dataclass(frozen=True, slots=True)
class MCPConfigSnapshot:
    """Normalized MCP config for static scanning (framework DTO)."""

    name: str
    type: str
    url: str | None = None
    command: str | None = None
    args: tuple[str, ...] = ()
    description: str = ""
    headers: dict[str, str] | None = None
    extra_params: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class MCPConfigScanResult:
    """Static scan result for an MCP server configuration."""

    server_name: str
    findings: tuple[MCPScanFinding, ...] = ()

    @property
    def allow_save(self) -> bool:
        return not any(f.severity == MCPScanSeverity.CRITICAL for f in self.findings)

    @property
    def requires_acknowledgement(self) -> bool:
        return any(f.severity in (MCPScanSeverity.HIGH, MCPScanSeverity.CRITICAL) for f in self.findings)

    @property
    def max_severity(self) -> MCPScanSeverity | None:
        if not self.findings:
            return None
        return max(self.findings, key=lambda f: _SEVERITY_ORDER.index(f.severity)).severity


@dataclass(frozen=True, slots=True)
class MCPRuntimeToolSurface:
    """Tool metadata returned from MCP verify for runtime surface scanning."""

    name: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class MCPRuntimeScanResult:
    """Runtime surface scan for MCP instructions, tool names, and tool descriptions."""

    server_name: str
    findings: tuple[MCPScanFinding, ...] = ()

    @property
    def allow_use(self) -> bool:
        return not any(
            f.severity in (MCPScanSeverity.HIGH, MCPScanSeverity.CRITICAL) for f in self.findings
        )


def _is_secret_reference(value: str) -> bool:
    return SECRET_REF_PREFIX in value


def _extract_env_map(extra_params: dict[str, object] | None) -> dict[str, str]:
    if not extra_params:
        return {}
    raw_env = extra_params.get("env")
    if not isinstance(raw_env, dict):
        return {}
    return {str(key): str(val) for key, val in raw_env.items() if val is not None}


def _append_credential_findings(
    findings: list[MCPScanFinding],
    *,
    content: str,
    field: str,
    severity: MCPScanSeverity = MCPScanSeverity.CRITICAL,
) -> None:
    if not content or _is_secret_reference(content):
        return
    leaks = scan_for_leaks(content)
    for leak_name in leaks:
        findings.append(
            MCPScanFinding(
                threat_type="credential_exposure",
                severity=severity,
                description=f"Potential credential detected ({leak_name})",
                field=field,
                recommendation="Replace plaintext secrets with {{secret:KEY}} references",
            )
        )


def _scan_text_for_injection(
    text: str,
    *,
    field: str,
    label: str,
) -> list[MCPScanFinding]:
    if not text:
        return []
    out: list[MCPScanFinding] = []
    for pattern, threat_type, severity, recommendation in _INJECTION_PATTERNS:
        if pattern.search(text):
            out.append(
                MCPScanFinding(
                    threat_type=threat_type,
                    severity=severity,
                    description=f"Suspicious content in {label}",
                    field=field,
                    recommendation=recommendation,
                )
            )
    return out


def _scan_identifier_for_injection(
    identifier: str,
    *,
    field: str,
    label: str,
) -> list[MCPScanFinding]:
    if not identifier:
        return []
    for pattern in NAME_INJECTION_PATTERNS:
        if pattern.search(identifier):
            return [
                MCPScanFinding(
                    threat_type="name_injection",
                    severity=MCPScanSeverity.HIGH,
                    description=f"{label} contains injection-like content",
                    field=field,
                    recommendation="Use a short alphanumeric identifier without URLs or instructions",
                )
            ]
    return []


def _scan_name_for_injection(name: str) -> list[MCPScanFinding]:
    return _scan_identifier_for_injection(
        name,
        field="name",
        label="Server name",
    )


def _scan_arg_for_exfiltration(arg: str, field: str) -> list[MCPScanFinding]:
    findings: list[MCPScanFinding] = []
    for pattern, label in EXFILTRATION_URL_PATTERNS:
        if pattern.search(arg):
            findings.append(
                MCPScanFinding(
                    threat_type="suspicious_url",
                    severity=MCPScanSeverity.HIGH,
                    description=f"Suspicious exfiltration URL ({label}) in arguments",
                    field=field,
                    recommendation="Remove external callback URLs unless the endpoint is explicitly trusted",
                )
            )
    if SENSITIVE_PATH_PATTERN.search(arg):
        findings.append(
            MCPScanFinding(
                threat_type="sensitive_path",
                severity=MCPScanSeverity.MEDIUM,
                description="Argument references a sensitive filesystem path",
                field=field,
                recommendation="Restrict filesystem MCP to explicit non-sensitive directories",
            )
        )
    return findings


def scan_mcp_config(config: MCPConfigSnapshot) -> MCPConfigScanResult:
    """Static pre-flight scan for MCP server configuration."""
    findings: list[MCPScanFinding] = []

    findings.extend(_scan_name_for_injection(config.name))

    for pattern, severity_label, description, recommendation in RISKY_SERVER_PATTERNS:
        if pattern.search(config.name) or pattern.search(config.description):
            findings.append(
                MCPScanFinding(
                    threat_type="risky_mcp_profile",
                    severity=MCPScanSeverity(severity_label),
                    description=description,
                    field="name",
                    recommendation=recommendation,
                )
            )

    if config.url:
        _append_credential_findings(findings, content=config.url, field="url")
        findings.extend(_scan_text_for_injection(config.url, field="url", label="URL"))

    if config.command:
        _append_credential_findings(findings, content=config.command, field="command")

    for idx, arg in enumerate(config.args):
        field = f"args[{idx}]"
        _append_credential_findings(findings, content=arg, field=field)
        findings.extend(_scan_arg_for_exfiltration(arg, field))

    if config.command and NPX_AUTO_INSTALL.match(config.command.strip()):
        has_y_flag = any(arg.strip() in ("-y", "--yes") for arg in config.args)
        has_pinned_package = any(arg.strip() and not arg.startswith("-") for arg in config.args)
        if has_y_flag and not has_pinned_package:
            findings.append(
                MCPScanFinding(
                    threat_type="supply_chain",
                    severity=MCPScanSeverity.MEDIUM,
                    description="npx -y without a pinned package name increases supply-chain risk",
                    field="args",
                    recommendation="Pin the package name and version in args",
                )
            )

    if config.headers:
        for key, value in config.headers.items():
            _append_credential_findings(findings, content=value, field=f"headers.{key}")
            if value and not _is_secret_reference(value) and len(value) > 8:
                key_lower = key.lower()
                if any(token in key_lower for token in ("authorization", "api-key", "apikey", "token", "secret")):
                    findings.append(
                        MCPScanFinding(
                            threat_type="hardcoded_secret",
                            severity=MCPScanSeverity.CRITICAL,
                            description=f"Header '{key}' appears to contain a hardcoded secret; use {{{{secret:KEY}}}}",
                            field=f"headers.{key}",
                            recommendation="Move the secret to the vault and reference it with {{secret:KEY}}",
                        )
                    )

    for env_key, env_value in _extract_env_map(config.extra_params).items():
        _append_credential_findings(findings, content=env_value, field=f"extra_params.env.{env_key}")
        if env_value and not _is_secret_reference(env_value):
            key_lower = env_key.lower()
            if any(token in key_lower for token in ("key", "token", "secret", "password", "credential")):
                findings.append(
                    MCPScanFinding(
                        threat_type="hardcoded_secret",
                        severity=MCPScanSeverity.CRITICAL,
                        description=(
                            f"Environment variable '{env_key}' contains a plaintext value; "
                            "use {{{{secret:KEY}}}} in headers or required_secrets"
                        ),
                        field=f"extra_params.env.{env_key}",
                        recommendation="Store credentials in the vault and inject via {{secret:KEY}}",
                    )
                )

    findings.extend(
        _scan_text_for_injection(config.description, field="description", label="description")
    )

    return MCPConfigScanResult(server_name=config.name, findings=tuple(findings))


def scan_mcp_runtime_surface(
    server_name: str,
    *,
    instructions: str | None,
    tools: tuple[MCPRuntimeToolSurface, ...] = (),
) -> MCPRuntimeScanResult:
    """Scan MCP instructions, tool names, and tool descriptions for prompt injection."""
    findings: list[MCPScanFinding] = []
    if instructions:
        findings.extend(
            _scan_text_for_injection(instructions, field="instructions", label="server instructions")
        )
    for tool in tools:
        findings.extend(
            _scan_identifier_for_injection(
                tool.name,
                field=f"tools.{tool.name}.name",
                label=f"tool '{tool.name}' name",
            )
        )
        findings.extend(
            _scan_text_for_injection(
                tool.description,
                field=f"tools.{tool.name}.description",
                label=f"tool '{tool.name}' description",
            )
        )
    return MCPRuntimeScanResult(server_name=server_name, findings=tuple(findings))


def format_mcp_scan_block_message(result: MCPConfigScanResult | MCPRuntimeScanResult) -> str:
    """Human-readable summary for API error responses."""
    lines = [f"MCP security scan failed for '{result.server_name}':"]
    for finding in result.findings[:8]:
        lines.append(f"- [{finding.severity}] {finding.description} ({finding.field})")
    if len(result.findings) > 8:
        lines.append(f"- ... and {len(result.findings) - 8} more findings")
    return "\n".join(lines)
