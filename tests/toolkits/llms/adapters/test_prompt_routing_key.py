"""Tests for session routing keys: OpenAI prompt_cache_key and xAI x-grok-conv-id (KV cache affinity)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage

from myrm_agent_harness.core.context_vars import chat_id_var, prompt_routing_key_var
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
# xAI conversation affinity (x-grok-conv-id)
# ---------------------------------------------------------------------------


class TestXaiNativeEndpointDetection:
    @pytest.mark.parametrize(
        "api_base",
        [
            "https://api.x.ai/v1",
            "https://us-east-1.api.x.ai/v1",
            "HTTPS://API.X.AI/v1/",
            "api.x.ai/v1",
            " https://api.x.ai ",
        ],
    )
    def test_first_party_hosts_are_native(self, api_base: str):
        assert ChatLiteLLM(model="grok-4", api_base=api_base)._is_xai_native_endpoint() is True

    @pytest.mark.parametrize(
        "api_base",
        [
            "https://api.openai.com/v1",
            "https://api.deepseek.com/v1",
            "https://notx.ai/v1",
            "https://x.ai.evil.example/v1",
            "https://proxy.example.com/api.x.ai/v1",
        ],
    )
    def test_other_hosts_are_not_native(self, api_base: str):
        assert ChatLiteLLM(model="grok-4", api_base=api_base)._is_xai_native_endpoint() is False

    def test_provider_hint_without_a_base_url_is_native(self):
        assert ChatLiteLLM(model="grok-4", custom_llm_provider="xai")._is_xai_native_endpoint() is True
        assert ChatLiteLLM(model="xai/grok-4")._is_xai_native_endpoint() is True

    def test_a_custom_base_url_wins_over_the_xai_model_name(self):
        model = ChatLiteLLM(model="xai/grok-4", api_base="https://proxy.example.com/v1")
        assert model._is_xai_native_endpoint() is False

    def test_a_plain_model_without_hints_is_not_native(self):
        assert ChatLiteLLM(model="gpt-4o")._is_xai_native_endpoint() is False


class TestInjectXaiConversationId:
    @staticmethod
    def _xai_model() -> ChatLiteLLM:
        return ChatLiteLLM(model="grok-4", api_base="https://api.x.ai/v1")

    def test_injects_the_routing_key_as_conversation_id(self):
        token = prompt_routing_key_var.set("session-abc-123")
        try:
            params: dict[str, object] = {"model": "grok-4"}
            self._xai_model()._inject_prompt_routing_key(params)
            assert params["extra_headers"] == {"x-grok-conv-id": "session-abc-123"}
        finally:
            prompt_routing_key_var.reset(token)

    def test_falls_back_to_the_chat_id(self):
        routing = prompt_routing_key_var.set(None)
        chat = chat_id_var.set("chat-42")
        try:
            params: dict[str, object] = {}
            self._xai_model()._inject_prompt_routing_key(params)
            assert params["extra_headers"] == {"x-grok-conv-id": "chat-42"}
        finally:
            chat_id_var.reset(chat)
            prompt_routing_key_var.reset(routing)

    def test_keeps_the_headers_already_on_the_request(self):
        token = prompt_routing_key_var.set("session-abc-123")
        try:
            params: dict[str, object] = {"extra_headers": {"Authorization": "Bearer t"}}
            self._xai_model()._inject_prompt_routing_key(params)
            assert params["extra_headers"] == {"Authorization": "Bearer t", "x-grok-conv-id": "session-abc-123"}
        finally:
            prompt_routing_key_var.reset(token)

    def test_never_overrides_a_caller_supplied_conversation_id(self):
        token = prompt_routing_key_var.set("session-abc-123")
        try:
            supplied = {"X-Grok-Conv-Id": "caller-chosen"}
            params: dict[str, object] = {"extra_headers": supplied}
            self._xai_model()._inject_prompt_routing_key(params)
            assert params["extra_headers"] == {"X-Grok-Conv-Id": "caller-chosen"}
        finally:
            prompt_routing_key_var.reset(token)

    def test_noop_without_a_routing_key(self):
        routing = prompt_routing_key_var.set(None)
        chat = chat_id_var.set(None)
        try:
            params: dict[str, object] = {}
            self._xai_model()._inject_prompt_routing_key(params)
            assert "extra_headers" not in params
        finally:
            chat_id_var.reset(chat)
            prompt_routing_key_var.reset(routing)

    def test_other_endpoints_get_no_xai_header(self):
        token = prompt_routing_key_var.set("session-abc-123")
        try:
            for model in (
                ChatLiteLLM(model="gpt-4o"),
                ChatLiteLLM(model="deepseek-chat", api_base="https://api.deepseek.com/v1"),
            ):
                params: dict[str, object] = {}
                model._inject_prompt_routing_key(params)
                assert "x-grok-conv-id" not in (params.get("extra_headers") or {})
        finally:
            prompt_routing_key_var.reset(token)

    def test_xai_requests_get_no_openai_cache_key(self):
        token = prompt_routing_key_var.set("session-abc-123")
        try:
            params: dict[str, object] = {}
            self._xai_model()._inject_prompt_routing_key(params)
            assert "prompt_cache_key" not in params
        finally:
            prompt_routing_key_var.reset(token)

    @pytest.mark.asyncio
    async def test_header_reaches_the_wire_next_to_the_authorization_header(self):
        model = ChatLiteLLM(model="xai/grok-4", api_base="https://api.x.ai/v1", api_key="xai-token")
        model.client = MagicMock()
        model.client.acreate = AsyncMock(
            return_value={
                "id": "chatcmpl-1",
                "model": "grok-4",
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        )
        token = prompt_routing_key_var.set("session-abc-123")
        try:
            await model.ainvoke([HumanMessage(content="hi")])
        finally:
            prompt_routing_key_var.reset(token)

        assert model.client.acreate.call_args.kwargs["extra_headers"] == {
            "Authorization": "Bearer xai-token",
            "x-grok-conv-id": "session-abc-123",
        }


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
