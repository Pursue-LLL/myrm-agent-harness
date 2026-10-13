"""KeyPoolLLM.bind_tools contract: bound tools reach the provider and key rotation survives binding.

The real ChatLiteLLM stack runs against a network-free ``litellm.acompletion`` double. A mocked
``bind_tools`` cannot tell whether the bound tools actually travel with the request, which is the
only thing an agent loop relies on.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import litellm
import pytest
from langchain_core.runnables import RunnableBinding
from langchain_core.tools import tool

from myrm_agent_harness.toolkits.llms.core.credential_pool import CredentialPool, CredentialPoolStrategy
from myrm_agent_harness.toolkits.llms.core.key_pool_llm import KeyPoolLLM
from myrm_agent_harness.toolkits.llms.core.llm import ChatLiteLLM

_MODEL = "gpt-4o"
_KEYS = ("k1", "k2")


@tool
def probe(query: str) -> str:
    """Echo the query."""
    return query


class _ProviderDouble:
    """Records every provider request; keys in ``rate_limited`` answer HTTP 429."""

    def __init__(self, rate_limited: frozenset[str] = frozenset()) -> None:
        self.requests: list[dict[str, Any]] = []
        self._rate_limited = rate_limited

    async def acompletion(self, *args: object, **params: Any) -> Any:
        key = str(params.get("api_key"))
        self.requests.append(
            {
                "api_key": key,
                "stream": bool(params.get("stream")),
                "tools": [spec["function"]["name"] for spec in params.get("tools") or []],
                "tool_choice": params.get("tool_choice"),
                "parallel_tool_calls": params.get("parallel_tool_calls"),
            }
        )
        if key in self._rate_limited:
            error = Exception("Rate limit exceeded")
            error.status_code = 429  # type: ignore[attr-defined]
            raise error
        if params.get("stream"):
            return self._stream()
        return litellm.ModelResponse(
            model=_MODEL,
            choices=[{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}],
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        )

    @staticmethod
    async def _stream() -> AsyncIterator[Any]:
        yield litellm.ModelResponseStream(
            model=_MODEL,
            choices=[
                litellm.utils.StreamingChoices(
                    index=0,
                    delta=litellm.utils.Delta(content="ok", role="assistant"),
                    finish_reason="stop",
                )
            ],
        )


def _provider(monkeypatch: pytest.MonkeyPatch, rate_limited: frozenset[str] = frozenset()) -> _ProviderDouble:
    double = _ProviderDouble(rate_limited)
    monkeypatch.setattr(litellm, "acompletion", double.acompletion)
    return double


def _pooled_llm() -> KeyPoolLLM:
    instances = {key: ChatLiteLLM(model=_MODEL, api_key=key) for key in _KEYS}
    pool = CredentialPool(list(_KEYS), strategy=CredentialPoolStrategy.ROUND_ROBIN)
    return KeyPoolLLM(instances=instances, pool=pool)


async def _drain(runnable: Any, *, streaming: bool) -> None:
    if streaming:
        async for _chunk in runnable.astream("hi"):
            pass
    else:
        await runnable.ainvoke("hi")


class TestKeyPoolLLMBindTools:
    def test_bind_tools_returns_a_binding_over_the_pool(self) -> None:
        llm = _pooled_llm()

        bound = llm.bind_tools([probe], tool_choice="required")

        assert isinstance(bound, RunnableBinding)
        assert bound.bound is llm
        assert [spec["function"]["name"] for spec in bound.kwargs["tools"]] == ["probe"]
        assert bound.kwargs["tool_choice"] == "required"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("streaming", [False, True], ids=["invoke", "stream"])
    async def test_bound_pool_sends_the_same_request_as_a_single_key(
        self, monkeypatch: pytest.MonkeyPatch, streaming: bool
    ) -> None:
        provider = _provider(monkeypatch)
        single = ChatLiteLLM(model=_MODEL, api_key="solo").bind_tools(
            [probe], tool_choice="required", parallel_tool_calls=False
        )
        pooled = _pooled_llm().bind_tools([probe], tool_choice="required", parallel_tool_calls=False)

        await _drain(single, streaming=streaming)
        await _drain(pooled, streaming=streaming)

        single_request, pooled_request = provider.requests
        assert single_request["tools"] == ["probe"]
        assert {k: v for k, v in pooled_request.items() if k != "api_key"} == {
            k: v for k, v in single_request.items() if k != "api_key"
        }
        assert pooled_request["api_key"] in _KEYS

    @pytest.mark.asyncio
    @pytest.mark.parametrize("streaming", [False, True], ids=["invoke", "stream"])
    async def test_bound_pool_rotates_keys_and_keeps_tools_on_the_retry(
        self, monkeypatch: pytest.MonkeyPatch, streaming: bool
    ) -> None:
        provider = _provider(monkeypatch, rate_limited=frozenset({"k1"}))
        bound = _pooled_llm().bind_tools([probe])

        await _drain(bound, streaming=streaming)

        attempted_keys = [request["api_key"] for request in provider.requests]
        assert attempted_keys[0] == "k1"
        assert attempted_keys[-1] == "k2"
        assert all(request["tools"] == ["probe"] for request in provider.requests)
