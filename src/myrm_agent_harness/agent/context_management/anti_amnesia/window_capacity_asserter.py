"""Physical context window capacity assertion and anti-truncation gates.

[INPUT]
- anti_amnesia_types::ModelWindowSpec, CapacityAssertionResult, CompressionFallbackTier (POS: Anti-amnesia domain models)

[OUTPUT]
- InsufficientWindowCapacityError: Raised when a target model cannot safely hold history.
- WindowCapacityAsserter: Evaluates model headroom and prevents silent truncation fallbacks.

[POS]
Physical capacity gate preventing compression modules from silently handing oversized
histories to small-context fallback models, which would cause severe historical truncation.
"""

from __future__ import annotations

from .anti_amnesia_types import (
    CapacityAssertionResult,
    CompressionFallbackTier,
    ModelWindowSpec,
)


class InsufficientWindowCapacityError(ValueError):
    """Raised when the target compression model lacks sufficient window capacity."""

    def __init__(
        self,
        required_tokens: int,
        safe_capacity: int,
        model_name: str,
        message: str,
    ) -> None:
        super().__init__(message)
        self.required_tokens = required_tokens
        self.safe_capacity = safe_capacity
        self.model_name = model_name


class WindowCapacityAsserter:
    """Performs rigorous assertions on target model context capacity to prevent amnesia."""

    @classmethod
    def evaluate_capacity(
        cls,
        total_tokens: int,
        spec: ModelWindowSpec,
    ) -> CapacityAssertionResult:
        """Evaluate whether a model spec can safely fit total_tokens without truncation."""
        tokens = max(total_tokens, 0)
        safe_cap = spec.safe_input_capacity

        if tokens <= safe_cap:
            return CapacityAssertionResult(
                passed=True,
                required_tokens=tokens,
                model_window=spec.context_window,
                safe_input_capacity=safe_cap,
                deficit_tokens=0,
                error_message=None,
            )

        deficit = tokens - safe_cap
        err = (
            f"Physical capacity check failed for model '{spec.model_name}': required {tokens} tokens "
            f"exceeds safe input capacity of {safe_cap} tokens by {deficit} tokens "
            f"(total window: {spec.context_window}, headroom ratio: {spec.safety_headroom_ratio}). "
            f"Direct compression would cause catastrophic historical truncation."
        )

        return CapacityAssertionResult(
            passed=False,
            required_tokens=tokens,
            model_window=spec.context_window,
            safe_input_capacity=safe_cap,
            deficit_tokens=deficit,
            error_message=err,
        )

    @classmethod
    def assert_capacity_or_raise(
        cls,
        total_tokens: int,
        spec: ModelWindowSpec,
    ) -> CapacityAssertionResult:
        """Evaluate capacity and raise InsufficientWindowCapacityError if assertion fails."""
        result = cls.evaluate_capacity(total_tokens, spec)
        if not result.passed:
            raise InsufficientWindowCapacityError(
                required_tokens=result.required_tokens,
                safe_capacity=result.safe_input_capacity,
                model_name=spec.model_name,
                message=result.error_message or "Insufficient context window capacity",
            )
        return result

    @classmethod
    def select_safe_compression_tier(
        cls,
        total_tokens: int,
        primary_spec: ModelWindowSpec | None,
        fallback_spec: ModelWindowSpec | None,
    ) -> tuple[CompressionFallbackTier, ModelWindowSpec | None]:
        """Determine the safest execution tier preventing silent truncation.

        Returns:
            Tuple of (tier, chosen_spec).
        """
        if primary_spec is not None:
            primary_eval = cls.evaluate_capacity(total_tokens, primary_spec)
            if primary_eval.passed:
                return CompressionFallbackTier.PRIMARY_LONG_WINDOW, primary_spec

        if fallback_spec is not None:
            fallback_eval = cls.evaluate_capacity(total_tokens, fallback_spec)
            if fallback_eval.passed:
                return CompressionFallbackTier.PRIMARY_LONG_WINDOW, fallback_spec

            # Fallback spec exists but cannot fit the entire history in one pass:
            # Shift to Chunked Map-Reduce rather than truncating!
            return CompressionFallbackTier.MAP_REDUCE_FALLBACK, fallback_spec

        # Neither model can safely ingest monolithic history: shift to deterministic rescue
        return CompressionFallbackTier.LOCAL_DETERMINISTIC_RESCUE, None
