from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, ChatMessage, HumanMessage, SystemMessage

from myrm_agent_harness.toolkits.llms.adapters.chat_model import ChatLiteLLM
from myrm_agent_harness.toolkits.llms.adapters.converters import convert_dict_to_message, convert_message_to_dict


def test_message_name_round_trip() -> None:
    message = SystemMessage(content="You are helpful.", name="MiniMax AI")

    message_dict = convert_message_to_dict(message)
    restored = convert_dict_to_message(message_dict)

    assert message_dict["role"] == "system"
    assert message_dict["name"] == "MiniMax AI"
    assert isinstance(restored, SystemMessage)
    assert restored.content == "You are helpful."
    assert restored.name == "MiniMax AI"


def test_minimax_system_messages_are_folded_into_first_human_turn() -> None:
    model = ChatLiteLLM.model_construct(
        client=MagicMock(),
        model="minimax/MiniMax-M2.5",
        api_base="https://api.minimaxi.com/v1",
        custom_llm_provider="minimax",
    )

    messages = [
        SystemMessage(content="You are a concise assistant."),
        HumanMessage(content="Hello"),
        SystemMessage(content="Answer in one paragraph."),
        AIMessage(content="Hi there."),
    ]

    message_dicts, params = model._create_message_dicts(messages, stop=None)

    assert params["api_base"] == "https://api.minimaxi.com/v1"
    assert [entry["role"] for entry in message_dicts] == ["user", "assistant"]
    assert message_dicts[0]["content"] == (
        "You are a concise assistant.\n\nAnswer in one paragraph.\n\nHello"
    )
    assert "name" not in message_dicts[0]
    assert message_dicts[1]["content"] == "Hi there."


def test_minimax_chat_message_system_role_is_folded_into_first_human_turn() -> None:
    model = ChatLiteLLM.model_construct(
        client=MagicMock(),
        model="minimax/MiniMax-M2.5",
        api_base="https://api.minimaxi.com/v1",
        custom_llm_provider="minimax",
    )

    messages = [
        ChatMessage(content="You are a concise assistant.", role="system"),
        HumanMessage(content="Hello"),
    ]

    message_dicts, _ = model._create_message_dicts(messages, stop=None)

    assert [entry["role"] for entry in message_dicts] == ["user"]
    assert message_dicts[0]["content"] == "You are a concise assistant.\n\nHello"
