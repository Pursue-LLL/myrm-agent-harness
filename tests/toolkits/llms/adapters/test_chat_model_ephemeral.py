from myrm_agent_harness.toolkits.llms.adapters.chat_model import ChatLiteLLM

# ---------------------------------------------------------------------------
# _apply_ephemeral_output_override unit tests
# ---------------------------------------------------------------------------


def test_apply_ephemeral_override_sets_max_tokens():
    """When ContextVar is set, _apply_ephemeral_output_override applies it and resets."""
    from myrm_agent_harness.agent.streaming.recovery.stream_recovery_truncation import (
        get_ephemeral_max_output_tokens,
        set_ephemeral_max_output_tokens,
    )

    set_ephemeral_max_output_tokens(16000)
    params: dict[str, object] = {"max_tokens": 4000}

    ChatLiteLLM._apply_ephemeral_output_override(params)

    assert params["max_tokens"] == 16000
    assert get_ephemeral_max_output_tokens() is None


def test_bind_tools_local_grammar_transport():
    """Verify local weak endpoints receive constrained response_format schema."""
    local_model = ChatLiteLLM(
        model="qwen2.5-coder:7b",
        api_base="http://127.0.0.1:11434/v1",
        custom_llm_provider="openai-like",
    )
    test_tool = {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run bash command",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    }
    bound = local_model.bind_tools([test_tool])
    assert "response_format" in bound.kwargs
    rf = bound.kwargs["response_format"]
    assert rf.get("type") == "json_schema"
    assert rf.get("json_schema", {}).get("name") == "tool_calls_transport"

    # Cloud models must NOT have forced local response_format
    cloud_model = ChatLiteLLM(
        model="gpt-4o",
        api_base="https://api.openai.com/v1",
        custom_llm_provider="openai",
    )
    bound_cloud = cloud_model.bind_tools([test_tool])
    assert "response_format" not in bound_cloud.kwargs
