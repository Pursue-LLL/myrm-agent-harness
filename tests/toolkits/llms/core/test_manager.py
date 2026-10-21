from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.toolkits.llms.core.credential_pool import CredentialPoolStrategy
from myrm_agent_harness.toolkits.llms.core.manager import LLMManager


@pytest.fixture(autouse=True)
def _clear_llm_cache() -> None:
    LLMManager.clear_cache()
    yield
    LLMManager.clear_cache()


def _mock_litellm_model(*, api_key: str, **kwargs: object) -> MagicMock:
    model = MagicMock()
    model.model = f"model-{api_key}"
    return model


def _make_config(api_keys: list[str], strategy: str | CredentialPoolStrategy) -> SimpleNamespace:
    return SimpleNamespace(
        model="test-model",
        api_key=api_keys[0],
        base_url="https://example.invalid",
        model_kwargs={},
        api_keys=api_keys,
        credential_pool_strategy=strategy,
    )


def test_pooled_cache_is_order_sensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.llms.core.manager.create_litellm_model",
        _mock_litellm_model,
    )

    first = LLMManager._get_pooled_llm(
        model="test-model",
        api_keys=["key-a", "key-b"],
        base_url="https://example.invalid",
        temperature=0.2,
        streaming=False,
        credential_pool_strategy=CredentialPoolStrategy.ROUND_ROBIN,
    )
    second = LLMManager._get_pooled_llm(
        model="test-model",
        api_keys=["key-b", "key-a"],
        base_url="https://example.invalid",
        temperature=0.2,
        streaming=False,
        credential_pool_strategy=CredentialPoolStrategy.ROUND_ROBIN,
    )

    assert first is not second


def test_pooled_cache_is_strategy_sensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.llms.core.manager.create_litellm_model",
        _mock_litellm_model,
    )

    first = LLMManager._get_pooled_llm(
        model="test-model",
        api_keys=["key-a", "key-b"],
        base_url="https://example.invalid",
        temperature=0.2,
        streaming=False,
        credential_pool_strategy=CredentialPoolStrategy.ROUND_ROBIN,
    )
    second = LLMManager._get_pooled_llm(
        model="test-model",
        api_keys=["key-a", "key-b"],
        base_url="https://example.invalid",
        temperature=0.2,
        streaming=False,
        credential_pool_strategy=CredentialPoolStrategy.FILL_FIRST,
    )

    assert first is not second


@pytest.mark.asyncio
async def test_get_llm_from_config_uses_config_pool_strategy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.llms.core.manager.create_litellm_model",
        _mock_litellm_model,
    )

    config = _make_config(["key-a", "key-b"], "fill_first")
    llm = await LLMManager.get_llm_from_config(config, streaming=False)

    assert llm.credential_pool.strategy == CredentialPoolStrategy.FILL_FIRST


@pytest.mark.asyncio
async def test_get_llm_from_config_top_level_temperature_overrides_model_kwargs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _capturing_model(*, api_key: str, **kwargs: object) -> MagicMock:
        captured.update(kwargs)
        model = MagicMock()
        model.model = f"model-{api_key}"
        return model

    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.llms.core.manager.create_litellm_model",
        _capturing_model,
    )

    config = SimpleNamespace(
        model="test-model",
        api_key="key-a",
        base_url="https://example.invalid",
        temperature=0.5,
        model_kwargs={"temperature": 0.9, "max_tokens": 1024},
        api_keys=None,
        credential_pool_strategy=None,
    )

    await LLMManager.get_llm_from_config(config, streaming=False)

    assert captured["temperature"] == 0.5
    assert captured["max_tokens"] == 1024


@pytest.mark.asyncio
async def test_get_llm_from_config_keeps_model_kwargs_temperature_when_top_level_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _capturing_model(*, api_key: str, **kwargs: object) -> MagicMock:
        captured.update(kwargs)
        model = MagicMock()
        model.model = f"model-{api_key}"
        return model

    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.llms.core.manager.create_litellm_model",
        _capturing_model,
    )

    config = SimpleNamespace(
        model="test-model",
        api_key="key-a",
        base_url="https://example.invalid",
        temperature=None,
        model_kwargs={"temperature": 0.7},
        api_keys=None,
        credential_pool_strategy=None,
    )

    await LLMManager.get_llm_from_config(config, streaming=False)

    assert captured["temperature"] == 0.7


@pytest.mark.asyncio
async def test_get_llm_from_config_passes_top_level_reasoning_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _capturing_model(*, api_key: str, **kwargs: object) -> MagicMock:
        captured.update(kwargs)
        model = MagicMock()
        model.model = f"model-{api_key}"
        return model

    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.llms.core.manager.create_litellm_model",
        _capturing_model,
    )

    config = SimpleNamespace(
        model="deepseek/deepseek-v4-pro",
        api_key="key-a",
        base_url="https://example.invalid",
        temperature=None,
        reasoning_effort="max",
        model_kwargs={"reasoning_effort": "low"},
        api_keys=None,
        credential_pool_strategy=None,
    )

    await LLMManager.get_llm_from_config(config, streaming=False)

    assert captured["reasoning_effort"] == "max"
