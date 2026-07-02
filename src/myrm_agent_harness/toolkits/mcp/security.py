"""MCP security validators — URL SSRF protection, response size enforcement, and OSV malware check.

Provides reusable security primitives for MCP integrations:
- MCPURLValidator: URL validation with SSRF prevention and optional HTTPS enforcement
- MCPResponseValidator: Response size and structure validation
- check_osv_malware: OSV API check for MAL-* malware advisories on npm/PyPI packages

All validators are stateless and deployment-mode agnostic. Behavior is controlled
via constructor parameters, not environment checks.

[INPUT]
- myrm_agent_harness.core.security.guards.ssrf::async_validate_url_for_ssrf (POS: SSRF validation with DNS pinning)
- myrm_agent_harness.utils.url_utils::validate_scheme_and_hostname (POS: URL scheme validation)

[OUTPUT]
- URLValidationError: URL validation failure
- ResolvedURL: DNS-pinned URL info for audit logging
- MCPURLValidator: URL security validator (SSRF + optional HTTPS)
- MCPResponseError: Response validation failure
- MCPResponseValidator: Response size and structure validator
- check_osv_malware: OSV MAL-* malware advisory check
- Re-exports from config_scan (POS: static MCP configuration/runtime scanners)
- config_scan_patterns (POS: compiled MCP security regex patterns, used by config_scan)

[POS]
MCP security primitives. Framework-level validators that any MCP integration
can use. Static scan APIs live in config_scan.py (patterns in config_scan_patterns.py)
and are re-exported here.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from myrm_agent_harness.infra.tls_compat import create_httpx_client

from myrm_agent_harness.toolkits.mcp.config_scan import (
    MCPConfigScanResult,
    MCPConfigSnapshot,
    MCPRuntimeScanResult,
    MCPRuntimeToolSurface,
    MCPScanFinding,
    MCPScanSeverity,
    format_mcp_scan_block_message,
    scan_mcp_config,
    scan_mcp_runtime_surface,
)
from myrm_agent_harness.core.security.guards.ssrf import (
    async_validate_url_for_ssrf,
)
from myrm_agent_harness.utils.url_utils import validate_scheme_and_hostname

logger = logging.getLogger(__name__)


class URLValidationError(Exception):
    """URL validation failed."""

    def __init__(self, message: str, url: str, reason: str) -> None:
        self.message = message
        self.url = url
        self.reason = reason
        super().__init__(f"{message}: {reason}")


class ResolvedURL(BaseModel):
    """DNS-resolved URL info for audit logging.

    ``resolved_ips`` are the pinned IPs verified safe by the SSRF check.
    Callers SHOULD use these IPs for the actual HTTP connection to prevent
    DNS rebinding attacks.
    """

    url: str = Field(..., description="Original URL")
    hostname: str = Field(..., description="Hostname")
    resolved_ips: list[str] = Field(..., description="Resolved IP addresses (pinned)")
    resolved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ttl: int = Field(default=300, description="DNS TTL (seconds)")


class MCPURLValidator:
    """MCP URL security validator.

    Delegates core SSRF checks (IP blocklists, hostname blocklists, DNS pinning)
    to ``core.security.guards.ssrf.async_validate_url_for_ssrf()``, and optionally enforces HTTPS.

    Args:
        require_https: Enforce HTTPS scheme. Defaults to False (local MCP servers
            typically use stdio or localhost:port without TLS).

    Example::

        validator = MCPURLValidator(require_https=True)
        result = await validator.validate_url("https://api.example.com/mcp")
        print(result.resolved_ips)  # pinned safe IPs
    """

    def __init__(self, *, require_https: bool = False) -> None:
        self.require_https = require_https

    async def validate_url(self, url: str) -> ResolvedURL:
        """Validate an MCP server URL for security.

        Args:
            url: URL to validate.

        Returns:
            ResolvedURL with pinned audit info.

        Raises:
            URLValidationError: If validation fails.
        """
        hostname, error = validate_scheme_and_hostname(url)
        if hostname is None:
            raise URLValidationError("URL validation failed", url, error)

        parsed = urlparse(url)
        if self.require_https and parsed.scheme != "https":
            raise URLValidationError("HTTPS required", url, "Only HTTPS is allowed when require_https is enabled")

        result = await async_validate_url_for_ssrf(url)
        if not result.safe:
            raise URLValidationError("SSRF check failed", url, result.error)

        return ResolvedURL(
            url=url,
            hostname=result.hostname,
            resolved_ips=list(result.resolved_ips),
        )


class MCPResponseError(Exception):
    """MCP response validation failed."""

    def __init__(self, message: str, reason: str) -> None:
        self.message = message
        self.reason = reason
        super().__init__(f"{message}: {reason}")


class MCPResponseValidator:
    """MCP response size and structure validator.

    Prevents resource exhaustion from malicious or misconfigured MCP servers
    by enforcing limits on response size and tool count.

    Args:
        max_response_size: Maximum allowed response size in bytes.
        enabled: Whether validation is active. Defaults to True.

    Example::

        validator = MCPResponseValidator(max_response_size=10 * 1024 * 1024)
        validator.validate_tools_response(tools_list)
    """

    MAX_TOOLS_COUNT = 1000
    ESTIMATED_BYTES_PER_TOOL = 2048

    def __init__(self, max_response_size: int, *, enabled: bool = True) -> None:
        self.max_response_size = max_response_size
        self._enabled = enabled

    def validate_tools_response(self, tools: list[object]) -> None:
        """Validate a tools list response from an MCP server.

        Args:
            tools: List of tool definitions.

        Raises:
            MCPResponseError: If the response exceeds safety limits.
        """
        if not self._enabled:
            return

        if len(tools) > self.MAX_TOOLS_COUNT:
            raise MCPResponseError(
                "Response validation failed",
                f"Too many tools: {len(tools)} (max: {self.MAX_TOOLS_COUNT})",
            )

        estimated_size = len(tools) * self.ESTIMATED_BYTES_PER_TOOL
        if estimated_size > self.max_response_size:
            raise MCPResponseError(
                "Response validation failed",
                f"Estimated response size {estimated_size / 1024 / 1024:.1f}MB "
                f"exceeds limit {self.max_response_size / 1024 / 1024:.1f}MB",
            )

        logger.debug("MCP response validated: %d tools (~%.1fKB)", len(tools), estimated_size / 1024)

    def validate_instructions_response(self, instructions: str | None) -> None:
        """Validate an instructions response from an MCP server.

        Args:
            instructions: Instructions text (may be None).

        Raises:
            MCPResponseError: If the instructions exceed the size limit.
        """
        if not self._enabled or instructions is None:
            return

        size = len(instructions.encode("utf-8"))
        if size > self.max_response_size:
            raise MCPResponseError(
                "Response validation failed",
                f"Instructions size {size / 1024:.1f}KB exceeds limit {self.max_response_size / 1024 / 1024:.1f}MB",
            )

        logger.debug("MCP instructions validated: %.1fKB", size / 1024)


# ---------------------------------------------------------------------------
# OSV Malware Advisory Check
# ---------------------------------------------------------------------------

_OSV_QUERY_URL = "https://api.osv.dev/v1/query"
_OSV_TIMEOUT_SECONDS = 10

_OSV_ECOSYSTEM_MAP: dict[str, str] = {
    "npx": "npm",
    "npm": "npm",
    "yarn": "npm",
    "pnpm": "npm",
    "uvx": "PyPI",
    "pipx": "PyPI",
    "pip": "PyPI",
    "python": "PyPI",
    "python3": "PyPI",
}


def _extract_package_info(
    command: str,
    args: list[str] | None,
) -> tuple[str, str] | None:
    """Extract package name and ecosystem from MCP command and args.

    Returns (package_name, ecosystem) or None if extraction fails.
    """
    cmd_lower = command.strip().lower()
    cmd_base = cmd_lower.rsplit("/", 1)[-1]

    ecosystem = _OSV_ECOSYSTEM_MAP.get(cmd_base)
    if ecosystem is None:
        return None

    for arg in args or []:
        stripped = arg.strip()
        if not stripped or stripped.startswith("-"):
            continue
        if ecosystem == "npm" and stripped.startswith("@"):
            scope_end = stripped.find("/", 1)
            if scope_end > 1:
                return stripped[: scope_end + 1], ecosystem
            return stripped, ecosystem
        return stripped, ecosystem

    return None


async def check_osv_malware(
    command: str,
    args: list[str] | None,
) -> str | None:
    """Check if an MCP package has MAL-* malware advisories via OSV API.

    Fail-open: returns None on network errors or extraction failures.
    Returns advisory summary string if malware is found.
    """
    info = _extract_package_info(command, args)
    if info is None:
        return None

    package_name, ecosystem = info

    try:
        async with create_httpx_client(timeout=_OSV_TIMEOUT_SECONDS) as client:
            response = await client.post(
                _OSV_QUERY_URL,
                json={"package": {"name": package_name, "ecosystem": ecosystem}},
            )
            response.raise_for_status()
            data = response.json()

        for vuln in data.get("vulns", []):
            vuln_id = vuln.get("id", "")
            if vuln_id.startswith("MAL-"):
                summary = vuln.get("summary", "malware advisory")
                return f"{vuln_id}: {summary} (package: {package_name})"

        return None

    except Exception as exc:
        logger.debug("OSV check skipped for %s/%s: %s", ecosystem, package_name, exc)
        return None


__all__ = [
    "MCPConfigScanResult",
    "MCPConfigSnapshot",
    "MCPResponseError",
    "MCPResponseValidator",
    "MCPRuntimeScanResult",
    "MCPRuntimeToolSurface",
    "MCPScanFinding",
    "MCPScanSeverity",
    "MCPURLValidator",
    "ResolvedURL",
    "URLValidationError",
    "check_osv_malware",
    "format_mcp_scan_block_message",
    "scan_mcp_config",
    "scan_mcp_runtime_surface",
]
