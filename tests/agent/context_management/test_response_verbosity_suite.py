# [INPUT]: DehydratedSummary, DynamicBudgetScaler, PostGenerationDehydrator, PromptDisciplineInjector, ResponseVerbosityLevel, ResponseVerbositySuite, TriTierResponseVerbosityControlAndDynamicDensityTunerSuite, VerbosityBudgetConfig, VerbosityContextBundle, VerbosityPreferenceResolver, VerbositySource
# [OUTPUT]: test_response_verbosity_suite.py
# [POS]: tests/agent/context_management/test_response_verbosity_suite.py

"""Comprehensive unit tests for TriTierResponseVerbosityControlAndDynamicDensityTunerSuite.

Verifies:
1. Verbosity domain types, enums, and budget configuration defaults.
2. 4-tier cascade preference resolution (Turn > Session > Profile > System).
3. Prompt discipline directives corresponding to each verbosity tier.
4. Dynamic token budget scaling and physical ceiling clamping.
5. Post-generation zero-cost heuristic text dehydration and TL;DR extraction.
6. Composer segmented options metadata for UI pill components.
7. Full facade suite end-to-end binding and integration.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.response_verbosity import (
    DehydratedSummary,
    DynamicBudgetScaler,
    PostGenerationDehydrator,
    PromptDisciplineInjector,
    ResponseVerbosityLevel,
    ResponseVerbositySuite,
    TriTierResponseVerbosityControlAndDynamicDensityTunerSuite,
    VerbosityBudgetConfig,
    VerbosityContextBundle,
    VerbosityPreferenceResolver,
    VerbositySource,
)


def test_verbosity_types_and_defaults() -> None:
    """Verifies default budget thresholds and tier enum values."""
    config = VerbosityBudgetConfig()
    assert config.default_level == ResponseVerbosityLevel.MEDIUM
    assert config.low_max_tokens == 512
    assert config.medium_max_tokens == 2048
    assert config.high_max_tokens == 8192
    assert config.enforce_token_budget_clamping is True
    assert config.inject_system_discipline_prompt is True

    assert ResponseVerbosityLevel.LOW.value == "low"
    assert ResponseVerbosityLevel.MEDIUM.value == "medium"
    assert ResponseVerbosityLevel.HIGH.value == "high"


def test_cascade_preference_resolution() -> None:
    """Verifies strict 4-level precedence cascade in resolver."""
    resolver = VerbosityPreferenceResolver()

    # 1. Turn override takes precedence over all lower levels
    level, src = resolver.resolve(
        turn_override="low",
        session_preference="high",
        profile_default="high",
    )
    assert level == ResponseVerbosityLevel.LOW
    assert src == VerbositySource.TURN_OVERRIDE

    # 2. Session preference takes precedence over profile and system
    level, src = resolver.resolve(
        turn_override=None,
        session_preference=ResponseVerbosityLevel.HIGH,
        profile_default="low",
    )
    assert level == ResponseVerbosityLevel.HIGH
    assert src == VerbositySource.SESSION_PREFERENCE

    # 3. Profile default takes precedence over system default
    level, src = resolver.resolve(
        turn_override=None,
        session_preference=None,
        profile_default="low",
    )
    assert level == ResponseVerbosityLevel.LOW
    assert src == VerbositySource.PROFILE_DEFAULT

    # 4. System default fallback
    level, src = resolver.resolve()
    assert level == ResponseVerbosityLevel.MEDIUM
    assert src == VerbositySource.SYSTEM_DEFAULT

    # 5. Invalid string values gracefully fallback to next level
    level, src = resolver.resolve(turn_override="invalid_tier", profile_default="high")
    assert level == ResponseVerbosityLevel.HIGH
    assert src == VerbositySource.PROFILE_DEFAULT


def test_prompt_discipline_directives() -> None:
    """Verifies discipline injection instructions across all 3 tiers."""
    injector = PromptDisciplineInjector()

    low_text = injector.generate_discipline_instruction(ResponseVerbosityLevel.LOW)
    assert "Ultra-Concise" in low_text
    assert "Zero Fluff" in low_text
    assert "3-5 lines" in low_text

    med_text = injector.generate_discipline_instruction(ResponseVerbosityLevel.MEDIUM)
    assert "Balanced" in med_text
    assert "Standard Rule" in med_text

    high_text = injector.generate_discipline_instruction(ResponseVerbosityLevel.HIGH)
    assert "Comprehensive" in high_text
    assert "In-Depth Rule" in high_text
    assert "architectural rationale" in high_text


def test_dynamic_token_budget_scaling() -> None:
    """Verifies physical token cap reduction and ceiling clamping."""
    scaler = DynamicBudgetScaler()

    # Low tier limits output to 512 tokens and adds slight presence penalty
    tokens_low, penalty_low = scaler.scale_budget(ResponseVerbosityLevel.LOW)
    assert tokens_low == 512
    assert penalty_low > 0.0

    # Medium tier defaults to 2048 tokens
    tokens_med, penalty_med = scaler.scale_budget(ResponseVerbosityLevel.MEDIUM)
    assert tokens_med == 2048
    assert penalty_med == 0.0

    # High tier allocates 8192 tokens
    tokens_high, _ = scaler.scale_budget(ResponseVerbosityLevel.HIGH)
    assert tokens_high == 8192

    # Clamping against a lower physical model context limit
    clamped_tokens, _ = scaler.scale_budget(ResponseVerbosityLevel.HIGH, model_hard_ceiling=1024)
    assert clamped_tokens == 1024


def test_post_generation_text_dehydration() -> None:
    """Verifies zero-overhead extraction of actionable TL;DR bullet points."""
    dehydrator = PostGenerationDehydrator()

    # 1. Empty text case
    empty_res = dehydrator.dehydrate("")
    assert empty_res.original_length_chars == 0
    assert empty_res.tldr_text == ""
    assert empty_res.compression_ratio == 1.0

    # 2. Verbose response with greeting fluff and structured bullets
    verbose_response = (
        "Hello! Certainly, I am very glad to help you resolve this architecture question today.\n"
        "Here are the core findings:\n"
        "- Finding 1: Prefix caching requires deterministic serialization order.\n"
        "- Finding 2: Ephemeral FTS5 indexes must isolate tenant tables.\n"
        "- Finding 3: Truncate max_tokens dynamically to cut latency by 60%.\n"
        "Please let me know if you need any additional explanations or diagrams!"
    )

    result = dehydrator.dehydrate(verbose_response, max_takeaways=3)
    assert result.original_length_chars == len(verbose_response.strip())
    assert len(result.key_takeaways) == 3
    assert any("Prefix caching requires" in t for t in result.key_takeaways)
    assert any("Ephemeral FTS5" in t for t in result.key_takeaways)
    assert any("Truncate max_tokens" in t for t in result.key_takeaways)
    assert result.compression_ratio < 1.0
    assert "Hello! Certainly" not in result.tldr_text


def test_composer_segmented_options_metadata() -> None:
    """Verifies UI metadata contract for frontend segmented switchers."""
    suite = TriTierResponseVerbosityControlAndDynamicDensityTunerSuite()
    options = suite.get_composer_segmented_options()

    assert len(options) == 3
    ids = [opt["id"] for opt in options]
    assert ids == ["low", "medium", "high"]

    low_opt = options[0]
    assert "极简" in low_opt["label"]
    assert low_opt["max_tokens"] == "512"


def test_full_suite_facade_resolve_and_bind() -> None:
    """Verifies end-to-end integration through the unified suite facade."""
    suite = FullSuite = ResponseVerbositySuite()
    assert TriTierResponseVerbosityControlAndDynamicDensityTunerSuite is ResponseVerbositySuite

    bundle: VerbosityContextBundle = suite.resolve_and_bind(
        turn_override="low",
        profile_default="high",
        model_hard_ceiling=4096,
    )

    assert bundle.level == ResponseVerbosityLevel.LOW
    assert bundle.source == VerbositySource.TURN_OVERRIDE
    assert "Ultra-Concise" in bundle.prompt_discipline_instruction
    assert bundle.recommended_max_tokens == 512
    assert bundle.recommended_presence_penalty > 0.0

    # Also test dehydrate on suite facade
    dehydrated = suite.dehydrate_response("Summary: This is an important security finding.\n")
    assert len(dehydrated.key_takeaways) >= 1
