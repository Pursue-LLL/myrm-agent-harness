"""Tests for core.config.llm — framework-agnostic LLM configuration.

Covers CustomModelDef and LLMConfig: construction, validation, immutability,
from_env(), and type identity with the agent.config.llm re-export.
"""


import pytest
from pydantic import ValidationError

from myrm_agent_harness.core.config.llm import CustomModelDef, LLMConfig


class TestCustomModelDef:
    def test_basic_creation(self) -> None:
        d = CustomModelDef(model_id="ollama/llama3.2")
        assert d.model_id == "ollama/llama3.2"
        assert d.context_length == 8192
        assert d.max_tokens == 4096
        assert d.supports_tools is True
        assert d.supports_streaming is True
        assert d.supports_vision is False
        assert d.supports_video is False

    def test_custom_values(self) -> None:
        d = CustomModelDef(
            model_id="vllm/qwen2.5-72b",
            context_length=131072,
            max_tokens=16384,
            supports_vision=True,
            supports_video=True,
        )
        assert d.context_length == 131072
        assert d.max_tokens == 16384
        assert d.supports_vision is True
        assert d.supports_video is True

    def test_frozen_immutability(self) -> None:
        d = CustomModelDef(model_id="test")
        with pytest.raises(AttributeError):
            d.context_length = 999  # type: ignore[misc]

    def test_equality(self) -> None:
        a = CustomModelDef(model_id="x", context_length=100)
        b = CustomModelDef(model_id="x", context_length=100)
        assert a == b

    def test_hashable(self) -> None:
        d = CustomModelDef(model_id="x")
        s = {d}
        assert d in s


class TestLLMConfig:
    def test_basic_creation(self) -> None:
        c = LLMConfig(model="gpt-4", api_key="sk-test")
        assert c.model == "gpt-4"
        assert c.api_key == "sk-test"
        assert c.base_url is None
        assert c.temperature is None
        assert c.streaming is True
        assert c.max_context_tokens is None
        assert c.supports_vision is False
        assert c.supports_video is False
        assert c.custom_model_def is None

    def test_all_fields(self) -> None:
        custom = CustomModelDef(model_id="ollama/test")
        c = LLMConfig(
            model="test",
            api_key="key",
            base_url="http://localhost:8080",
            temperature=0.5,
            streaming=False,
            model_kwargs={"top_p": 0.9},
            max_context_tokens=128000,
            supports_vision=True,
            supports_video=True,
            custom_model_def=custom,
        )
        assert c.base_url == "http://localhost:8080"
        assert c.temperature == 0.5
        assert c.streaming is False
        assert c.model_kwargs == {"top_p": 0.9}
        assert c.max_context_tokens == 128000
        assert c.supports_vision is True
        assert c.supports_video is True
        assert c.custom_model_def is custom

    def test_frozen_immutability(self) -> None:
        c = LLMConfig(model="gpt-4", api_key="key")
        with pytest.raises(ValidationError):
            c.model = "other"  # type: ignore[misc]

    def test_model_required(self) -> None:
        with pytest.raises(ValidationError):
            LLMConfig(model="", api_key="key")

    def test_api_key_required(self) -> None:
        with pytest.raises(ValidationError):
            LLMConfig(model="gpt-4", api_key="")

    def test_from_env_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYRM_MODEL_NAME", "gpt-4o")
        monkeypatch.setenv("MYRM_API_KEY", "sk-test-123")
        monkeypatch.setenv("MYRM_BASE_URL", "https://api.example.com")
        monkeypatch.setenv("MYRM_TEMPERATURE", "0.7")
        monkeypatch.setenv("MYRM_STREAMING", "false")
        monkeypatch.setenv("MYRM_MAX_CONTEXT_TOKENS", "64000")

        c = LLMConfig.from_env()
        assert c.model == "gpt-4o"
        assert c.api_key == "sk-test-123"
        assert c.base_url == "https://api.example.com"
        assert c.temperature == 0.7
        assert c.streaming is False
        assert c.max_context_tokens == 64000

    def test_from_env_minimal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYRM_MODEL_NAME", "claude-3")
        monkeypatch.setenv("MYRM_API_KEY", "sk-abc")

        c = LLMConfig.from_env()
        assert c.model == "claude-3"
        assert c.streaming is True

    def test_from_env_missing_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MYRM_MODEL_NAME", raising=False)
        monkeypatch.setenv("MYRM_API_KEY", "key")

        with pytest.raises(ValueError, match="MYRM_MODEL_NAME"):
            LLMConfig.from_env()

    def test_from_env_missing_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYRM_MODEL_NAME", "gpt-4")
        monkeypatch.delenv("MYRM_API_KEY", raising=False)

        with pytest.raises(ValueError, match="MYRM_API_KEY"):
            LLMConfig.from_env()

    def test_hashable(self) -> None:
        c = LLMConfig(model="gpt-4", api_key="key")
        s = {c}
        assert c in s


class TestLLMConfigValidators:
    """Tests for field validators: _strip_whitespace and _normalize_base_url."""

    def test_model_strip_whitespace(self) -> None:
        c = LLMConfig(model="  gpt-4  ", api_key="key")
        assert c.model == "gpt-4"

    def test_api_key_strip_whitespace(self) -> None:
        c = LLMConfig(model="gpt-4", api_key="  sk-abc123  ")
        assert c.api_key == "sk-abc123"

    def test_base_url_strip_trailing_slash(self) -> None:
        c = LLMConfig(model="m", api_key="k", base_url="https://api.openai.com/v1/")
        assert c.base_url == "https://api.openai.com/v1"

    def test_base_url_strip_multiple_trailing_slashes(self) -> None:
        c = LLMConfig(model="m", api_key="k", base_url="https://api.example.com///")
        assert c.base_url == "https://api.example.com"

    def test_base_url_strip_whitespace_and_slash(self) -> None:
        c = LLMConfig(model="m", api_key="k", base_url="  https://api.example.com/  ")
        assert c.base_url == "https://api.example.com"

    def test_base_url_empty_string_becomes_none(self) -> None:
        c = LLMConfig(model="m", api_key="k", base_url="")
        assert c.base_url is None

    def test_base_url_whitespace_only_becomes_none(self) -> None:
        c = LLMConfig(model="m", api_key="k", base_url="   ")
        assert c.base_url is None

    def test_base_url_single_slash_becomes_none(self) -> None:
        c = LLMConfig(model="m", api_key="k", base_url="/")
        assert c.base_url is None

    def test_base_url_none_stays_none(self) -> None:
        c = LLMConfig(model="m", api_key="k", base_url=None)
        assert c.base_url is None

    def test_model_whitespace_only_fails_min_length(self) -> None:
        with pytest.raises(ValidationError):
            LLMConfig(model="   ", api_key="key")

    def test_api_key_whitespace_only_fails_min_length(self) -> None:
        with pytest.raises(ValidationError):
            LLMConfig(model="gpt-4", api_key="   ")


class TestReExportTypeIdentity:
    """Verify that core.config types and agent.config re-exports are identical objects."""

    def test_llm_config_identity(self) -> None:
        from myrm_agent_harness.agent.config.llm import LLMConfig as AgentLLMConfig

        assert LLMConfig is AgentLLMConfig

    def test_custom_model_def_identity(self) -> None:
        from myrm_agent_harness.agent.config.llm import (
            CustomModelDef as AgentCustomModelDef,
        )

        assert CustomModelDef is AgentCustomModelDef

    def test_isinstance_cross_module(self) -> None:
        from myrm_agent_harness.agent.config.llm import LLMConfig as AgentLLMConfig

        c = LLMConfig(model="gpt-4", api_key="key")
        assert isinstance(c, AgentLLMConfig)

        c2 = AgentLLMConfig(model="gpt-4", api_key="key2")
        assert isinstance(c2, LLMConfig)

    def test_custom_model_def_isinstance_cross_module(self) -> None:
        from myrm_agent_harness.agent.config.llm import (
            CustomModelDef as AgentCustomModelDef,
        )

        d = CustomModelDef(model_id="test")
        assert isinstance(d, AgentCustomModelDef)

    def test_package_init_reexport(self) -> None:
        from myrm_agent_harness.core.config import CustomModelDef as PkgCustomModelDef
        from myrm_agent_harness.core.config import LLMConfig as PkgLLMConfig

        assert LLMConfig is PkgLLMConfig
        assert CustomModelDef is PkgCustomModelDef
