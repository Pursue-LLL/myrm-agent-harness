"""Tests for myrm_agent_harness.utils.token_economics.cost_engine"""

from unittest.mock import MagicMock, patch

from myrm_agent_harness.utils.token_economics.cost_engine import (
    CostResult,
    CostStatus,
    compute_cost,
    compute_cost_by_tokens,
)


class TestCostResult:
    def test_defaults(self) -> None:
        r = CostResult()
        assert r.usd == 0.0
        assert r.status == CostStatus.UNKNOWN

    def test_is_known_actual(self) -> None:
        r = CostResult(usd=0.01, status=CostStatus.ACTUAL)
        assert r.is_known is True

    def test_is_known_estimated(self) -> None:
        r = CostResult(usd=0.005, status=CostStatus.ESTIMATED)
        assert r.is_known is True

    def test_is_known_unknown(self) -> None:
        r = CostResult()
        assert r.is_known is False


class TestComputeCost:
    def test_no_model_returns_unknown(self) -> None:
        assert compute_cost(MagicMock(), None) == CostResult()
        assert compute_cost(MagicMock(), "") == CostResult()

    @patch("litellm.completion_cost", return_value=0.0025)
    def test_positive_cost_returns_actual(self, mock_cc: MagicMock) -> None:
        resp = MagicMock()
        result = compute_cost(resp, "gpt-4o")
        assert result.usd == 0.0025
        assert result.status == CostStatus.ACTUAL
        mock_cc.assert_called_once_with(completion_response=resp, model="gpt-4o")

    @patch("litellm.completion_cost", return_value=0.0)
    def test_zero_cost_returns_unknown(self, mock_cc: MagicMock) -> None:
        result = compute_cost(MagicMock(), "gpt-4o")
        assert result.usd == 0.0
        assert result.status == CostStatus.UNKNOWN

    @patch("litellm.completion_cost", side_effect=ValueError("model not found"))
    def test_exception_returns_unknown(self, mock_cc: MagicMock) -> None:
        result = compute_cost(MagicMock(), "unknown-model")
        assert result == CostResult()


class TestComputeCostByTokens:
    def test_no_model_returns_unknown(self) -> None:
        assert compute_cost_by_tokens(None, 100, 50) == CostResult()
        assert compute_cost_by_tokens("", 100, 50) == CostResult()

    def test_zero_tokens_returns_unknown(self) -> None:
        assert compute_cost_by_tokens("gpt-4o", 0, 0) == CostResult()
        assert compute_cost_by_tokens("gpt-4o", -1, -1) == CostResult()

    @patch("litellm.completion_cost", return_value=0.005)
    def test_positive_cost_returns_actual(self, mock_cc: MagicMock) -> None:
        result = compute_cost_by_tokens("claude-3.5-sonnet", 1000, 500)
        assert result.usd == 0.005
        assert result.status == CostStatus.ACTUAL
        mock_cc.assert_called_once_with(
            model="claude-3.5-sonnet",
            prompt_tokens=1000,
            completion_tokens=500,
        )

    @patch("litellm.completion_cost", return_value=0.0)
    def test_zero_cost_returns_unknown(self, mock_cc: MagicMock) -> None:
        result = compute_cost_by_tokens("gpt-4o", 100, 50)
        assert result.usd == 0.0
        assert result.status == CostStatus.UNKNOWN

    @patch("litellm.completion_cost", side_effect=RuntimeError("API error"))
    def test_exception_returns_unknown(self, mock_cc: MagicMock) -> None:
        result = compute_cost_by_tokens("unknown-model", 100, 50)
        assert result == CostResult()

    @patch("litellm.completion_cost", return_value=0.001)
    def test_only_prompt_tokens(self, mock_cc: MagicMock) -> None:
        result = compute_cost_by_tokens("gpt-4o", 100, 0)
        assert result.status == CostStatus.ACTUAL

    @patch("litellm.completion_cost", return_value=0.002)
    def test_only_completion_tokens(self, mock_cc: MagicMock) -> None:
        result = compute_cost_by_tokens("gpt-4o", 0, 100)
        assert result.status == CostStatus.ACTUAL
