"""Tests for concurrency module."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.llms.adapters.concurrency import (
    get_semaphores,
)


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    """Reset module-level state before each test."""
    import myrm_agent_harness.toolkits.llms.adapters.concurrency as mod

    mod._GLOBAL_SEMAPHORE = None
    mod._GLOBAL_SEMAPHORE_INITIALIZED = False
    mod._MODEL_SEMAPHORES.clear()


class TestGetSemaphores:
    @pytest.mark.asyncio
    async def test_no_env_vars(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            global_sem, model_sem = await get_semaphores("gpt-4o")
        assert global_sem is None
        assert model_sem is None

    @pytest.mark.asyncio
    async def test_global_semaphore_from_env(self) -> None:
        with patch.dict(os.environ, {"LLM_GLOBAL_MAX_CONCURRENCY": "5"}, clear=True):
            global_sem, model_sem = await get_semaphores("gpt-4o")
        assert global_sem is not None
        assert model_sem is None

    @pytest.mark.asyncio
    async def test_model_semaphore_from_env(self) -> None:
        with patch.dict(os.environ, {"LLM_LOCAL_MAX_CONCURRENCY": "3"}, clear=True):
            global_sem, model_sem = await get_semaphores("gpt-4o")
        assert global_sem is None
        assert model_sem is not None

    @pytest.mark.asyncio
    async def test_both_semaphores(self) -> None:
        with patch.dict(
            os.environ,
            {"LLM_GLOBAL_MAX_CONCURRENCY": "10", "LLM_LOCAL_MAX_CONCURRENCY": "2"},
            clear=True,
        ):
            global_sem, model_sem = await get_semaphores("claude-3")
        assert global_sem is not None
        assert model_sem is not None

    @pytest.mark.asyncio
    async def test_cached_per_model(self) -> None:
        with patch.dict(os.environ, {"LLM_LOCAL_MAX_CONCURRENCY": "3"}, clear=True):
            _, sem1 = await get_semaphores("gpt-4o")
            _, sem2 = await get_semaphores("gpt-4o")
        assert sem1 is sem2

    @pytest.mark.asyncio
    async def test_different_models_different_semaphores(self) -> None:
        with patch.dict(os.environ, {"LLM_LOCAL_MAX_CONCURRENCY": "3"}, clear=True):
            _, sem1 = await get_semaphores("gpt-4o")
            _, sem2 = await get_semaphores("claude-3")
        assert sem1 is not sem2

    @pytest.mark.asyncio
    async def test_global_initialized_only_once(self) -> None:
        import myrm_agent_harness.toolkits.llms.adapters.concurrency as mod

        with patch.dict(os.environ, {"LLM_GLOBAL_MAX_CONCURRENCY": "5"}, clear=True):
            await get_semaphores("a")
        assert mod._GLOBAL_SEMAPHORE_INITIALIZED is True
        first_sem = mod._GLOBAL_SEMAPHORE

        with patch.dict(os.environ, {"LLM_GLOBAL_MAX_CONCURRENCY": "100"}, clear=True):
            global_sem, _ = await get_semaphores("b")
        assert global_sem is first_sem

    @pytest.mark.asyncio
    async def test_invalid_env_values_ignored(self) -> None:
        with patch.dict(
            os.environ,
            {"LLM_GLOBAL_MAX_CONCURRENCY": "abc", "LLM_LOCAL_MAX_CONCURRENCY": "0"},
            clear=True,
        ):
            global_sem, model_sem = await get_semaphores("test")
        assert global_sem is None
        assert model_sem is None
