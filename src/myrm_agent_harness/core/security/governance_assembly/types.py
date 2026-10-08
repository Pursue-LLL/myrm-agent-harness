"""Types and models for Governance Assembly Path Assertion and Zero-Bypass Guard.

Enforces:
1. Multi-ingress governance verification (Chat, API, Subagent DAG, Cron).
2. Runtime zero-bypass signature validation (no naked callable execution).
3. Offline recording test harness without LLM cost.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

JsonScalar = str | int | float | bool | None


class IngressSource(StrEnum):
    """Source channel through which an Agent tool invocation was initiated."""

    INTERACTIVE_CHAT = "INTERACTIVE_CHAT"
    REST_API = "REST_API"
    SUBAGENT_DAG = "SUBAGENT_DAG"
    BACKGROUND_CRON = "BACKGROUND_CRON"


@dataclass(frozen=True)
class GovernanceWrapperSignature:
    """Cryptographic/Runtime signature proving a tool is wrapped by governance middlewares."""

    wrapper_id: str
    tool_name: str
    ingress_source: IngressSource
    applied_middlewares: tuple[str, ...]
    is_sealed: bool = True


@dataclass(frozen=True)
class ToolCallAssemblyTrace:
    """Trace recording the assembly and governance path of a tool call."""

    trace_id: str
    tool_name: str
    ingress_source: IngressSource
    call_stack_summary: str
    applied_middlewares: tuple[str, ...]
    is_governed: bool
    bypassed_guards: tuple[str, ...] = ()


@dataclass(frozen=True)
class GovernanceMatrixReport:
    """Audit report detailing multi-ingress governance assembly coverage."""

    total_invocations: int
    governed_invocations: int
    bypassed_invocations: int
    coverage_ratio: float
    is_fully_compliant: bool
    traces_by_ingress: dict[str, int]
    violations: tuple[str, ...] = ()


class GovernanceAssemblyError(Exception):
    """Base exception for governance assembly and zero-bypass domains."""


class UngovernedToolExecutionError(GovernanceAssemblyError):
    """Raised when an unshielded / naked tool invocation is detected attempting execution."""
