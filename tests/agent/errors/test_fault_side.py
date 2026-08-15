"""Tests for fault_side attribution module."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.errors.diagnostics.i18n.constants import REQUIRED_ERROR_TYPES
from myrm_agent_harness.agent.errors.fault_side import (
    FaultSide,
    classify_diagnostic_fault_side,
    classify_fault_side,
    classify_llm_fault_side,
    classify_tool_fault_side,
)
from myrm_agent_harness.agent.errors.tool_error_category import ToolErrorCategory
from myrm_agent_harness.toolkits.llms.errors.classifier import ErrorKind


class TestClassifyLlmFaultSide:
    @pytest.mark.parametrize(
        "error_kind",
        ["rate_limit", "overloaded", "timeout", "billing", "auth", "model_not_found"],
    )
    def test_env_kinds(self, error_kind: str) -> None:
        assert classify_llm_fault_side(error_kind) is FaultSide.ENV

    @pytest.mark.parametrize(
        "error_kind",
        ["response_format_error", "format_error"],
    )
    def test_model_kinds(self, error_kind: str) -> None:
        assert classify_llm_fault_side(error_kind) is FaultSide.MODEL

    @pytest.mark.parametrize("error_kind", ["context_overflow", "safety_block"])
    def test_owner_kinds(self, error_kind: str) -> None:
        assert classify_llm_fault_side(error_kind) is FaultSide.OWNER

    def test_none_is_unknown(self) -> None:
        assert classify_llm_fault_side(None) is FaultSide.UNKNOWN

    def test_unrecognized_is_unknown(self) -> None:
        assert classify_llm_fault_side("mystery_error") is FaultSide.UNKNOWN


class TestClassifyToolFaultSide:
    @pytest.mark.parametrize(
        "error_category",
        [
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
        ],
    )
    def test_harness_tool_categories(self, error_category: str) -> None:
        assert classify_tool_fault_side(error_category) is FaultSide.HARNESS_TOOL

    @pytest.mark.parametrize(
        "error_category",
        [
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
        ],
    )
    def test_owner_categories(self, error_category: str) -> None:
        assert classify_tool_fault_side(error_category) is FaultSide.OWNER

    def test_none_is_unknown(self) -> None:
        assert classify_tool_fault_side(None) is FaultSide.UNKNOWN

    def test_unrecognized_is_unknown(self) -> None:
        assert classify_tool_fault_side("unknown_category") is FaultSide.UNKNOWN


class TestClassifyDiagnosticFaultSide:
    @pytest.mark.parametrize(
        "error_type",
        [
            "connection",
            "tls_certificate",
            "rate_limit",
            "billing",
            "api_key",
            "model",
            "custom_model_not_found",
            "timeout",
            "custom_endpoint_unreachable",
        ],
    )
    def test_env_types(self, error_type: str) -> None:
        assert classify_diagnostic_fault_side(error_type) is FaultSide.ENV

    @pytest.mark.parametrize(
        "error_type",
        [
            "response_format_error",
            "thinking_budget_exhausted",
            "tool_call_truncated",
            "tool_call_retry",
            "text_continuation",
            "text_continuation_exhausted",
        ],
    )
    def test_model_types(self, error_type: str) -> None:
        assert classify_diagnostic_fault_side(error_type) is FaultSide.MODEL

    @pytest.mark.parametrize("error_type", ["context_overflow"])
    def test_owner_types(self, error_type: str) -> None:
        assert classify_diagnostic_fault_side(error_type) is FaultSide.OWNER

    def test_none_is_unknown(self) -> None:
        assert classify_diagnostic_fault_side(None) is FaultSide.UNKNOWN


class TestClassifyFaultSideUnified:

    def test_priority_error_kind_wins(self) -> None:
        # error_kind (most specific) should win over category/type.
        assert (
            classify_fault_side(error_kind="rate_limit", error_type="api_key")
            is FaultSide.ENV
        )

    def test_falls_back_to_error_category(self) -> None:
        assert (
            classify_fault_side(error_category="timeout") is FaultSide.HARNESS_TOOL
        )

    def test_falls_back_to_error_type(self) -> None:
        assert (
            classify_fault_side(error_type="connection") is FaultSide.ENV
        )

    def test_error_kind_takes_priority_over_category(self) -> None:
        assert (
            classify_fault_side(
                error_kind="format_error",
                error_category="timeout",
            )
            is FaultSide.MODEL
        )

    def test_all_none_is_unknown(self) -> None:
        assert classify_fault_side() is FaultSide.UNKNOWN

    def test_unrecognized_all_is_unknown(self) -> None:
        assert (
            classify_fault_side(error_kind="x", error_category="y", error_type="z")
            is FaultSide.UNKNOWN
        )

    def test_enum_values_are_stable_tokens(self) -> None:
        # Values are stable API tokens (not user-facing text).
        assert FaultSide.MODEL.value == "model"
        assert FaultSide.HARNESS_TOOL.value == "harness_tool"
        assert FaultSide.HARNESS_PIPELINE.value == "harness_pipeline"
        assert FaultSide.ENV.value == "env"
        assert FaultSide.GRADER.value == "grader"
        assert FaultSide.OWNER.value == "owner"
        assert FaultSide.UNKNOWN.value == "unknown"


class TestEnumCoverageGuard:
    """Regression guard: every canonical enum member must be classifiable.

    When a new ToolErrorCategory or ErrorKind member is added but the
    corresponding fault-side set is not updated, classification silently
    degrades to UNKNOWN (frontend badge disappears). These tests fail loudly
    instead, so the sets stay in sync with the enums.
    """

    @pytest.mark.parametrize("category", list(ToolErrorCategory))
    def test_all_tool_error_categories_classifiable(self, category: ToolErrorCategory) -> None:
        assert classify_tool_fault_side(category.value) is not FaultSide.UNKNOWN, (
            f"ToolErrorCategory.{category.name} is not mapped in fault_side — add it to "
            "_HARNESS_TOOL_CATEGORIES or _OWNER_TOOL_CATEGORIES"
        )

    @pytest.mark.parametrize("kind", [k for k in ErrorKind if k is not ErrorKind.UNKNOWN])
    def test_all_error_kinds_classifiable(self, kind: ErrorKind) -> None:
        assert classify_llm_fault_side(kind.value) is not FaultSide.UNKNOWN, (
            f"ErrorKind.{kind.name} is not mapped in fault_side — add it to "
            "_ENV_LLM_KINDS, _MODEL_LLM_KINDS, or _OWNER_LLM_KINDS"
        )

    @pytest.mark.parametrize(
        "error_type",
        [t for t in REQUIRED_ERROR_TYPES if t != "unknown"],
    )
    def test_all_required_diagnostic_types_classifiable(self, error_type: str) -> None:
        assert classify_diagnostic_fault_side(error_type) is not FaultSide.UNKNOWN, (
            f"Diagnostic error_type {error_type!r} is not mapped in fault_side — add it to "
            "_ENV_DIAGNOSTIC_TYPES, _MODEL_DIAGNOSTIC_TYPES, or _OWNER_DIAGNOSTIC_TYPES"
        )

    @pytest.mark.parametrize(
        "error_type",
        [
            "thinking_budget_exhausted",
            "tool_call_truncated",
            "tool_call_retry",
            "text_continuation",
            "text_continuation_exhausted",
        ],
    )
    def test_truncation_diagnostic_types_classifiable(self, error_type: str) -> None:
        # Truncation types are produced by LLMErrorDiagnostic.diagnose_truncation
        # (stream_recovery_truncation.py) — keep them mapped to MODEL.
        assert classify_diagnostic_fault_side(error_type) is FaultSide.MODEL, (
            f"Truncation error_type {error_type!r} must map to MODEL"
        )
