"""Tests for ProviderDiversityLinter and validate_provider_diversity in profiles backend."""

from __future__ import annotations

import pytest

from myrm_agent_harness.backends.profiles.diversity_lint import (
    ModelSelectionSlot,
    ProviderDiversityResult,
    extract_root_vendor,
    validate_provider_diversity,
)


class TestExtractRootVendor:
    def test_direct_providers(self) -> None:
        assert extract_root_vendor("openai", "gpt-4o") == "openai"
        assert extract_root_vendor("azure-openai", "gpt-4o-mini") == "openai"
        assert extract_root_vendor("anthropic", "claude-3-5-sonnet") == "anthropic"
        assert extract_root_vendor("deepseek", "deepseek-chat") == "deepseek"
        assert extract_root_vendor("google", "gemini-1.5-pro") == "google"
        assert extract_root_vendor("qwen", "qwen-2.5-72b") == "qwen"
        assert extract_root_vendor("xai", "grok-2") == "xai"

    def test_openrouter_prefix_extraction(self) -> None:
        assert extract_root_vendor("openrouter", "meta-llama/llama-3.3-70b-instruct") == "meta"
        assert extract_root_vendor("openrouter", "qwen/qwen-2.5-coder-32b-instruct") == "qwen"
        assert extract_root_vendor("openrouter", "anthropic/claude-3-5-sonnet") == "anthropic"
        assert extract_root_vendor("openrouter", "deepseek/deepseek-chat") == "deepseek"

    def test_model_name_heuristics(self) -> None:
        assert extract_root_vendor("", "gpt-4o") == "openai"
        assert extract_root_vendor("", "claude-3-5-haiku") == "anthropic"
        assert extract_root_vendor("", "deepseek-coder") == "deepseek"
        assert extract_root_vendor("", "llama-3.1-8b") == "meta"
        assert extract_root_vendor("", "qwen-2.5-14b") == "qwen"


class TestValidateProviderDiversity:
    def test_empty_selections_fails(self) -> None:
        res = validate_provider_diversity([])
        assert not res.is_valid
        assert res.distinct_vendor_count == 0

    def test_single_vendor_fails_default_min_2(self) -> None:
        selections = [
            ModelSelectionSlot(provider_id="openai", model="gpt-4o"),
            ModelSelectionSlot(provider_id="azure-openai", model="gpt-4o-mini"),
            ("openai", "o1"),
        ]
        res = validate_provider_diversity(selections)
        assert not res.is_valid
        assert res.distinct_vendor_count == 1
        assert res.distinct_vendors == ("openai",)
        assert "Insufficient provider diversity" in res.reason

    def test_heterogeneous_vendors_passes(self) -> None:
        selections = [
            ModelSelectionSlot(provider_id="deepseek", model="deepseek-chat"),
            ModelSelectionSlot(provider_id="anthropic", model="claude-3-5-sonnet-20241022"),
            {"providerId": "openrouter", "model": "meta-llama/llama-3.3-70b-instruct"},
        ]
        res = validate_provider_diversity(selections, min_distinct_vendors=2)
        assert res.is_valid
        assert res.distinct_vendor_count == 3
        assert set(res.distinct_vendors) == {"deepseek", "anthropic", "meta"}
        assert res.slots_evaluated == 3

    def test_dict_and_tuple_inputs(self) -> None:
        selections = [
            {"provider": "google", "model": "gemini-1.5-pro"},
            ("qwen", "qwen-2.5-72b"),
        ]
        res = validate_provider_diversity(selections, min_distinct_vendors=2)
        assert res.is_valid
        assert res.distinct_vendor_count == 2
        assert set(res.distinct_vendors) == {"google", "qwen"}
