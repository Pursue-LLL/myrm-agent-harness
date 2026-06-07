"""Tests for configurable compress_start_ratio feature.

Validates:
1. Proportional gap formula correctness across the valid range [0.20, 0.85]
2. Default behavior preserved when compress_start_ratio is None
3. Clamping at boundary values
4. Context extraction from request objects
5. Integration with build_default_processors
6. Defensive coercion of invalid inputs
"""

from __future__ import annotations

from typing import ClassVar

from myrm_agent_harness.agent.context_management.context import (
    AgentContext,
    _coerce_optional_float,
    _coerce_optional_int,
    extract_context_from_request,
)
from myrm_agent_harness.agent.context_management.infra.schemas import ContextConfig


class TestContextConfigDefaultBehavior:
    """Ensure default behavior is unchanged when compress_start_ratio is None."""

    def test_default_thresholds_128k(self) -> None:
        config = ContextConfig(max_context_tokens=128000)
        assert config.proactive_reset_threshold == 51200  # 128000 * 0.4
        assert config.compress_threshold == 64000  # 128000 * 0.5
        assert config.compress_force_threshold == 89600  # 128000 * 0.7
        assert config.summarize_trigger_threshold == 108000  # min(128000*0.9, max(64000, 108000))

    def test_default_thresholds_200k(self) -> None:
        config = ContextConfig(max_context_tokens=200000)
        assert config.proactive_reset_threshold == 80000
        assert config.compress_threshold == 100000
        assert config.compress_force_threshold == 140000
        assert config.summarize_trigger_threshold == 180000

    def test_default_thresholds_1m(self) -> None:
        config = ContextConfig(max_context_tokens=1000000)
        assert config.proactive_reset_threshold == 400000
        assert config.compress_threshold == 500000
        assert config.compress_force_threshold == 700000
        assert config.summarize_trigger_threshold == 900000

    def test_compress_start_ratio_none_by_default(self) -> None:
        config = ContextConfig(max_context_tokens=128000)
        assert config.compress_start_ratio is None
        assert config._effective_ratio() is None


class TestProportionalGapFormula:
    """Validate the proportional gap formula for various compress_start_ratio values."""

    def test_ratio_0_40_matches_default(self) -> None:
        """At ratio=0.40, thresholds should be close to defaults."""
        config = ContextConfig(max_context_tokens=200000, compress_start_ratio=0.40)
        # gap = (0.95 - 0.40) / 3 = 0.1833...
        # proactive_reset = 200000 * 0.40 = 80000
        # compress = 200000 * (0.40 + 0.1833) = 200000 * 0.5833 = 116666
        # compress_force = 200000 * (0.40 + 0.3666) = 200000 * 0.7666 = 153333
        # summarize_trigger = 200000 * 0.95 = 190000
        assert config.proactive_reset_threshold == 80000
        assert config.compress_threshold == 116666
        assert config.compress_force_threshold == 153333
        assert config.summarize_trigger_threshold == 190000

    def test_ratio_0_60_delayed_compression(self) -> None:
        """At ratio=0.60, compression starts later."""
        config = ContextConfig(max_context_tokens=200000, compress_start_ratio=0.60)
        # gap = (0.95 - 0.60) / 3 = 0.1166...
        assert config.proactive_reset_threshold == 120000  # 200000 * 0.60
        assert config.compress_threshold == 143333  # 200000 * (0.60 + 0.1166) = ~143333
        assert config.compress_force_threshold == 166666  # 200000 * (0.60 + 0.2333) = ~166666
        assert config.summarize_trigger_threshold == 190000  # 200000 * 0.95

    def test_ratio_0_20_aggressive_compression(self) -> None:
        """At ratio=0.20, compression starts very early (cost-saving mode)."""
        config = ContextConfig(max_context_tokens=200000, compress_start_ratio=0.20)
        # gap = (0.95 - 0.20) / 3 = 0.25
        assert config.proactive_reset_threshold == 40000  # 200000 * 0.20
        assert config.compress_threshold == 90000  # 200000 * 0.45
        assert config.compress_force_threshold == 140000  # 200000 * 0.70
        assert config.summarize_trigger_threshold == 190000  # 200000 * 0.95

    def test_ratio_0_85_maximum_delayed(self) -> None:
        """At ratio=0.85 (max valid), thresholds are tightly packed near the end."""
        config = ContextConfig(max_context_tokens=200000, compress_start_ratio=0.85)
        # gap = (0.95 - 0.85) / 3 = 0.0333...
        assert config.proactive_reset_threshold == 170000  # 200000 * 0.85
        assert config.compress_threshold == 176666  # 200000 * (0.85 + 0.0333) = ~176666
        assert config.compress_force_threshold == 183333  # 200000 * (0.85 + 0.0666) = ~183333
        assert config.summarize_trigger_threshold == 190000  # 200000 * 0.95

    def test_thresholds_always_ascending(self) -> None:
        """For any valid ratio, thresholds must be strictly ascending."""
        for ratio_pct in range(20, 86):
            ratio = ratio_pct / 100.0
            config = ContextConfig(max_context_tokens=200000, compress_start_ratio=ratio)
            assert config.proactive_reset_threshold < config.compress_threshold, f"Failed at ratio={ratio}"
            assert config.compress_threshold < config.compress_force_threshold, f"Failed at ratio={ratio}"
            assert config.compress_force_threshold < config.summarize_trigger_threshold, f"Failed at ratio={ratio}"

    def test_thresholds_never_exceed_window(self) -> None:
        """No threshold should exceed max_context_tokens."""
        for ratio_pct in range(20, 86):
            ratio = ratio_pct / 100.0
            for window in [64000, 128000, 200000, 1000000]:
                config = ContextConfig(max_context_tokens=window, compress_start_ratio=ratio)
                assert config.proactive_reset_threshold <= window
                assert config.compress_threshold <= window
                assert config.compress_force_threshold <= window
                assert config.summarize_trigger_threshold <= window


class TestClamping:
    """Test boundary clamping for out-of-range compress_start_ratio values."""

    def test_below_minimum_clamps_to_0_20(self) -> None:
        config = ContextConfig(max_context_tokens=200000, compress_start_ratio=0.05)
        assert config._effective_ratio() == 0.20
        assert config.proactive_reset_threshold == 40000  # 200000 * 0.20

    def test_above_maximum_clamps_to_0_85(self) -> None:
        config = ContextConfig(max_context_tokens=200000, compress_start_ratio=0.99)
        assert config._effective_ratio() == 0.85
        assert config.proactive_reset_threshold == 170000  # 200000 * 0.85

    def test_negative_value_clamps_to_0_20(self) -> None:
        config = ContextConfig(max_context_tokens=200000, compress_start_ratio=-0.5)
        assert config._effective_ratio() == 0.20

    def test_exactly_0_20_is_valid(self) -> None:
        config = ContextConfig(max_context_tokens=200000, compress_start_ratio=0.20)
        assert config._effective_ratio() == 0.20

    def test_exactly_0_85_is_valid(self) -> None:
        config = ContextConfig(max_context_tokens=200000, compress_start_ratio=0.85)
        assert config._effective_ratio() == 0.85


class TestAgentContextExtraction:
    """Test compress_start_ratio extraction from runtime context."""

    def test_from_dict_with_ratio(self) -> None:
        ctx = AgentContext.from_dict(
            {"chat_id": "test", "max_context_tokens": 128000, "compress_start_ratio": 0.6}
        )
        assert ctx.compress_start_ratio == 0.6
        assert ctx.max_context_tokens == 128000

    def test_from_dict_without_ratio(self) -> None:
        ctx = AgentContext.from_dict({"chat_id": "test", "max_context_tokens": 128000})
        assert ctx.compress_start_ratio is None

    def test_to_dict_includes_ratio(self) -> None:
        ctx = AgentContext(chat_id="test", max_context_tokens=128000, compress_start_ratio=0.5)
        d = ctx.to_dict()
        assert d["compress_start_ratio"] == 0.5

    def test_to_dict_excludes_none_ratio(self) -> None:
        ctx = AgentContext(chat_id="test", max_context_tokens=128000)
        d = ctx.to_dict()
        assert "compress_start_ratio" not in d


class TestExtractContextFromRequest:
    """Test the updated extract_context_from_request function."""

    def test_extracts_ratio_from_mapping_context(self) -> None:
        class MockRuntime:
            context: ClassVar[dict[str, object]] = {"chat_id": "abc", "max_context_tokens": 200000, "compress_start_ratio": 0.7}

        class MockRequest:
            runtime = MockRuntime()

        chat_id, max_tokens, ratio = extract_context_from_request(MockRequest())
        assert chat_id == "abc"
        assert max_tokens == 200000
        assert ratio == 0.7

    def test_returns_none_ratio_when_absent(self) -> None:
        class MockRuntime:
            context: ClassVar[dict[str, object]] = {"chat_id": "abc", "max_context_tokens": 128000}

        class MockRequest:
            runtime = MockRuntime()

        chat_id, max_tokens, ratio = extract_context_from_request(MockRequest())
        assert chat_id == "abc"
        assert max_tokens == 128000
        assert ratio is None

    def test_returns_none_for_empty_request(self) -> None:
        class MockRequest:
            runtime = None

        chat_id, max_tokens, ratio = extract_context_from_request(MockRequest())
        assert chat_id is None
        assert max_tokens is None
        assert ratio is None


class TestBuildDefaultProcessorsIntegration:
    """Test that compress_start_ratio flows through to build_default_processors."""

    def test_builds_with_ratio(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.engine import (
            build_default_processors,
        )

        processors = build_default_processors(
            max_context_tokens=200000,
            compress_start_ratio=0.6,
        )
        assert len(processors) > 0

        summarize_proc = None
        for p in processors:
            if p.name == "summarize":
                summarize_proc = p
                break
        assert summarize_proc is not None
        assert summarize_proc.config.compress_start_ratio == 0.6  # type: ignore[attr-defined]
        assert summarize_proc.config.proactive_reset_threshold == 120000  # type: ignore[attr-defined]

    def test_builds_without_ratio(self) -> None:
        from myrm_agent_harness.agent.context_management.pipeline.engine import (
            build_default_processors,
        )

        processors = build_default_processors(max_context_tokens=200000)
        assert len(processors) > 0

        summarize_proc = None
        for p in processors:
            if p.name == "summarize":
                summarize_proc = p
                break
        assert summarize_proc is not None
        assert summarize_proc.config.compress_start_ratio is None  # type: ignore[attr-defined]
        assert summarize_proc.config.proactive_reset_threshold == 80000  # type: ignore[attr-defined]


class TestMinimumFloorGuarantees:
    """Test that minimum floors protect against extremely small windows."""

    def test_small_window_20k_with_ratio(self) -> None:
        config = ContextConfig(max_context_tokens=30000, compress_start_ratio=0.20)
        assert config.proactive_reset_threshold >= 20000
        assert config.compress_threshold >= 25000
        assert config.compress_force_threshold >= 35000

    def test_small_window_50k_default(self) -> None:
        config = ContextConfig(max_context_tokens=50000)
        assert config.proactive_reset_threshold == 20000
        assert config.compress_threshold == 25000
        assert config.compress_force_threshold == 35000
        # min(50000*0.9=45000, max(50000*0.5=25000, 50000-20000=30000)) = min(45000, 30000) = 30000
        assert config.summarize_trigger_threshold == 30000


class TestCoercionDefensiveness:
    """Test that _coerce_optional_float/int handle invalid inputs gracefully."""

    def test_float_valid_string(self) -> None:
        assert _coerce_optional_float("0.7") == 0.7

    def test_float_valid_int(self) -> None:
        assert _coerce_optional_float(1) == 1.0

    def test_float_none(self) -> None:
        assert _coerce_optional_float(None) is None

    def test_float_invalid_string(self) -> None:
        assert _coerce_optional_float("abc") is None

    def test_float_empty_string(self) -> None:
        assert _coerce_optional_float("") is None

    def test_float_non_scalar(self) -> None:
        assert _coerce_optional_float([1, 2, 3]) is None

    def test_float_dict(self) -> None:
        assert _coerce_optional_float({"value": 0.5}) is None

    def test_int_valid_string(self) -> None:
        assert _coerce_optional_int("200000") == 200000

    def test_int_invalid_string(self) -> None:
        assert _coerce_optional_int("abc") is None

    def test_int_empty_string(self) -> None:
        assert _coerce_optional_int("") is None

    def test_int_none(self) -> None:
        assert _coerce_optional_int(None) is None

    def test_int_float_string(self) -> None:
        assert _coerce_optional_int("3.14") is None
