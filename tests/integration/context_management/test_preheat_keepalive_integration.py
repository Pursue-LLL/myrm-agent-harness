"""Integration test: preheat_prefix_cache and CacheKeepAliveManager with real LLM.

Validates:
1. preheat_prefix_cache sends a real probe to the LLM and returns True.
2. CacheKeepAliveManager correctly activates/deactivates based on provider type.
3. End-to-end idle keepalive loop sends real probes when idle.

Uses BASIC_MODEL from .env.test via ChatLiteLLM — auto-cache provider (OpenAI-like),
so keepalive is expected NOT to activate (validates the negative path).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import time

import pytest
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from myrm_agent_harness.agent.context_management.preheat import (
    CacheKeepAliveManager,
    needs_explicit_preheat,
    preheat_prefix_cache,
)

_RAW_MODEL = os.environ.get("BASIC_MODEL", "openai-like/mimo-v2.5-pro")
_TEST_BASE_URL = os.environ.get("BASIC_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1")
_TEST_API_KEY = os.environ.get("BASIC_API_KEY", "")

pytestmark = pytest.mark.timeout(60)


def _normalize_model(raw: str) -> tuple[str, str | None]:
    openai_compat = {"openai-like", "openai_compatible", "openai-compatible", "openai_like"}
    if "/" in raw:
        prefix, model = raw.split("/", 1)
        if prefix in openai_compat:
            return f"openai/{model}", "openai"
        return raw, None
    return raw, None


def _require_api_key() -> None:
    if not _TEST_API_KEY:
        pytest.skip("BASIC_API_KEY not set — skipping real LLM integration test")


def _make_llm():
    from myrm_agent_harness.toolkits.llms.adapters.chat_model import ChatLiteLLM

    model, provider = _normalize_model(_RAW_MODEL)
    return ChatLiteLLM(
        model=model,
        api_key=_TEST_API_KEY,
        api_base=_TEST_BASE_URL,
        custom_llm_provider=provider,
        temperature=0.0,
        max_tokens=1,
    )


class TestPreheatPrefixCacheIntegration:
    """Real LLM integration tests for preheat_prefix_cache."""

    @pytest.mark.asyncio
    async def test_real_preheat_probe_to_explicit_provider(self) -> None:
        """preheat_prefix_cache sends a real LLM call for explicit-cache providers.

        Forces the model name to "anthropic/test" so preheat logic activates,
        while using the real .env.test LLM endpoint for the actual API call.
        """
        _require_api_key()
        llm = _make_llm()

        msgs: list[BaseMessage] = [
            SystemMessage(content="You are a helpful assistant."),
            HumanMessage(content="warmup"),
        ]

        result = await preheat_prefix_cache(llm, msgs, "anthropic/test-model")
        assert result is True

    @pytest.mark.asyncio
    async def test_preheat_skips_auto_cache_provider(self) -> None:
        """preheat_prefix_cache returns False for auto-cache providers."""
        _require_api_key()
        llm = _make_llm()
        model_name, _ = _normalize_model(_RAW_MODEL)

        msgs: list[BaseMessage] = [
            SystemMessage(content="You are a helpful assistant."),
            HumanMessage(content="warmup"),
        ]

        result = await preheat_prefix_cache(llm, msgs, model_name)
        assert result is False

        result2 = await preheat_prefix_cache(llm, msgs, "gpt-4o")
        assert result2 is False


class TestCacheKeepAliveManagerIntegration:
    """Real LLM integration tests for CacheKeepAliveManager."""

    def test_auto_cache_provider_not_activated(self) -> None:
        """Manager should NOT be activated for auto-cache providers.

        This validates the real production path: when a user configures an
        OpenAI-compatible model, keepalive must not start.
        """
        _require_api_key()
        model_name, _ = _normalize_model(_RAW_MODEL)
        assert needs_explicit_preheat(model_name) is False

    def test_explicit_preheat_provider_detection(self) -> None:
        """Verify provider detection matches expected behavior."""
        assert needs_explicit_preheat("anthropic/claude-3-5-sonnet") is True
        assert needs_explicit_preheat("claude-3-opus") is True
        assert needs_explicit_preheat("qwen-max") is True
        assert needs_explicit_preheat("dashscope/qwen-turbo") is True
        assert needs_explicit_preheat("gpt-4o") is False
        assert needs_explicit_preheat("deepseek-v3") is False

    @pytest.mark.asyncio
    async def test_keepalive_loop_sends_real_probe(self) -> None:
        """End-to-end: keepalive loop sends a real probe when idle.

        Uses a very short interval (0.5s) to avoid long test times.
        Forces needs_explicit_preheat to return True for the test model.
        """
        _require_api_key()
        llm = _make_llm()
        model_name, _ = _normalize_model(_RAW_MODEL)

        from unittest.mock import patch

        mgr = CacheKeepAliveManager(llm, "You are a helpful assistant.", model_name)
        mgr._last_activity = time.monotonic() - 600

        probe_count = 0
        original_preheat = preheat_prefix_cache

        async def counting_preheat(
            llm_arg: object,
            msgs: list[BaseMessage],
            model: str,
        ) -> bool:
            nonlocal probe_count
            result = await original_preheat(llm_arg, msgs, model)
            probe_count += 1
            return result

        with (
            patch(
                "myrm_agent_harness.agent.context_management.preheat._KEEPALIVE_INTERVAL_SECONDS",
                0.5,
            ),
            patch(
                "myrm_agent_harness.agent.context_management.preheat.preheat_prefix_cache",
                counting_preheat,
            ),
            patch(
                "myrm_agent_harness.agent.context_management.preheat.needs_explicit_preheat",
                return_value=True,
            ),
        ):
            task = asyncio.create_task(mgr._loop())
            await asyncio.sleep(3.0)
            mgr.stop()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        assert probe_count >= 1, f"Expected at least 1 real probe, got {probe_count}"

    @pytest.mark.asyncio
    async def test_keepalive_lifecycle_start_touch_stop(self) -> None:
        """Full lifecycle: start → touch → stop with real LLM instance."""
        _require_api_key()
        llm = _make_llm()
        model_name, _ = _normalize_model(_RAW_MODEL)

        mgr = CacheKeepAliveManager(llm, "You are a helpful assistant.", model_name)
        assert mgr._task is None

        mgr.start()
        assert mgr._task is not None

        before = mgr._last_activity
        await asyncio.sleep(0.01)
        mgr.touch()
        assert mgr._last_activity > before

        mgr.stop()
        assert mgr._stopped is True
        assert mgr._task is None
