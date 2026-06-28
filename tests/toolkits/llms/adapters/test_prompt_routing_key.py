"""Tests for prompt_cache_key injection (OpenAI KV cache routing affinity)."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.context_vars import prompt_routing_key_var
from myrm_agent_harness.toolkits.llms.adapters.chat_model import ChatLiteLLM


# ---------------------------------------------------------------------------
# _is_openai_native_endpoint detection
# ---------------------------------------------------------------------------


class TestOpenAINativeEndpointDetection:
    def test_default_api_base_is_openai(self):
        """No api_base set → defaults to OpenAI."""
        model = ChatLiteLLM(model="gpt-4o")
        assert model._is_openai_native_endpoint() is True

    def test_explicit_openai_base(self):
        model = ChatLiteLLM(model="gpt-4o", api_base="https://api.openai.com/v1")
        assert model._is_openai_native_endpoint() is True

    def test_deepseek_base_rejected(self):
        model = ChatLiteLLM(model="deepseek-chat", api_base="https://api.deepseek.com/v1")
        assert model._is_openai_native_endpoint() is False

    def test_azure_provider_rejected(self):
        model = ChatLiteLLM(model="gpt-4o", custom_llm_provider="azure")
        assert model._is_openai_native_endpoint() is False

    def test_ollama_provider_rejected(self):
        model = ChatLiteLLM(model="llama3", custom_llm_provider="ollama")
        assert model._is_openai_native_endpoint() is False

    def test_openai_provider_explicit(self):
        model = ChatLiteLLM(model="gpt-4o", custom_llm_provider="openai")
        assert model._is_openai_native_endpoint() is True

    def test_custom_proxy_rejected(self):
        model = ChatLiteLLM(model="gpt-4o", api_base="https://my-proxy.example.com/v1")
        assert model._is_openai_native_endpoint() is False


# ---------------------------------------------------------------------------
# _inject_prompt_routing_key behavior
# ---------------------------------------------------------------------------


class TestInjectPromptRoutingKey:
    def test_injects_when_openai_and_key_set(self):
        """Should inject prompt_cache_key for OpenAI endpoint with active routing key."""
        token = prompt_routing_key_var.set("session-abc-123")
        try:
            model = ChatLiteLLM(model="gpt-4o")
            params: dict[str, object] = {"model": "gpt-4o"}
            model._inject_prompt_routing_key(params)
            assert params["prompt_cache_key"] == "session-abc-123"
        finally:
            prompt_routing_key_var.reset(token)

    def test_noop_when_no_routing_key(self):
        """Should not inject when ContextVar is unset."""
        token = prompt_routing_key_var.set(None)
        try:
            model = ChatLiteLLM(model="gpt-4o")
            params: dict[str, object] = {"model": "gpt-4o"}
            model._inject_prompt_routing_key(params)
            assert "prompt_cache_key" not in params
        finally:
            prompt_routing_key_var.reset(token)

    def test_noop_for_non_openai(self):
        """Should not inject for non-OpenAI endpoints even with routing key set."""
        token = prompt_routing_key_var.set("session-xyz")
        try:
            model = ChatLiteLLM(model="deepseek-chat", api_base="https://api.deepseek.com/v1")
            params: dict[str, object] = {"model": "deepseek-chat"}
            model._inject_prompt_routing_key(params)
            assert "prompt_cache_key" not in params
        finally:
            prompt_routing_key_var.reset(token)

    def test_noop_for_empty_routing_key(self):
        """Empty string routing key should not inject."""
        token = prompt_routing_key_var.set("")
        try:
            model = ChatLiteLLM(model="gpt-4o")
            params: dict[str, object] = {"model": "gpt-4o"}
            model._inject_prompt_routing_key(params)
            assert "prompt_cache_key" not in params
        finally:
            prompt_routing_key_var.reset(token)


# ---------------------------------------------------------------------------
# Integration: ContextVar propagation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_routing_key_propagates_to_subtask():
    """Verify ContextVar propagates to asyncio child tasks (subagent scenario)."""
    import asyncio

    prompt_routing_key_var.set("parent-session-id")

    captured: list[str | None] = []

    async def child_task():
        captured.append(prompt_routing_key_var.get())

    await asyncio.create_task(child_task())
    assert captured == ["parent-session-id"]
