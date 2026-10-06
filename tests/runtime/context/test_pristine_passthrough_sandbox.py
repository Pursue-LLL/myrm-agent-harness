"""Tests for Raw Model Direct Passthrough and Pristine Testing Sandbox."""

from __future__ import annotations

from myrm_agent_harness.runtime.context.pristine_passthrough_sandbox import (
    PristineExecutionConfig,
    PristinePassthroughMode,
    PristineTestingSandbox,
    RawModelPassthroughTransformer,
)


def test_raw_model_passthrough_transformer_pristine_mode():
    history_messages = [
        {"role": "system", "content": "Old framework prompt to be stripped"},
        {"role": "user", "content": "Who are you?"},
        {"role": "assistant", "content": "I am an AI assistant."},
    ]
    agent_prompt = "You are Myrm Agent equipped with bash and python tools."
    tools = [{"name": "bash", "description": "Run shell command"}]

    config = PristineExecutionConfig(
        mode=PristinePassthroughMode.RAW_PASSTHROUGH,
        strip_agent_system_prompt=True,
        strip_tools=True,
        custom_system_prompt=None,
    )

    payload = RawModelPassthroughTransformer.transform_for_execution(
        messages=history_messages,
        config=config,
        agent_system_prompt=agent_prompt,
        available_tools=tools,
    )

    assert payload.is_pristine is True
    assert payload.tools_provided is False
    assert payload.system_prompt_used is None
    # All system messages stripped, only pure user and assistant messages retained
    roles = [m["role"] for m in payload.messages]
    assert roles == ["user", "assistant"]
    assert payload.messages[0]["content"] == "Who are you?"


def test_raw_model_passthrough_with_custom_system_prompt():
    history_messages = [{"role": "user", "content": "Solve 2+2"}]
    custom_sys = "You are a pure mathematics professor."

    config = PristineExecutionConfig(
        mode=PristinePassthroughMode.RAW_PASSTHROUGH,
        strip_agent_system_prompt=True,
        strip_tools=True,
        custom_system_prompt=custom_sys,
    )

    payload = RawModelPassthroughTransformer.transform_for_execution(
        messages=history_messages,
        config=config,
        agent_system_prompt="Agent scaffold prompt",
        available_tools=[{"name": "eval", "description": "calculator"}],
    )

    assert payload.is_pristine is True
    assert payload.tools_provided is False
    assert payload.system_prompt_used == custom_sys
    assert len(payload.messages) == 2
    assert payload.messages[0]["role"] == "system"
    assert payload.messages[0]["content"] == custom_sys
    assert payload.messages[1]["role"] == "user"


def test_agent_augmented_mode_preserves_framework_prompts_and_tools():
    history_messages = [{"role": "user", "content": "Build an API"}]
    agent_prompt = "You are Myrm Senior Full-Stack Agent."
    tools = [{"name": "write_file", "description": "Write code to file"}]

    config = PristineExecutionConfig(
        mode=PristinePassthroughMode.AGENT_AUGMENTED,
    )

    payload = RawModelPassthroughTransformer.transform_for_execution(
        messages=history_messages,
        config=config,
        agent_system_prompt=agent_prompt,
        available_tools=tools,
    )

    assert payload.is_pristine is False
    assert payload.tools_provided is True
    assert payload.system_prompt_used == agent_prompt
    assert payload.messages[0]["role"] == "system"
    assert payload.messages[0]["content"] == agent_prompt
    assert payload.messages[1]["role"] == "user"


def test_side_by_side_dual_track_experiment():
    prompt = "Write a complete web server in Python and verify it."

    def mock_raw_runner(p: str) -> tuple[str, int, float]:
        assert p == prompt
        return ("Here is raw code using http.server...", 300, 150.0)

    def mock_augmented_runner(p: str) -> tuple[str, int, int, float]:
        assert p == prompt
        return ("Created server.py, wrote unit tests, and verified via curl.", 1200, 3, 450.0)

    report = PristineTestingSandbox.run_side_by_side_experiment(
        prompt=prompt,
        raw_runner=mock_raw_runner,
        augmented_runner=mock_augmented_runner,
        experiment_id="exp-test-01",
    )

    assert report.experiment_id == "exp-test-01"
    assert report.prompt == prompt
    assert "Here is raw code" in report.raw_response
    assert "Created server.py" in report.augmented_response
    assert report.raw_tokens == 300
    assert report.augmented_tokens == 1200
    assert report.tools_invoked_count == 3
    assert report.raw_latency_ms == 150.0
    assert report.augmented_latency_ms == 450.0
    assert report.token_overhead_ratio == 4.0
