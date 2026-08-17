"""Tests for LLM identity metadata passthrough and capability-learning roundtrip.

``ManagedLLM`` / ``KeyPoolLLM`` wrappers expose ``model`` / ``model_name`` /
``api_base`` / ``base_url`` via passthrough properties, and ``ChatLiteLLM``
aliases ``base_url`` to ``api_base``.  This keeps the capability learner key
(model@api_base) stable across the middleware gate and the oneshot-recovery
learn path, so an unsupported ``allowed_tools`` tool_choice is remembered after
a single rejection and skipped on all subsequent calls.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain_core.language_models import BaseChatModel

from myrm_agent_harness.toolkits.llms.adapters.chat_model.model import ChatLiteLLM
from myrm_agent_harness.toolkits.llms.allowed_tools_capability import (
    CAPABILITY_REJECTS_ALLOWED_TOOLS,
    model_supports_allowed_tools_tool_choice,
    normalize_model_capability_key,
)
from myrm_agent_harness.toolkits.llms.capability_learner import (
    ModelCapabilityLearner,
    get_capability_learner,
)
from myrm_agent_harness.toolkits.llms.core.credential_pool import CredentialPool
from myrm_agent_harness.toolkits.llms.core.key_pool_llm import KeyPoolLLM
from myrm_agent_harness.toolkits.llms.fallback import ManagedLLM
from myrm_agent_harness.toolkits.llms.fallback.managed_llm import FallbackModel


@pytest.fixture(autouse=True)
def _reset_learner() -> None:
    ModelCapabilityLearner._instance = None
    yield
    ModelCapabilityLearner._instance = None


def _chat_llm(**kwargs: object) -> ChatLiteLLM:
    return ChatLiteLLM(
        model=str(kwargs.get("model", "gpt-4o")),
        api_base=(kwargs.get("api_base") or None),  # type: ignore[arg-type]
        model_name=(kwargs.get("model_name") or None),  # type: ignore[arg-type]
    )


class TestChatLiteLLMBaseUrlAlias:
    def test_base_url_aliases_api_base(self) -> None:
        llm = _chat_llm(model="gpt-4o", api_base="https://api-a.example.com/v1")
        assert llm.base_url == "https://api-a.example.com/v1"
        assert llm.base_url == llm.api_base

    def test_base_url_none_when_api_base_unset(self) -> None:
        llm = _chat_llm(model="gpt-4o")
        assert llm.base_url is None


class TestManagedLLMPassthrough:
    def test_identity_attributes_delegate_to_main_llm(self) -> None:
        inner = _chat_llm(
            model="gpt-4o",
            model_name="gpt-4o-v2",
            api_base="https://api-a.example.com/v1",
        )
        managed = ManagedLLM(main_llm=inner)
        assert managed.model == "gpt-4o"
        assert managed.model_name == "gpt-4o-v2"
        assert managed.api_base == "https://api-a.example.com/v1"
        assert managed.base_url == "https://api-a.example.com/v1"

    def test_identity_delegation_is_layer_agnostic(self) -> None:
        """Passthrough must also work when the main LLM is itself a wrapper."""
        inner = _chat_llm(model="gpt-4o", api_base="https://api-a.example.com/v1")
        outer = ManagedLLM(main_llm=inner)
        top = ManagedLLM(main_llm=outer)
        assert top.model == "gpt-4o"
        assert top.api_base == "https://api-a.example.com/v1"
        assert top.base_url == "https://api-a.example.com/v1"

    def test_base_url_falls_back_to_api_base_without_underlying_alias(self) -> None:
        inner = SimpleNamespace(
            model="gpt-4o",
            model_name="gpt-4o",
            api_base="https://api-a.example.com/v1",
        )
        managed = ManagedLLM(main_llm=inner)  # type: ignore[arg-type]
        assert managed.base_url == "https://api-a.example.com/v1"

    def test_rejects_both_fallback_llm_and_fallback_models(self) -> None:
        inner = _chat_llm(model="gpt-4o")
        fallback = _chat_llm(model="gpt-4o-mini")
        with pytest.raises(ValueError, match="both fallback_llm and fallback_models"):
            ManagedLLM(
                main_llm=inner,
                fallback_llm=fallback,
                fallback_models=[FallbackModel(llm=fallback, name="gpt-4o-mini")],
            )

    def test_multi_level_fallback_exposes_identifying_params(self) -> None:
        main = _chat_llm(model="gpt-4o", api_base="https://api.openai.com/v1")
        mini = _chat_llm(model="gpt-4o-mini")
        managed = ManagedLLM(
            main_llm=main,
            main_model_name="gpt-4o",
            fallback_models=[FallbackModel(llm=mini, name="gpt-4o-mini")],
        )
        params = managed._identifying_params
        assert params["main_model"] == "gpt-4o"
        assert params["fallback_models"] == ["gpt-4o-mini"]


class TestKeyPoolLLMPassthrough:
    def test_identity_attributes_delegate_to_primary_instance(self) -> None:
        pool = CredentialPool(["k1", "k2"])
        llm = _chat_llm(
            model="gpt-4o",
            model_name="gpt-4o-v2",
            api_base="https://api-a.example.com/v1",
        )
        kp = KeyPoolLLM(instances={"k1": llm, "k2": llm}, pool=pool)
        assert kp.model == "gpt-4o"
        assert kp.model_name == "gpt-4o-v2"
        assert kp.api_base == "https://api-a.example.com/v1"
        assert kp.base_url == "https://api-a.example.com/v1"


class TestCapabilityLearningRoundtrip:
    """End-to-end: middleware reads identity → rejection path learns → gate skips."""

    def test_managed_llm_unknown_endpoint_gates_fail_closed_and_learns(self) -> None:
        inner = _chat_llm(model="gpt-4o", api_base="https://custom.example.com/v1")
        managed = ManagedLLM(main_llm=inner)

        # Middleware identity extraction (same getattrs as the middleware).
        model_name = getattr(managed, "model", None) or getattr(
            managed, "model_name", None
        )
        api_base = getattr(managed, "api_base", None)
        assert model_name == "gpt-4o"
        assert api_base == "https://custom.example.com/v1"

        # Unknown/non-native endpoints fail closed — never send allowed_tools.
        assert (
            model_supports_allowed_tools_tool_choice(
                str(model_name), api_base=str(api_base or "")
            )
            is False
        )

        # The learner key stays scoped to model@api_base so the middleware.
        # check and this gate always agree.
        learner = get_capability_learner()
        key = normalize_model_capability_key(
            str(model_name), api_base=str(api_base or "")
        )
        assert key == "gpt-4o@https://custom.example.com/v1"
        assert learner.get(key, CAPABILITY_REJECTS_ALLOWED_TOOLS) is None

        # Only native OpenAI endpoint is opted in.
        assert (
            model_supports_allowed_tools_tool_choice(
                str(model_name), api_base="https://api.openai.com/v1"
            )
            is True
        )

    def test_managed_llm_local_endpoint_fails_closed(self) -> None:
        """Local dev proxies (the OpenCode Go Pool scenario) never send allowed_tools."""
        inner = _chat_llm(
            model="openai-like/OpenCode Go Pool", api_base="http://localhost:20128/v1"
        )
        managed = ManagedLLM(main_llm=inner)
        model_name = getattr(managed, "model", None) or getattr(
            managed, "model_name", None
        )
        api_base = getattr(managed, "api_base", None)
        assert model_name == "openai-like/OpenCode Go Pool"
        assert api_base == "http://localhost:20128/v1"
        assert (
            model_supports_allowed_tools_tool_choice(
                str(model_name), api_base=str(api_base or "")
            )
            is False
        )
        # Learning under the same scoped key remains consistent (no-op here).
        assert (
            model_supports_allowed_tools_tool_choice(
                str(model_name), api_base=str(api_base or "")
            )
            is False
        )

    def test_key_pool_llm_learns_then_gates(self) -> None:
        pool = CredentialPool(["k1", "k2"])
        inner = _chat_llm(model="gpt-4o", api_base="https://custom.example.com/v1")
        kp = KeyPoolLLM(instances={"k1": inner, "k2": inner}, pool=pool)

        model_name = getattr(kp, "model", None) or getattr(kp, "model_name", None)
        api_base = getattr(kp, "api_base", None)
        assert api_base == "https://custom.example.com/v1"

        learner = get_capability_learner()
        key = normalize_model_capability_key(
            str(model_name), api_base=str(api_base or "")
        )
        learner.learn(key, CAPABILITY_REJECTS_ALLOWED_TOOLS, True)

        assert (
            model_supports_allowed_tools_tool_choice(
                str(model_name), api_base=str(api_base or "")
            )
            is False
        )


def test_managed_llm_is_base_chat_model_subclass() -> None:
    """ManagedLLM must remain a BaseChatModel for LangChain compatibility."""
    inner = _chat_llm(model="gpt-4o")
    managed = ManagedLLM(main_llm=inner)
    assert isinstance(managed, BaseChatModel)


def test_key_pool_llm_is_base_chat_model_subclass() -> None:
    pool = CredentialPool(["k1"])
    llm = _chat_llm(model="gpt-4o")
    kp = KeyPoolLLM(instances={"k1": llm}, pool=pool)
    assert isinstance(kp, BaseChatModel)
