"""Tests for create_litellm_model factory, including attribution headers and parameter handling."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.llms.core.llm import create_litellm_model


def test_vercel_ai_gateway_attribution_headers() -> None:
    """Verify Vercel AI Gateway requests automatically inject attribution headers."""
    model = create_litellm_model(
        model="gpt-4o",
        base_url="https://ai-gateway.vercel.sh/v1",
        api_key="sk-test",
    )
    extra_headers = (model.model_kwargs or {}).get("extra_headers", {})
    assert extra_headers.get("HTTP-Referer") == "https://myrm.ai"
    assert extra_headers.get("X-Title") == "Myrm Agent"
    assert extra_headers.get("User-Agent") == "Myrm/1.0 (Vercel-AI-Gateway-Client)"


def test_openrouter_attribution_headers_by_url() -> None:
    """Verify OpenRouter requests by base_url inject attribution headers."""
    model = create_litellm_model(
        model="anthropic/claude-3.5-sonnet",
        base_url="https://openrouter.ai/api/v1",
        api_key="sk-or-test",
    )
    extra_headers = (model.model_kwargs or {}).get("extra_headers", {})
    assert extra_headers.get("HTTP-Referer") == "https://myrm.ai"
    assert extra_headers.get("X-Title") == "Myrm Agent"


def test_openrouter_attribution_headers_by_prefix() -> None:
    """Verify OpenRouter requests by openrouter/ model prefix inject attribution headers."""
    model = create_litellm_model(
        model="openrouter/google/gemini-2.0-flash",
        api_key="sk-or-test",
    )
    extra_headers = (model.model_kwargs or {}).get("extra_headers", {})
    assert extra_headers.get("HTTP-Referer") == "https://myrm.ai"
    assert extra_headers.get("X-Title") == "Myrm Agent"
