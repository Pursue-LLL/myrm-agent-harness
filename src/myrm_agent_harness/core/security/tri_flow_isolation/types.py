"""Type definitions for Agentic Transaction Safety and Tri-Flow Isolation Suite."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

WorkflowRole = Literal["read_only", "buyer", "seller"]


@dataclass(slots=True, frozen=True)
class ToolRoleContract:
    """Declares the workflow role and financial constraints for a specific tool."""

    tool_name: str
    allowed_roles: tuple[WorkflowRole, ...]
    is_financial_transaction: bool = False
    requires_hitl_confirmation: bool = False
    financial_threshold: float = 0.0


@dataclass(slots=True, frozen=True)
class DocumentedEndpointSpec:
    """Documented API endpoint or contract method whitelist spec."""

    service: str
    path: str
    method: str = "GET"
    allowed_methods: tuple[str, ...] = ("GET",)
    contract_functions: tuple[str, ...] = field(default_factory=tuple)


@dataclass(slots=True, frozen=True)
class TriFlowValidationResult:
    """Evaluation result of an attempted tool execution within a workflow role."""

    is_allowed: bool
    current_role: WorkflowRole
    tool_name: str
    reason: str
    requires_hitl: bool = False


@dataclass(slots=True, frozen=True)
class EndpointValidationResult:
    """Evaluation result of an outgoing API, RPC, or contract call."""

    is_allowed: bool
    service: str
    endpoint: str
    method: str
    reason: str


@dataclass(slots=True, frozen=True)
class ZeroPrintSanitizationResult:
    """Result of scanning and redacting sensitive private keys and credentials."""

    sanitized_text: str
    redactions_count: int
    detected_types: tuple[str, ...]
