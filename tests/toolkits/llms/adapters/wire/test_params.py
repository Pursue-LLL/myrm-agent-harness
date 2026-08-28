"""Tests for Responses wire params builder."""

from myrm_agent_harness.toolkits.llms.adapters.wire.params import build_responses_kwargs


def test_build_responses_kwargs_passes_include_from_extra_body() -> None:
    kwargs = build_responses_kwargs(
        [{"role": "user", "content": "hi"}],
        {
            "model": "openai/muse-spark-1.2-contributor",
            "extra_body": {
                "reasoning": {"effort": "low"},
                "include": ["reasoning.encrypted_content"],
            },
        },
    )
    assert kwargs["include"] == ["reasoning.encrypted_content"]
    assert kwargs["reasoning"] == {"effort": "low"}


def test_build_responses_kwargs_maps_optional_fields() -> None:
    kwargs = build_responses_kwargs(
        [
            {"role": "system", "content": "Be concise"},
            {"role": "user", "content": "hello"},
        ],
        {
            "model": "openai/muse-spark-1.2-contributor",
            "max_tokens": 256,
            "reasoning_effort": "medium",
            "api_key": "sk-test",
            "api_base": "https://opencode.ai/zen/go/v1",
            "stream": True,
            "tools": [{"type": "function", "function": {"name": "web_search"}}],
            "tool_choice": "auto",
            "temperature": 0.2,
            "top_p": 0.9,
            "force_timeout": 30,
            "extra_headers": {"X-Test": "1"},
        },
    )
    assert kwargs["instructions"] == "Be concise"
    assert kwargs["max_output_tokens"] == 512
    assert kwargs["reasoning"] == {"effort": "medium"}
    assert kwargs["stream"] is True
    assert kwargs["tools"][0]["function"]["name"] == "web_search"
    assert kwargs["tool_choice"] == "auto"
    assert kwargs["temperature"] == 0.2
    assert kwargs["top_p"] == 0.9
    assert kwargs["timeout"] == 30
    assert kwargs["extra_headers"] == {"X-Test": "1"}


def test_build_responses_kwargs_uses_timeout_param() -> None:
    kwargs = build_responses_kwargs([{"role": "user", "content": "hi"}], {"model": "m", "timeout": 42})
    assert kwargs["timeout"] == 42
