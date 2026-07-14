"""Integration tests for reasoning_timeout — no mocks on core path.

Validates that create_litellm_model correctly propagates timeout floors
to the ChatLiteLLM instance, and that the force_timeout parameter reaches
the LiteLLM completion layer during a real API call.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.llms.core.llm import create_litellm_model
from myrm_agent_harness.toolkits.llms.core.reasoning_timeout import get_reasoning_timeout_floor

_ENV_TEST = Path(__file__).resolve().parents[5] / "myrm-agent" / "myrm-agent-server" / ".env.test"


class TestReasoningTimeoutIntegration:
    """Full-path integration: create_litellm_model → ChatLiteLLM → force_timeout."""

    def test_reasoning_model_gets_elevated_timeout(self) -> None:
        """create_litellm_model('openai/o3') should create instance with 600s timeout."""
        llm = create_litellm_model("openai/o3", api_key="sk-test")
        assert llm.request_timeout == 600.0

    def test_reasoning_model_force_timeout_in_params(self) -> None:
        """force_timeout in litellm params must equal the reasoning floor."""
        llm = create_litellm_model("deepseek/deepseek-r1", api_key="sk-test")
        params = llm._default_params
        assert params["force_timeout"] == 600.0

    def test_non_reasoning_model_keeps_default_timeout(self) -> None:
        """Non-reasoning models should retain the default 300s timeout."""
        llm = create_litellm_model("openai/gpt-4o", api_key="sk-test")
        assert llm.request_timeout == 300.0

    def test_explicit_timeout_not_overridden(self) -> None:
        """User-specified request_timeout takes precedence over floor."""
        llm = create_litellm_model("openai/o3", api_key="sk-test", request_timeout=120.0)
        assert llm.request_timeout == 120.0

    @pytest.mark.parametrize(
        ("model", "expected_timeout"),
        [
            ("openai/o3", 600.0),
            ("openai/o3-mini", 450.0),
            ("deepseek/deepseek-r1", 600.0),
            ("anthropic/claude-opus-4", 450.0),
            ("openai/gpt-4o", 300.0),
            ("minimax/MiniMax-M3", 300.0),
        ],
    )
    def test_timeout_matrix(self, model: str, expected_timeout: float) -> None:
        """Cross-model timeout assignment matrix."""
        llm = create_litellm_model(model, api_key="sk-test")
        assert llm.request_timeout == expected_timeout

    def test_force_timeout_consistency(self) -> None:
        """force_timeout from _default_params must match request_timeout."""
        for model, expected in [("openai/o3", 600.0), ("gemini-2.5-pro", 450.0)]:
            llm = create_litellm_model(model, api_key="sk-test")
            params = llm._default_params
            assert params["force_timeout"] == expected
            assert llm.request_timeout == expected


class TestReasoningTimeoutStreamingPath:
    """Validates timeout floor in streaming mode (production primary path)."""

    def test_streaming_model_inherits_timeout_floor(self) -> None:
        """Streaming ChatLiteLLM for reasoning model should have elevated timeout."""
        llm = create_litellm_model("openai/o3", api_key="sk-test", streaming=True)
        assert llm.streaming is True
        assert llm.request_timeout == 600.0

    def test_streaming_force_timeout_in_default_params(self) -> None:
        """force_timeout in _default_params should be correct in streaming mode."""
        llm = create_litellm_model("deepseek/deepseek-r1", api_key="sk-test", streaming=True)
        params = llm._default_params
        assert params["stream"] is True
        assert params["force_timeout"] == 600.0

    def test_non_reasoning_streaming_uses_default(self) -> None:
        """Non-reasoning streaming model keeps default 300s."""
        llm = create_litellm_model("openai/gpt-4o", api_key="sk-test", streaming=True)
        assert llm.request_timeout == 300.0


class TestReasoningTimeoutLLMManagerPath:
    """Validates timeout propagation through LLMManager → create_litellm_model."""

    @pytest.mark.asyncio
    async def test_manager_single_llm_reasoning_timeout(self) -> None:
        """LLMManager.get_llm with reasoning model should apply floor."""
        from myrm_agent_harness.toolkits.llms.core.manager import LLMManager

        llm = await LLMManager.get_llm(
            model="openai/o3",
            api_key="sk-test",
            streaming=True,
        )
        assert llm.request_timeout == 600.0  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_manager_non_reasoning_default_timeout(self) -> None:
        """LLMManager.get_llm with non-reasoning model keeps default."""
        from myrm_agent_harness.toolkits.llms.core.manager import LLMManager

        llm = await LLMManager.get_llm(
            model="openai/gpt-4o",
            api_key="sk-test",
            streaming=True,
        )
        assert llm.request_timeout == 300.0  # type: ignore[union-attr]


class TestReasoningTimeoutRealAPI:
    """Real API call verifying timeout parameter reaches the network layer.

    Requires BASIC_MODEL, BASIC_API_KEY, BASIC_BASE_URL from .env.test.
    """

    @pytest.fixture(autouse=True)
    def _load_env_test(self) -> None:
        """Load .env.test to get real API credentials."""
        if not _ENV_TEST.exists():
            pytest.skip(f"{_ENV_TEST} not found")
        for line in _ENV_TEST.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            if key and value:
                os.environ[key] = value

    @pytest.fixture()
    def env_config(self) -> dict[str, str]:
        """Use LITE_MODEL (standard LiteLLM provider) for real API validation."""
        api_key = os.environ.get("LITE_API_KEY", "")
        base_url = os.environ.get("LITE_BASE_URL", "")
        model = os.environ.get("LITE_MODEL", "")
        if not all([api_key, base_url, model]):
            pytest.skip("LITE_MODEL/LITE_API_KEY/LITE_BASE_URL not configured")
        return {"api_key": api_key, "base_url": base_url, "model": model}

    def test_real_call_uses_default_timeout(self, env_config: dict[str, str]) -> None:
        """Real API call with non-reasoning model uses default 300s timeout.

        Validates that the full create→invoke path works without timeout issues.
        """
        llm = create_litellm_model(
            model=env_config["model"],
            api_key=env_config["api_key"],
            base_url=env_config["base_url"],
            temperature=0.0,
            max_tokens=5,
        )
        assert llm.request_timeout == 300.0

        result = llm.invoke("Say 'hi'")
        assert result.content

    def test_real_call_timeout_propagates_to_litellm(self, env_config: dict[str, str]) -> None:
        """Verify force_timeout actually reaches litellm.completion() kwargs.

        Uses a spy on litellm.completion to capture the actual timeout value sent.
        """
        import litellm

        captured_kwargs: dict = {}
        original_completion = litellm.completion

        def spy_completion(*args: object, **kwargs: object) -> object:
            captured_kwargs.update(kwargs)  # type: ignore[arg-type]
            return original_completion(*args, **kwargs)

        llm = create_litellm_model(
            model=env_config["model"],
            api_key=env_config["api_key"],
            base_url=env_config["base_url"],
            temperature=0.0,
            max_tokens=5,
        )

        with patch.object(litellm, "completion", side_effect=spy_completion):
            llm.invoke("Say 'ok'")

        assert "force_timeout" in captured_kwargs or "timeout" in captured_kwargs
        timeout_val = captured_kwargs.get("force_timeout") or captured_kwargs.get("timeout")
        assert timeout_val == 300.0
