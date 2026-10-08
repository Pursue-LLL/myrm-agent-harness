"""Data types and schemas for Enterprise Zero-Credential Proxy and Super-CLI Suite."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class AuthHeaderScheme(StrEnum):
    """Authentication header scheme for outbound proxy injection."""

    BEARER = "bearer"
    BASIC = "basic"
    CUSTOM = "custom"


@dataclass(frozen=True)
class ProxyInjectionRule:
    """Outbound proxy injection rule mapping a sandbox placeholder to real credentials."""

    rule_id: str
    target_domain: str
    real_token: str
    header_name: str = "Authorization"
    scheme: AuthHeaderScheme = AuthHeaderScheme.BEARER
    custom_header_prefix: str = ""
    description: str = ""


@dataclass(frozen=True)
class OutboundProxyRequest:
    """Request initiated from sandbox with connector placeholders."""

    url: str
    method: str
    headers: Mapping[str, str] = field(default_factory=dict)
    body: str = ""
    connector_ref: str | None = None


@dataclass(frozen=True)
class OutboundProxyResponse:
    """Response returned through the zero-credential outbound proxy."""

    status_code: int
    headers: Mapping[str, str]
    body: str
    credential_injected: bool
    matched_rule_id: str | None
    redacted_count: int
    transparency_notice: str | None
    blocked_reason: str | None = None


@dataclass(frozen=True)
class RedactionResult:
    """Result of running plaintext redaction with transparency notice."""

    sanitized_text: str
    redacted_count: int
    transparency_notice: str | None
    matched_patterns: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SuperCliCommandSpec:
    """Command specification executed via the Super-CLI wrapper."""

    target_cli: str
    args: list[str] = field(default_factory=list)
    injected_env: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: float = 30.0


@dataclass(frozen=True)
class SuperCliExecutionResult:
    """Execution result of Super-CLI with output streams sanitized."""

    exit_code: int
    stdout: str
    stderr: str
    redacted_count: int
    transparency_notice: str | None
