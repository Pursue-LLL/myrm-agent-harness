"""Credential helpers for real-LLM e2e tests.

Lives outside ``conftest.py`` so test modules can import it by path-independent
name; several ``conftest.py`` files exist across the suite, so ``from conftest
import ...`` does not resolve.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_ENV_TEST = Path(__file__).resolve().parents[4] / "myrm-agent" / "myrm-agent-server" / ".env.test"

_OPENAI_COMPAT = {"openai-like", "openai_compatible", "openai-compatible", "openai_like"}


def normalize_model(raw: str) -> tuple[str, str | None]:
    """Convert env model names (e.g. openai-like/X) to LiteLLM (openai/X, provider)."""
    if "/" in raw:
        prefix, model = raw.split("/", 1)
        if prefix in _OPENAI_COMPAT:
            return f"openai/{model}", "openai"
        return raw, None
    return raw, None


def litellm_config_for(key_prefix: str) -> tuple[str, str, str, str | None]:
    """Return ``(api_key, base_url, litellm_model, provider)`` for raw litellm calls."""
    api_key = os.environ.get(f"{key_prefix}_API_KEY", "")
    base_url = os.environ.get(f"{key_prefix}_BASE_URL", "")
    model = os.environ.get(f"{key_prefix}_MODEL", "")
    if not all([api_key, base_url, model]):
        pytest.skip(f"{key_prefix}_API_KEY/BASE_URL/MODEL not configured")
    litellm_model, provider = normalize_model(model)
    return api_key, base_url, litellm_model, provider