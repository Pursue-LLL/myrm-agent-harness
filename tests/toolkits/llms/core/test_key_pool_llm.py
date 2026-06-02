"""Tests for KeyPoolLLM — transparent API key rotation on key-specific errors."""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from myrm_agent_harness.toolkits.llms.core.credential_pool import CredentialPool, CredentialPoolStrategy
from myrm_agent_harness.toolkits.llms.core.key_pool_llm import KeyPoolLLM


def _make_rate_limit_error() -> Exception:
    """Create an exception that classify_error maps to RATE_LIMIT."""
    exc = Exception("Rate limit exceeded")
    exc.status_code = 429  # type: ignore[attr-defined]
    return exc


def _make_auth_error() -> Exception:
    """Create an exception that classify_error maps to AUTH."""
    exc = Exception("Invalid API key provided")
    exc.status_code = 401  # type: ignore[attr-defined]
    return exc


def _make_billing_error() -> Exception:
    """Create an exception that classify_error maps to BILLING."""
    exc = Exception("insufficient balance, payment required")
    exc.status_code = 402  # type: ignore[attr-defined]
    return exc


def _make_context_overflow_error() -> Exception:
    """Create an error NOT handled by key rotation (model-level failover)."""
    exc = Exception("maximum context length exceeded")
    exc.status_code = 400  # type: ignore[attr-defined]
    return exc


def _make_chat_result(text: str = "hello") -> ChatResult:
    return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])


def _make_mock_llm(
    agenerate_result: ChatResult | Exception | None = None,
    astream_chunks: list[ChatGenerationChunk] | Exception | None = None,
) -> MagicMock:
    llm = MagicMock()
    llm.model = "test-model"

    if isinstance(agenerate_result, Exception):
        llm._agenerate = AsyncMock(side_effect=agenerate_result)
    elif agenerate_result is not None:
        llm._agenerate = AsyncMock(return_value=agenerate_result)
    else:
        llm._agenerate = AsyncMock(return_value=_make_chat_result())

    if isinstance(astream_chunks, Exception):

        async def _fail_stream(*args: object, **kwargs: object) -> AsyncIterator[ChatGenerationChunk]:
            raise astream_chunks  # type: ignore[misc]
            yield  # noqa: unreachable — makes this an async generator

        llm._astream = _fail_stream
    elif astream_chunks is not None:

        async def _ok_stream(*args: object, **kwargs: object) -> AsyncIterator[ChatGenerationChunk]:
            for c in astream_chunks:
                yield c

        llm._astream = _ok_stream
    else:
        chunk = ChatGenerationChunk(message=AIMessageChunk(content="hi"))

        async def _default_stream(*args: object, **kwargs: object) -> AsyncIterator[ChatGenerationChunk]:
            yield chunk

        llm._astream = _default_stream

    return llm


class TestKeyPoolLLMInit:
    def test_requires_at_least_one_instance(self) -> None:
        pool = CredentialPool(["k1"])
        with pytest.raises(ValueError, match="at least one"):
            KeyPoolLLM(instances={}, pool=pool)

    def test_properties(self) -> None:
        pool = CredentialPool(["k1", "k2"])
        instances = {"k1": _make_mock_llm(), "k2": _make_mock_llm()}
        llm = KeyPoolLLM(instances=instances, pool=pool)
        assert llm._llm_type == "key_pool_llm"
        assert llm._identifying_params["pool_size"] == 2
        assert llm._identifying_params["pool_strategy"] == "round_robin"
        assert llm.credential_pool is pool

    def test_properties_reflect_pool_strategy(self) -> None:
        pool = CredentialPool(["k1", "k2"], strategy=CredentialPoolStrategy.FILL_FIRST)
        instances = {"k1": _make_mock_llm(), "k2": _make_mock_llm()}
        llm = KeyPoolLLM(instances=instances, pool=pool)
        assert llm._identifying_params["pool_strategy"] == "fill_first"
        assert llm.credential_pool.strategy == CredentialPoolStrategy.FILL_FIRST


class TestKeyPoolLLMAgenerate:
    @pytest.mark.asyncio
    async def test_success_first_key(self) -> None:
        pool = CredentialPool(["k1", "k2"])
        result = _make_chat_result("ok")
        instances = {"k1": _make_mock_llm(agenerate_result=result), "k2": _make_mock_llm()}
        llm = KeyPoolLLM(instances=instances, pool=pool)

        out = await llm._agenerate([HumanMessage(content="hi")])
        assert out.generations[0].message.content == "ok"

    @pytest.mark.asyncio
    async def test_rotates_on_rate_limit(self) -> None:
        pool = CredentialPool(["k1", "k2"])
        rate_exc = _make_rate_limit_error()
        ok_result = _make_chat_result("from k2")
        instances = {
            "k1": _make_mock_llm(agenerate_result=rate_exc),
            "k2": _make_mock_llm(agenerate_result=ok_result),
        }
        llm = KeyPoolLLM(instances=instances, pool=pool)

        out = await llm._agenerate([HumanMessage(content="hi")])
        assert out.generations[0].message.content == "from k2"
        assert pool.available_count() == 1

    @pytest.mark.asyncio
    async def test_raises_non_rate_limit_error(self) -> None:
        pool = CredentialPool(["k1"])
        auth_err = Exception("Invalid API key")
        auth_err.status_code = 401  # type: ignore[attr-defined]
        instances = {"k1": _make_mock_llm(agenerate_result=auth_err)}
        llm = KeyPoolLLM(instances=instances, pool=pool)

        with pytest.raises(Exception, match="Invalid API key"):
            await llm._agenerate([HumanMessage(content="hi")])

    @pytest.mark.asyncio
    async def test_all_keys_rate_limited_raises(self) -> None:
        pool = CredentialPool(["k1", "k2"])
        rate_exc = _make_rate_limit_error()
        instances = {
            "k1": _make_mock_llm(agenerate_result=rate_exc),
            "k2": _make_mock_llm(agenerate_result=rate_exc),
        }
        llm = KeyPoolLLM(instances=instances, pool=pool)

        with pytest.raises(Exception, match="Rate limit"):
            await llm._agenerate([HumanMessage(content="hi")])


class TestKeyPoolLLMAuthBillingRotation:
    """Tests for AUTH and BILLING error key rotation (A2 enhancement)."""

    @pytest.mark.asyncio
    async def test_rotates_on_auth_error(self) -> None:
        pool = CredentialPool(["k1", "k2"])
        auth_exc = _make_auth_error()
        ok_result = _make_chat_result("from k2")
        instances = {
            "k1": _make_mock_llm(agenerate_result=auth_exc),
            "k2": _make_mock_llm(agenerate_result=ok_result),
        }
        llm = KeyPoolLLM(instances=instances, pool=pool)
        out = await llm._agenerate([HumanMessage(content="hi")])
        assert out.generations[0].message.content == "from k2"

    @pytest.mark.asyncio
    async def test_rotates_on_billing_error(self) -> None:
        pool = CredentialPool(["k1", "k2"])
        billing_exc = _make_billing_error()
        ok_result = _make_chat_result("from k2")
        instances = {
            "k1": _make_mock_llm(agenerate_result=billing_exc),
            "k2": _make_mock_llm(agenerate_result=ok_result),
        }
        llm = KeyPoolLLM(instances=instances, pool=pool)
        out = await llm._agenerate([HumanMessage(content="hi")])
        assert out.generations[0].message.content == "from k2"

    @pytest.mark.asyncio
    async def test_auth_error_single_key_still_raises(self) -> None:
        pool = CredentialPool(["k1"])
        auth_exc = _make_auth_error()
        instances = {"k1": _make_mock_llm(agenerate_result=auth_exc)}
        llm = KeyPoolLLM(instances=instances, pool=pool)
        with pytest.raises(Exception, match="Invalid API key"):
            await llm._agenerate([HumanMessage(content="hi")])

    @pytest.mark.asyncio
    async def test_all_keys_auth_error_raises(self) -> None:
        pool = CredentialPool(["k1", "k2"])
        auth_exc = _make_auth_error()
        instances = {
            "k1": _make_mock_llm(agenerate_result=auth_exc),
            "k2": _make_mock_llm(agenerate_result=auth_exc),
        }
        llm = KeyPoolLLM(instances=instances, pool=pool)
        with pytest.raises(Exception, match="Invalid API key"):
            await llm._agenerate([HumanMessage(content="hi")])

    @pytest.mark.asyncio
    async def test_context_overflow_not_rotated(self) -> None:
        """Errors outside _KEY_ROTATABLE_KINDS should raise immediately."""
        pool = CredentialPool(["k1", "k2"])
        overflow_exc = _make_context_overflow_error()
        instances = {
            "k1": _make_mock_llm(agenerate_result=overflow_exc),
            "k2": _make_mock_llm(),
        }
        llm = KeyPoolLLM(instances=instances, pool=pool)
        with pytest.raises(Exception, match="maximum context length"):
            await llm._agenerate([HumanMessage(content="hi")])

    @pytest.mark.asyncio
    async def test_stream_rotates_on_auth_error(self) -> None:
        pool = CredentialPool(["k1", "k2"])
        auth_exc = _make_auth_error()
        ok_chunk = ChatGenerationChunk(message=AIMessageChunk(content="from k2"))
        instances = {
            "k1": _make_mock_llm(astream_chunks=auth_exc),
            "k2": _make_mock_llm(astream_chunks=[ok_chunk]),
        }
        llm = KeyPoolLLM(instances=instances, pool=pool)
        chunks = [c async for c in llm._astream([HumanMessage(content="hi")])]
        assert len(chunks) == 1
        assert chunks[0].message.content == "from k2"

    @pytest.mark.asyncio
    async def test_stream_rotates_on_billing_error(self) -> None:
        pool = CredentialPool(["k1", "k2"])
        billing_exc = _make_billing_error()
        ok_chunk = ChatGenerationChunk(message=AIMessageChunk(content="from k2"))
        instances = {
            "k1": _make_mock_llm(astream_chunks=billing_exc),
            "k2": _make_mock_llm(astream_chunks=[ok_chunk]),
        }
        llm = KeyPoolLLM(instances=instances, pool=pool)
        chunks = [c async for c in llm._astream([HumanMessage(content="hi")])]
        assert len(chunks) == 1
        assert chunks[0].message.content == "from k2"


class TestKeyPoolLLMAstream:
    @pytest.mark.asyncio
    async def test_stream_success(self) -> None:
        pool = CredentialPool(["k1"])
        chunk = ChatGenerationChunk(message=AIMessageChunk(content="streamed"))
        instances = {"k1": _make_mock_llm(astream_chunks=[chunk])}
        llm = KeyPoolLLM(instances=instances, pool=pool)

        chunks = [c async for c in llm._astream([HumanMessage(content="hi")])]
        assert len(chunks) == 1
        assert chunks[0].message.content == "streamed"

    @pytest.mark.asyncio
    async def test_stream_rotates_on_rate_limit(self) -> None:
        pool = CredentialPool(["k1", "k2"])
        rate_exc = _make_rate_limit_error()
        ok_chunk = ChatGenerationChunk(message=AIMessageChunk(content="from k2"))
        instances = {
            "k1": _make_mock_llm(astream_chunks=rate_exc),
            "k2": _make_mock_llm(astream_chunks=[ok_chunk]),
        }
        llm = KeyPoolLLM(instances=instances, pool=pool)

        chunks = [c async for c in llm._astream([HumanMessage(content="hi")])]
        assert len(chunks) == 1
        assert chunks[0].message.content == "from k2"


class TestKeyPoolLLMEdgeCases:
    def test_bind_tools_binds_all_instances_and_returns_self(self) -> None:
        pool = CredentialPool(["k1", "k2"])
        mock1 = _make_mock_llm()
        mock1.bind_tools = MagicMock()
        mock2 = _make_mock_llm()
        mock2.bind_tools = MagicMock()
        instances = {"k1": mock1, "k2": mock2}
        llm = KeyPoolLLM(instances=instances, pool=pool)

        result = llm.bind_tools([{"type": "function", "name": "test"}])
        assert result is llm
        mock1.bind_tools.assert_called_once()
        mock2.bind_tools.assert_called_once()

    def test_sync_generate_delegates_to_primary(self) -> None:
        pool = CredentialPool(["k1", "k2"])
        result = _make_chat_result("sync result")
        mock1 = _make_mock_llm()
        mock1._generate = MagicMock(return_value=result)
        mock2 = _make_mock_llm()
        instances = {"k1": mock1, "k2": mock2}
        llm = KeyPoolLLM(instances=instances, pool=pool)

        out = llm._generate([HumanMessage(content="hi")])
        assert out.generations[0].message.content == "sync result"
        mock1._generate.assert_called_once()

    def test_sync_generate_rotates_on_rate_limit(self) -> None:
        pool = CredentialPool(["k1", "k2"], strategy=CredentialPoolStrategy.ROUND_ROBIN)
        rate_exc = _make_rate_limit_error()
        ok_result = _make_chat_result("from k2")
        mock1 = _make_mock_llm()
        mock1._generate = MagicMock(side_effect=rate_exc)
        mock2 = _make_mock_llm()
        mock2._generate = MagicMock(return_value=ok_result)
        instances = {"k1": mock1, "k2": mock2}
        llm = KeyPoolLLM(instances=instances, pool=pool)

        out = llm._generate([HumanMessage(content="hi")])
        assert out.generations[0].message.content == "from k2"
        assert pool.available_count() == 1

    @pytest.mark.asyncio
    async def test_missing_instance_key_skipped(self) -> None:
        pool = CredentialPool(["k1", "k2"])
        ok_result = _make_chat_result("ok")
        instances = {"k2": _make_mock_llm(agenerate_result=ok_result)}
        llm = KeyPoolLLM(instances=instances, pool=pool)

        out = await llm._agenerate([HumanMessage(content="hi")])
        assert out.generations[0].message.content == "ok"

    def test_identifying_params(self) -> None:
        pool = CredentialPool(["k1", "k2"])
        mock_llm = _make_mock_llm()
        mock_llm.model = "test-model-v2"
        instances = {"k1": mock_llm, "k2": _make_mock_llm()}
        llm = KeyPoolLLM(instances=instances, pool=pool)

        params = llm._identifying_params
        assert params["model"] == "test-model-v2"
        assert params["pool_size"] == 2
        assert params["pool_strategy"] == "round_robin"
