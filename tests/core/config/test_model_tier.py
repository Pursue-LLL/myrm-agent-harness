"""Tests for model tier inference logic."""

import pytest

from myrm_agent_harness.core.config.llm import CustomModelDef
from myrm_agent_harness.core.config.model_tier import ModelTier, infer_model_tier


class TestInferModelTier:
    """Test infer_model_tier with various model configurations."""

    def test_strong_cloud_models(self) -> None:
        assert infer_model_tier("gpt-4o") == ModelTier.STRONG
        assert infer_model_tier("claude-3.5-sonnet") == ModelTier.STRONG
        assert infer_model_tier("gemini-2-flash") == ModelTier.STRONG
        assert infer_model_tier("deepseek-v3") == ModelTier.STRONG

    def test_weak_by_param_size_in_name(self) -> None:
        assert infer_model_tier("qwen2.5:7b") == ModelTier.WEAK
        assert infer_model_tier("ollama/llama3:8b") == ModelTier.WEAK
        assert infer_model_tier("mistral_7b") == ModelTier.WEAK
        assert infer_model_tier("phi-3.5:3.8b") == ModelTier.WEAK
        assert infer_model_tier("ollama/codellama:13b") == ModelTier.WEAK

    def test_medium_by_param_size_in_name(self) -> None:
        assert infer_model_tier("qwen2.5:32b") == ModelTier.MEDIUM
        assert infer_model_tier("deepseek-coder-33b") == ModelTier.MEDIUM

    def test_strong_by_param_size_in_name(self) -> None:
        assert infer_model_tier("qwen3-235b") == ModelTier.STRONG
        assert infer_model_tier("llama3:70b") == ModelTier.STRONG

    def test_weak_by_context_length_from_custom_def(self) -> None:
        custom_def = CustomModelDef(model_id="my-model", context_length=4096)
        assert infer_model_tier("my-model", custom_model_def=custom_def) == ModelTier.WEAK

    def test_weak_by_context_length_8k(self) -> None:
        custom_def = CustomModelDef(model_id="local-llm", context_length=8192)
        assert infer_model_tier("local-llm", custom_model_def=custom_def) == ModelTier.WEAK

    def test_medium_by_context_length(self) -> None:
        custom_def = CustomModelDef(model_id="mid-model", context_length=32768)
        assert infer_model_tier("mid-model", custom_model_def=custom_def) == ModelTier.MEDIUM

    def test_strong_by_context_length(self) -> None:
        custom_def = CustomModelDef(model_id="big-model", context_length=128000)
        assert infer_model_tier("big-model", custom_model_def=custom_def) == ModelTier.STRONG

    def test_max_context_tokens_parameter(self) -> None:
        assert infer_model_tier("unknown-model", max_context_tokens=4096) == ModelTier.WEAK
        assert infer_model_tier("unknown-model", max_context_tokens=65536) == ModelTier.MEDIUM
        assert infer_model_tier("unknown-model", max_context_tokens=128000) == ModelTier.STRONG

    def test_custom_def_takes_priority_over_max_context_tokens(self) -> None:
        custom_def = CustomModelDef(model_id="x", context_length=4096)
        result = infer_model_tier("x", custom_model_def=custom_def, max_context_tokens=128000)
        assert result == ModelTier.WEAK

    def test_unknown_model_defaults_to_strong(self) -> None:
        assert infer_model_tier("some-unknown-api-model") == ModelTier.STRONG

    def test_context_length_boundary_weak_threshold(self) -> None:
        custom_def_at = CustomModelDef(model_id="x", context_length=16384)
        assert infer_model_tier("x", custom_model_def=custom_def_at) == ModelTier.WEAK

        custom_def_above = CustomModelDef(model_id="x", context_length=16385)
        assert infer_model_tier("x", custom_model_def=custom_def_above) == ModelTier.MEDIUM

    def test_param_boundary_weak_threshold(self) -> None:
        assert infer_model_tier("model-14b") == ModelTier.WEAK
        assert infer_model_tier("model-15b") == ModelTier.MEDIUM
