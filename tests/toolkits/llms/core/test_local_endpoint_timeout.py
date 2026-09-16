"""Tests for local endpoint detection and stall timeout relaxation."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.llms.core.llm import (
    _LOCAL_FIRST_EVENT_TIMEOUT,
    _LOCAL_INTER_CHUNK_TIMEOUT,
    _LOCAL_REQUEST_TIMEOUT,
    _is_local_endpoint,
    create_litellm_model,
)


class TestIsLocalEndpoint:
    """Test _is_local_endpoint with various URL patterns."""

    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost:11434",
            "http://localhost:8080/v1",
            "http://127.0.0.1:11434",
            "http://0.0.0.0:8080",
            "http://[::1]:11434",
            "http://192.168.1.100:11434",
            "http://192.168.0.1:8080/v1",
            "http://10.0.0.5:8080",
            "http://10.255.255.255:11434",
            "http://172.16.0.1:8080",
            "http://172.31.255.255:8080",
        ],
    )
    def test_local_endpoints(self, url: str) -> None:
        assert _is_local_endpoint(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://api.openai.com/v1",
            "https://api.anthropic.com",
            "http://my-server.example.com:8080",
            "http://172.32.0.1:8080",
            "http://8.8.8.8:8080",
            "http://100.64.0.1:8080",
        ],
    )
    def test_remote_endpoints(self, url: str) -> None:
        assert _is_local_endpoint(url) is False

    @pytest.mark.parametrize("url", [None, ""])
    def test_empty_input(self, url: str | None) -> None:
        assert _is_local_endpoint(url) is False


class TestCreateLitellmModelLocalTimeout:
    """Test that create_litellm_model applies local timeout relaxation."""

    @patch("myrm_agent_harness.toolkits.llms.core.llm.ChatLiteLLM")
    @patch(
        "myrm_agent_harness.toolkits.llms.core.llm.clean_model_kwargs",
        side_effect=lambda kwargs, model: kwargs,
    )
    def test_local_endpoint_relaxes_timeouts(self, _mock_clean, mock_llm) -> None:
        create_litellm_model("llama-3.1-70b", base_url="http://localhost:11434", streaming=True)
        kwargs = mock_llm.call_args[1]
        assert kwargs["first_event_timeout"] == _LOCAL_FIRST_EVENT_TIMEOUT
        assert kwargs["inter_chunk_timeout"] == _LOCAL_INTER_CHUNK_TIMEOUT
        assert kwargs["request_timeout"] == _LOCAL_REQUEST_TIMEOUT

    @patch("myrm_agent_harness.toolkits.llms.core.llm.ChatLiteLLM")
    @patch(
        "myrm_agent_harness.toolkits.llms.core.llm.clean_model_kwargs",
        side_effect=lambda kwargs, model: kwargs,
    )
    def test_remote_endpoint_no_override(self, _mock_clean, mock_llm) -> None:
        create_litellm_model("gpt-4o", base_url="https://api.openai.com/v1", streaming=True)
        kwargs = mock_llm.call_args[1]
        assert "first_event_timeout" not in kwargs
        assert "inter_chunk_timeout" not in kwargs
        assert "request_timeout" not in kwargs

    @patch("myrm_agent_harness.toolkits.llms.core.llm.ChatLiteLLM")
    @patch(
        "myrm_agent_harness.toolkits.llms.core.llm.clean_model_kwargs",
        side_effect=lambda kwargs, model: kwargs,
    )
    def test_user_override_preserved(self, _mock_clean, mock_llm) -> None:
        create_litellm_model(
            "llama-3.1-70b",
            base_url="http://localhost:11434",
            first_event_timeout=120.0,
        )
        kwargs = mock_llm.call_args[1]
        assert kwargs["first_event_timeout"] == 120.0

    @patch("myrm_agent_harness.toolkits.llms.core.llm.ChatLiteLLM")
    @patch(
        "myrm_agent_harness.toolkits.llms.core.llm.clean_model_kwargs",
        side_effect=lambda kwargs, model: kwargs,
    )
    def test_reasoning_model_remote(self, _mock_clean, mock_llm) -> None:
        create_litellm_model("o3", base_url="https://api.openai.com/v1", streaming=True)
        kwargs = mock_llm.call_args[1]
        assert kwargs["request_timeout"] == 600.0
        assert kwargs["first_event_timeout"] == 300.0

    @patch("myrm_agent_harness.toolkits.llms.core.llm.ChatLiteLLM")
    @patch(
        "myrm_agent_harness.toolkits.llms.core.llm.clean_model_kwargs",
        side_effect=lambda kwargs, model: kwargs,
    )
    def test_reasoning_model_with_user_request_timeout(self, _mock_clean, mock_llm) -> None:
        """Regression: reasoning floor must compute first_event even when request_timeout is user-provided."""
        create_litellm_model("o3", base_url="https://api.openai.com/v1", request_timeout=900)
        kwargs = mock_llm.call_args[1]
        assert kwargs["request_timeout"] == 900
        assert kwargs["first_event_timeout"] == 300.0  # min(600/2, 300)

    @patch("myrm_agent_harness.toolkits.llms.core.llm.ChatLiteLLM")
    @patch(
        "myrm_agent_harness.toolkits.llms.core.llm.clean_model_kwargs",
        side_effect=lambda kwargs, model: kwargs,
    )
    def test_local_reasoning_model(self, _mock_clean, mock_llm) -> None:
        create_litellm_model("deepseek-r1", base_url="http://localhost:11434", streaming=True)
        kwargs = mock_llm.call_args[1]
        assert kwargs["request_timeout"] == 600.0  # reasoning floor
        assert kwargs["first_event_timeout"] == 300.0  # reasoning floor / 2
        assert kwargs["inter_chunk_timeout"] == _LOCAL_INTER_CHUNK_TIMEOUT

    @patch("myrm_agent_harness.toolkits.llms.core.llm.ChatLiteLLM")
    @patch(
        "myrm_agent_harness.toolkits.llms.core.llm.clean_model_kwargs",
        side_effect=lambda kwargs, model: kwargs,
    )
    def test_no_base_url_no_detection(self, _mock_clean, mock_llm) -> None:
        create_litellm_model("gpt-4o", streaming=True)
        kwargs = mock_llm.call_args[1]
        assert "first_event_timeout" not in kwargs
        assert "inter_chunk_timeout" not in kwargs


class TestIsOllamaEndpoint:
    """Test _is_ollama_endpoint detects real Ollama endpoints only."""

    @pytest.mark.parametrize(
        ("url", "model"),
        [
            ("", "ollama/llama3.1"),
            ("http://localhost:11434/v1", "llama3.1"),
            ("http://127.0.0.1:11434/v1", "openai/llama3.1"),
            ("http://my-ollama-host:8080/v1", "qwen2.5"),
        ],
    )
    def test_ollama_endpoints(self, url: str, model: str) -> None:
        from myrm_agent_harness.toolkits.llms.core.llm import _is_ollama_endpoint

        assert _is_ollama_endpoint(url, model) is True

    @pytest.mark.parametrize(
        ("url", "model"),
        [
            ("http://127.0.0.1:20128/v1", "openai-like/deepseek-v4-pro"),
            ("http://127.0.0.1:8000/v1", "qwen2.5-7b"),
            ("https://api.openai.com/v1", "gpt-4o"),
            ("", "gpt-4o"),
            ("http://127.0.0.1:99999/v1", "qwen2.5-7b"),
        ],
    )
    def test_non_ollama_endpoints(self, url: str, model: str) -> None:
        from myrm_agent_harness.toolkits.llms.core.llm import _is_ollama_endpoint

        assert _is_ollama_endpoint(url, model) is False

    def test_ollama_provider_prefix(self) -> None:
        from myrm_agent_harness.toolkits.llms.core.llm import _is_ollama_endpoint

        assert _is_ollama_endpoint("http://127.0.0.1:8080/v1", "ollama/llama3.1") is True


class TestOllamaNumCtxInjection:
    """Test options.num_ctx is injected only for real Ollama endpoints."""

    @patch("myrm_agent_harness.toolkits.llms.core.llm.ChatLiteLLM")
    @patch(
        "myrm_agent_harness.toolkits.llms.core.llm.clean_model_kwargs",
        side_effect=lambda kwargs, model: kwargs,
    )
    def test_ollama_endpoint_gets_num_ctx(self, _mock_clean, mock_llm) -> None:
        create_litellm_model("llama-3.1-70b", base_url="http://localhost:11434", streaming=True)
        kwargs = mock_llm.call_args[1]
        assert kwargs["extra_body"]["options"]["num_ctx"] == 64000

    @patch("myrm_agent_harness.toolkits.llms.core.llm.ChatLiteLLM")
    @patch(
        "myrm_agent_harness.toolkits.llms.core.llm.clean_model_kwargs",
        side_effect=lambda kwargs, model: kwargs,
    )
    def test_gateway_endpoint_gets_no_ollama_options(self, _mock_clean, mock_llm) -> None:
        create_litellm_model("qwen2.5-7b", base_url="http://127.0.0.1:20128/v1", streaming=True)
        kwargs = mock_llm.call_args[1]
        assert "options" not in kwargs.get("extra_body", {})

    @patch("myrm_agent_harness.toolkits.llms.core.llm.ChatLiteLLM")
    @patch(
        "myrm_agent_harness.toolkits.llms.core.llm.clean_model_kwargs",
        side_effect=lambda kwargs, model: kwargs,
    )
    def test_tls_strict_disabled_sets_ssl_verify(self, _mock_clean, mock_llm, monkeypatch) -> None:
        monkeypatch.setenv("MYRM_TLS_STRICT", "0")
        create_litellm_model("gpt-4o", base_url="https://api.openai.com/v1")
        kwargs = mock_llm.call_args[1]
        assert "ssl_verify" in kwargs
        assert kwargs["ssl_verify"] is not True
