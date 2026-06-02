"""Tests for Kimi/Moonshot temperature floor in clean_model_kwargs."""

from myrm_agent_harness.toolkits.llms.utils.litellm_utils import clean_model_kwargs


def test_kimi_temperature_floor():
    """Kimi models should have temperature clamped to >= 1.0."""
    result = clean_model_kwargs({"temperature": 0.2, "model": "moonshot/kimi-k2.5"}, "moonshot/kimi-k2.5")
    assert result["temperature"] == 1.0


def test_kimi_high_temperature_kept():
    """High temperature for Kimi should be kept as-is."""
    result = clean_model_kwargs({"temperature": 1.5, "model": "moonshot/kimi"}, "moonshot/kimi")
    assert result["temperature"] == 1.5


def test_non_kimi_temperature_unchanged():
    """Non-Kimi models should not have temperature adjusted."""
    result = clean_model_kwargs({"temperature": 0.2, "model": "openai/gpt-4"}, "openai/gpt-4")
    assert result["temperature"] == 0.2


def test_kimi_no_temperature_key():
    """If no temperature is set, no floor should be applied."""
    result = clean_model_kwargs({"model": "moonshot/kimi-k2.5"}, "moonshot/kimi-k2.5")
    assert "temperature" not in result
