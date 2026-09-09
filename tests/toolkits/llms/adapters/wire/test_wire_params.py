"""Unit tests for Responses wire parameter translation and URL sanitization."""

from __future__ import annotations

from myrm_agent_harness.toolkits.llms.adapters.wire.params import build_responses_kwargs


def test_build_responses_kwargs_strips_endpoint_suffixes_from_api_base() -> None:
    message_dicts = [{"role": "user", "content": "hello"}]

    # 1. Trailing /responses
    params_responses = {
        "model": "muse-spark-1.3-contributor",
        "api_base": "https://opencode.ai/zen/go/v1/responses",
    }
    kwargs = build_responses_kwargs(message_dicts, params_responses)
    assert kwargs["api_base"] == "https://opencode.ai/zen/go/v1"

    # 2. Trailing /responses/ with slash
    params_slash = {
        "model": "muse-spark-1.3-contributor",
        "api_base": "https://opencode.ai/zen/go/v1/responses/",
    }
    kwargs = build_responses_kwargs(message_dicts, params_slash)
    assert kwargs["api_base"] == "https://opencode.ai/zen/go/v1"

    # 3. Trailing /chat/completions
    params_chat = {
        "model": "muse-spark-1.3-contributor",
        "api_base": "https://opencode.ai/zen/v1/chat/completions",
    }
    kwargs = build_responses_kwargs(message_dicts, params_chat)
    assert kwargs["api_base"] == "https://opencode.ai/zen/v1"

    # 4. Clean base URL remains unchanged
    params_clean = {
        "model": "muse-spark-1.3-contributor",
        "api_base": "https://opencode.ai/zen/go/v1",
    }
    kwargs = build_responses_kwargs(message_dicts, params_clean)
    assert kwargs["api_base"] == "https://opencode.ai/zen/go/v1"
