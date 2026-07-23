import sys
import types

import pytest

from myrm_agent_harness.utils.token_economics.cache_savings import calculate_cache_savings_usd


def _make_mock_litellm() -> types.ModuleType:
    mock_litellm = types.ModuleType("litellm")
    mock_litellm.model_cost = {
        "claude-3-5-sonnet": {
            "input_cost_per_token": 0.000003,
            "output_cost_per_token": 0.000015,
            "cache_read_input_token_cost": 0.0000003,
            "cache_creation_input_token_cost": 0.00000375,
        },
        "model-no-cache-cost": {
            "input_cost_per_token": 0.000003,
            "output_cost_per_token": 0.000015,
        }
    }

    def mock_get_model_info(model_name: str) -> dict | None:
        return mock_litellm.model_cost.get(model_name)
    mock_litellm.get_model_info = mock_get_model_info

    return mock_litellm


@pytest.fixture(autouse=True)
def _restore_litellm():
    """Ensure sys.modules['litellm'] is restored after each test."""
    original = sys.modules.get("litellm")
    yield
    if original is not None:
        sys.modules["litellm"] = original
    else:
        sys.modules.pop("litellm", None)


def _install_mock_litellm() -> None:
    sys.modules["litellm"] = _make_mock_litellm()


def test_empty_model_returns_zero():
    assert calculate_cache_savings_usd({"cached_tokens": 100}, None) == 0.0
    assert calculate_cache_savings_usd({"cached_tokens": 100}, "") == 0.0


def test_empty_usage_returns_zero():
    assert calculate_cache_savings_usd({}, "claude-3-5-sonnet") == 0.0


def test_no_cached_tokens_returns_zero():
    _install_mock_litellm()
    usage = {"prompt_tokens_details": {"cached_tokens": 0, "cache_creation_input_tokens": 0}}
    assert calculate_cache_savings_usd(usage, "claude-3-5-sonnet") == 0.0


def test_litellm_has_cache_read_cost():
    """When litellm provides explicit cache_read_input_token_cost, use it directly."""
    _install_mock_litellm()

    usage = {"prompt_tokens_details": {"cached_tokens": 1000, "cache_creation_input_tokens": 500}}
    savings = calculate_cache_savings_usd(usage, "claude-3-5-sonnet")
    # Base cost = 0.000003
    # savings_per_read = 0.000003 - 0.0000003 = 0.0000027; gross = 1000 * 0.0000027 = 0.0027
    # write_premium = 0.00000375 - 0.000003 = 0.00000075; penalty = 500 * 0.00000075 = 0.000375
    # net = 0.0027 - 0.000375 = 0.002325
    assert abs(savings - 0.002325) < 1e-6


def test_cache_savings_negative_roi():
    """Test that cache savings can be negative if write premium exceeds read savings."""
    _install_mock_litellm()

    usage = {
        "prompt_tokens_details": {
            "cached_tokens": 0,
            "cache_creation_input_tokens": 1000
        }
    }

    # Write penalty = 1000 * 0.00000075 = 0.00075
    # Gross savings = 0
    # Net = -0.00075
    savings = calculate_cache_savings_usd(usage, "claude-3-5-sonnet")
    assert savings < 0
    assert abs(savings - (-0.00075)) < 1e-6


def test_model_no_cache_cost_returns_zero():
    """When model does not have cache read cost defined, return 0 strictly."""
    _install_mock_litellm()
    usage = {"prompt_tokens_details": {"cached_tokens": 1000}}
    assert calculate_cache_savings_usd(usage, "model-no-cache-cost") == 0.0


def test_litellm_import_error():
    """When litellm import fails entirely, return 0.0."""
    sys.modules["litellm"] = None  # type: ignore[assignment]
    usage = {"prompt_tokens_details": {"cached_tokens": 500}}
    assert calculate_cache_savings_usd(usage, "claude-3-5-sonnet") == 0.0


def test_model_alias_not_found_returns_zero():
    """When neither model_cost nor get_model_info has pricing."""
    mock = types.ModuleType("litellm")
    mock.model_cost = {}
    mock.get_model_info = lambda m: None
    sys.modules["litellm"] = mock

    usage = {"prompt_tokens_details": {"cached_tokens": 500}}
    assert calculate_cache_savings_usd(usage, "totally-unknown") == 0.0


def test_model_alias_get_model_info_raises():
    """When get_model_info raises, fall through gracefully."""
    mock = types.ModuleType("litellm")
    mock.model_cost = {}
    mock.get_model_info = lambda m: (_ for _ in ()).throw(RuntimeError("info error"))
    sys.modules["litellm"] = mock

    usage = {"prompt_tokens_details": {"cached_tokens": 500}}
    assert calculate_cache_savings_usd(usage, "error-model") == 0.0
