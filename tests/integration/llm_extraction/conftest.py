"""Shared fixtures for real-LLM e2e integration tests of the content-extraction layer.

Loads credentials from ``myrm-agent/myrm-agent-server/.env.test`` (the same
file pytest uses for server-side integration/e2e suites) and builds real
``ChatLiteLLM`` instances for the BASIC (agnes hub) and LITE (minimax) model
lanes. Tests that require a real model must opt in via ``@pytest.mark.e2e``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_ENV_TEST = Path(__file__).resolve().parents[4] / "myrm-agent" / "myrm-agent-server" / ".env.test"

_OPENAI_COMPAT = {"openai-like", "openai_compatible", "openai-compatible", "openai_like"}


def _normalize_model(raw: str) -> tuple[str, str | None]:
    """Convert env model names (e.g. openai-like/X) to LiteLLM (openai/X, provider)."""
    if "/" in raw:
        prefix, model = raw.split("/", 1)
        if prefix in _OPENAI_COMPAT:
            return f"openai/{model}", "openai"
        return raw, None
    return raw, None


@pytest.fixture(autouse=True)
def _load_env_test() -> None:
    """Load .env.test into the process environment (never overriding existing vars)."""
    if not _ENV_TEST.exists():
        pytest.skip(f"{_ENV_TEST} not found — real-LLM e2e cannot run")
    for line in _ENV_TEST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        if key and value:
            os.environ.setdefault(key, value)


def build_litellm_for(key_prefix: str):
    """Build a real ChatLiteLLM from ``<PREFIX>_API_KEY/BASE_URL/MODEL`` env vars."""
    api_key, base_url, litellm_model, provider = litellm_config_for(key_prefix)
    from myrm_agent_harness.toolkits.llms.adapters.chat_model import ChatLiteLLM

    return ChatLiteLLM(
        model=litellm_model,
        api_key=api_key,
        api_base=base_url,
        custom_llm_provider=provider,
        temperature=0.0,
        max_tokens=4096,
    )


def litellm_config_for(key_prefix: str) -> tuple[str, str, str, str | None]:
    """Return ``(api_key, base_url, litellm_model, provider)`` for raw litellm calls."""
    api_key = os.environ.get(f"{key_prefix}_API_KEY", "")
    base_url = os.environ.get(f"{key_prefix}_BASE_URL", "")
    model = os.environ.get(f"{key_prefix}_MODEL", "")
    if not all([api_key, base_url, model]):
        pytest.skip(f"{key_prefix}_API_KEY/BASE_URL/MODEL not configured")
    litellm_model, provider = _normalize_model(model)
    return api_key, base_url, litellm_model, provider


@pytest.fixture
def basic_llm():
    """Real LLM on the BASIC lane (agnes hub by default)."""
    return build_litellm_for("BASIC")


@pytest.fixture
def lite_llm():
    """Real LLM on the LITE lane (minimax by default)."""
    return build_litellm_for("LITE")
