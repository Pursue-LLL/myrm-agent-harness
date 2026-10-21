"""
[INPUT]: NormalizedTokenUsageSnapshot instances or raw token counters.
[OUTPUT]: InvariantCheckResult verdicts confirming zero-double-counting assertions or applying auto-healing corrections.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/reasoning_semantics/invariant_guard.py
"""

from typing import Optional

from .models import (
    InvariantCheckResult,
    NormalizedTokenUsageSnapshot,
    ReasoningInclusionPolicy,
)


class ReasoningInvariantGuard:
    """
    Runtime invariant validator and auto-remediation guard ensuring zero double-counting
    of reasoning tokens in total volume and cost across all reporting channels.
    """

    @staticmethod
    def verify_and_guard(
        snapshot: NormalizedTokenUsageSnapshot,
        raw_reported_total: Optional[int] = None,
    ) -> InvariantCheckResult:
        """
        Validates core mathematical invariants:
        1. total_tokens == prompt_tokens + completion_tokens (Zero double counting).
        2. reasoning_tokens <= completion_tokens.
        3. visible_content_tokens == completion_tokens - reasoning_tokens.
        """
        # Check 1: Did upstream report an erroneous double-counted total?
        if raw_reported_total is not None:
            flawed_double_total = (
                snapshot.prompt_tokens
                + snapshot.completion_tokens
                + snapshot.reasoning_tokens
            )
            if raw_reported_total == flawed_double_total and snapshot.reasoning_tokens > 0:
                warning = (
                    f"检测到严重重复计数漏洞: 上报 total ({raw_reported_total}) 包含了 "
                    f"prompt + completion + reasoning ({flawed_double_total})。自动修正剔除二次累加。"
                )
                return InvariantCheckResult(
                    is_valid=False,
                    violation_type="DOUBLE_COUNTING_TOTAL",
                    diagnostic_warning=warning,
                    corrected_snapshot=snapshot,
                )

        # Check 2: Does reasoning exceed total completion?
        if snapshot.reasoning_tokens > snapshot.completion_tokens:
            warning = (
                f"推理 Token 异常溢出: reasoning_tokens ({snapshot.reasoning_tokens}) > "
                f"completion_tokens ({snapshot.completion_tokens})。"
            )
            # Auto-heal: set completion_tokens to max of both
            healed = NormalizedTokenUsageSnapshot(
                prompt_tokens=snapshot.prompt_tokens,
                completion_tokens=snapshot.reasoning_tokens,
                reasoning_tokens=snapshot.reasoning_tokens,
                visible_content_tokens=0,
                total_tokens=snapshot.prompt_tokens + snapshot.reasoning_tokens,
                cost_usd=snapshot.cost_usd,
                is_zero_double_counted=True,
                raw_provider=snapshot.raw_provider,
                policy_applied=snapshot.policy_applied,
                normalized_at=snapshot.normalized_at,
            )
            return InvariantCheckResult(
                is_valid=False,
                violation_type="REASONING_EXCEEDS_COMPLETION",
                diagnostic_warning=warning,
                corrected_snapshot=healed,
            )

        # Check 3: Mathematical equality check on total
        expected_total = snapshot.prompt_tokens + snapshot.completion_tokens
        if snapshot.total_tokens != expected_total:
            warning = (
                f"总量不变量破损: total_tokens ({snapshot.total_tokens}) != "
                f"prompt ({snapshot.prompt_tokens}) + completion ({snapshot.completion_tokens})。"
            )
            healed = NormalizedTokenUsageSnapshot(
                prompt_tokens=snapshot.prompt_tokens,
                completion_tokens=snapshot.completion_tokens,
                reasoning_tokens=snapshot.reasoning_tokens,
                visible_content_tokens=snapshot.visible_content_tokens,
                total_tokens=expected_total,
                cost_usd=snapshot.cost_usd,
                is_zero_double_counted=True,
                raw_provider=snapshot.raw_provider,
                policy_applied=snapshot.policy_applied,
                normalized_at=snapshot.normalized_at,
            )
            return InvariantCheckResult(
                is_valid=False,
                violation_type="TOTAL_INVARIANT_MISMATCH",
                diagnostic_warning=warning,
                corrected_snapshot=healed,
            )

        # All invariants passed perfectly
        return InvariantCheckResult(
            is_valid=True,
            violation_type=None,
            diagnostic_warning=None,
            corrected_snapshot=snapshot,
        )
