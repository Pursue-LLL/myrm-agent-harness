"""Fault-side attribution — who owns a failure.

Deterministic, rule-based attribution that maps existing error classifications
(``ErrorKind`` from ``toolkits/llms/errors/classifier``, ``ToolErrorCategory``
from ``errors/tool_error_category``, and diagnostic ``error_type`` strings)
to a coarse fault side.  No LLM calls, no prompt tokens, no network — pure
string/enum mapping so GUI users can see at a glance whether to retry, switch
models, change input, or escalate.

[INPUT]
- toolkits.llms.errors::ErrorKind (POS: LLM error classification)
- errors.tool_error_category::ToolErrorCategory (POS: Tool error classification)

[OUTPUT]
- FaultSide: canonical fault-side enum (StrEnum, values match frontend i18n keys)
- classify_llm_fault_side: LLM ErrorKind → FaultSide
- classify_tool_fault_side: ToolErrorCategory → FaultSide
- classify_diagnostic_fault_side: diagnostic error_type string → FaultSide
- classify_fault_side: unified entry point (LLM error kind, tool error category, diagnostic type)

[POS]
Deterministic fault-side attribution.  Pure functions — no I/O, no side effects.
UNKNOWN is the explicit abstain value: when attribution is ambiguous we say
"we don't know" instead of guessing.
"""

from __future__ import annotations

from enum import StrEnum


class FaultSide(StrEnum):
    """Coarse attribution of a failure.

    Values are stable API tokens (not user-facing text); frontend maps them to
    localized human-readable labels.
    """

    MODEL = "model"  # The model provider or model output misbehaved (bad schema, refusal, hallucinated call)
    HARNESS_TOOL = "harness_tool"  # A built-in tool failed (file/bash/browser implementation issue)
    HARNESS_PIPELINE = "harness_pipeline"  # Agent pipeline/state machine issue (guard, budget, lifecycle)
    ENV = "env"  # Environment/provider/infra issue (network, rate limit, billing, TLS, outage)
    GRADER = "grader"  # Acceptance/evaluation failed (kanban verifier, drift judge)
    OWNER = "owner"  # User input / configuration issue (safety block, guardrail, bad request)
    UNKNOWN = "unknown"  # Abstain — cannot attribute deterministically


# ---------------------------------------------------------------------------
# LLM ErrorKind → FaultSide
# ---------------------------------------------------------------------------

# Errors that originate from the provider infrastructure / network layer.
_ENV_LLM_KINDS: frozenset[str] = frozenset(
    {
        "rate_limit",
        "overloaded",
        "timeout",
        "billing",
        "auth",
        "model_not_found",
    }
)

# Errors that indicate the model produced something unusable.
_MODEL_LLM_KINDS: frozenset[str] = frozenset(
    {
        "response_format_error",
        "format_error",
    }
)

# Errors that depend on context — attributed to the side that produced the
# triggering input (see disambiguation note on classify_llm_fault_side).
_OWNER_LLM_KINDS: frozenset[str] = frozenset(
    {
        "context_overflow",
        "safety_block",
    }
)


def classify_llm_fault_side(error_kind: str | None) -> FaultSide:
    """Map an LLM ``ErrorKind`` string to a fault side.

    Disambiguation notes:
    - ``context_overflow`` is attributed to OWNER: the conversation grew beyond
      the model window because of accumulated input, not a model defect.  Users
      can act on it (start a new chat / wait for compression), whereas a MODEL
      tag would imply "switch model" which does not fix an overflowing window.
    - ``safety_block`` is OWNER: the provider refused the *content* the user
      supplied.  Retrying or switching models cannot change the verdict.

    Returns UNKNOWN for ``None`` or unrecognized kinds (abstain).
    """
    if not error_kind:
        return FaultSide.UNKNOWN
    if error_kind in _ENV_LLM_KINDS:
        return FaultSide.ENV
    if error_kind in _MODEL_LLM_KINDS:
        return FaultSide.MODEL
    if error_kind in _OWNER_LLM_KINDS:
        return FaultSide.OWNER
    return FaultSide.UNKNOWN


# ---------------------------------------------------------------------------
# ToolErrorCategory → FaultSide
# ---------------------------------------------------------------------------

# Tool failures that are the tool's own fault (implementation, sandbox, execution).
_HARNESS_TOOL_CATEGORIES: frozenset[str] = frozenset(
    {
        "timeout",
        "oom",
        "not_found",
        "sandbox_ro",
        "network_blocked",
        "permission_denied",
        "syntax",
        "import",
        "unknown",
        "execution_failure",
        "oom_killed",
        "segfault",
        "signal_terminated",
        "nonzero_exit",
        "context_validation",
    }
)

# Tool failures that the user's input/config triggered.
_OWNER_TOOL_CATEGORIES: frozenset[str] = frozenset(
    {
        "hook_blocked",
        "estop",
        "loop_guard",
        "sandbox_boundary",
        "frequency_guard",
        "turn_budget_guard",
        "steering",
        "invalid_tool",
        "trust_attenuation",
        "pii_guard",
        "circuit_breaker",
        "post_hook_blocked",
        "tool_cancelled",
        "guardrail_blocked",
        "benchmark_blocked",
    }
)


def classify_tool_fault_side(error_category: str | None) -> FaultSide:
    """Map a ``ToolErrorCategory`` string to a fault side.

    Guard/guardrail categories (``guardrail_blocked``, ``pii_guard``, etc.) are
    OWNER: the request was blocked because of user content or configuration.
    Execution categories (``timeout``, ``oom``, ``syntax``...) are HARNESS_TOOL:
    the built-in tool itself failed to complete the requested operation.

    Returns UNKNOWN for ``None`` or unrecognized categories (abstain).
    """
    if not error_category:
        return FaultSide.UNKNOWN
    if error_category in _HARNESS_TOOL_CATEGORIES:
        return FaultSide.HARNESS_TOOL
    if error_category in _OWNER_TOOL_CATEGORIES:
        return FaultSide.OWNER
    return FaultSide.UNKNOWN


# ---------------------------------------------------------------------------
# Diagnostic error_type → FaultSide
# ---------------------------------------------------------------------------

# Diagnostic error types produced by LLMErrorDiagnostic (diagnostics/engine.py).
_ENV_DIAGNOSTIC_TYPES: frozenset[str] = frozenset(
    {
        "connection",
        "tls_certificate",
        "rate_limit",
        "billing",
        "api_key",
        "model",
        "timeout",
        "overloaded",
        "custom_endpoint_unreachable",
    }
)

_MODEL_DIAGNOSTIC_TYPES: frozenset[str] = frozenset(
    {
        "response_format",
        "format",
    }
)

_OWNER_DIAGNOSTIC_TYPES: frozenset[str] = frozenset(
    {
        "context_overflow",
        "safety_block",
        "guardrail",
    }
)


def classify_diagnostic_fault_side(error_type: str | None) -> FaultSide:
    """Map a diagnostic ``error_type`` string to a fault side.

    ``error_type`` comes from ``DiagnosticResult.error_type`` (e.g. ``"api_key"``,
    ``"connection"``, ``"response_format"``).  This is the diagnostic-level
    fallback when only the localized diagnostic is available (no ErrorKind).

    Returns UNKNOWN for ``None`` or unrecognized types (abstain).
    """
    if not error_type:
        return FaultSide.UNKNOWN
    if error_type in _ENV_DIAGNOSTIC_TYPES:
        return FaultSide.ENV
    if error_type in _MODEL_DIAGNOSTIC_TYPES:
        return FaultSide.MODEL
    if error_type in _OWNER_DIAGNOSTIC_TYPES:
        return FaultSide.OWNER
    return FaultSide.UNKNOWN


# ---------------------------------------------------------------------------
# Unified entry point
# ---------------------------------------------------------------------------


def classify_fault_side(
    *,
    error_kind: str | None = None,
    error_category: str | None = None,
    error_type: str | None = None,
) -> FaultSide:
    """Unified deterministic fault-side attribution.

    Priority: ``error_kind`` (LLM classification, most specific) →
    ``error_category`` (tool classification) → ``error_type`` (diagnostic
    fallback).  Only the first non-UNKNOWN result is returned; if every input
    is absent or unrecognized the result is ``FaultSide.UNKNOWN`` (abstain).

    This function is safe to call from any layer — it performs no I/O.
    """
    for value, classifier in (
        (error_kind, classify_llm_fault_side),
        (error_category, classify_tool_fault_side),
        (error_type, classify_diagnostic_fault_side),
    ):
        side = classifier(value)
        if side is not FaultSide.UNKNOWN:
            return side
    return FaultSide.UNKNOWN


__all__ = [
    "FaultSide",
    "classify_diagnostic_fault_side",
    "classify_fault_side",
    "classify_llm_fault_side",
    "classify_tool_fault_side",
]
