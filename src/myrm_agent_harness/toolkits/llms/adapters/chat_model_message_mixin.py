"""ChatLiteLLM message conversion and response assembly mixin.

[INPUT]
- adapters.converters (POS: message and tool call converters)
- adapters.model_capability (POS: reasoning_content echo requirements)
- adapters.safety_termination_detector (POS: safety termination on truncated tool_calls)
- adapters.chat_model_exceptions (POS: role patterns and EmptyChoicesError)

[OUTPUT]
- ChatLiteLLMMessageMixin: _create_message_dicts, normalize, stamp, ChatResult assembly

[POS]
Message normalization and response assembly for ChatLiteLLM. Provider-aware system
demotion/promotion and reasoning_content stamping live here to keep the hot path in one module.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from myrm_agent_harness.toolkits.llms.adapters.converters import (
    convert_dict_to_message,
    convert_message_to_dict,
    create_usage_metadata,
)
from myrm_agent_harness.toolkits.llms.adapters.tool_recovery import (
    build_final_tool_call_chunk as _build_final_tool_call_chunk_fn,
)

from myrm_agent_harness.toolkits.llms.adapters.chat_model_exceptions import (
    EmptyChoicesError,
    _DEVELOPER_ROLE_PATTERN,
    _SYSTEM_MESSAGE_DENYLIST_HINTS,
)
from myrm_agent_harness.toolkits.llms.adapters.model_capability import ModelCapabilityDetector
from myrm_agent_harness.toolkits.llms.adapters.safety_termination_detector import (
    detect_safety_termination,
    suppress_tool_calls_for_safety,
)

logger = logging.getLogger(__name__)

_capability_detector = ModelCapabilityDetector()


class ChatLiteLLMMessageMixin:
    def _convert_response_to_dict(self, response: Any) -> dict[str, Any]:
        if isinstance(response, dict):
            return response
        if hasattr(response, "model_dump"):
            return response.model_dump()
        if hasattr(response, "dict"):
            return response.dict()
        raise ValueError(f"Unable to convert LiteLLM response to dict. Type: {type(response)}")

    def _build_empty_choices_error(self, response: Mapping[str, Any]) -> str:
        error_msg = response.get("error", {})
        error_code = response.get("code", "")
        error_type = response.get("type", "")
        original_error = response.get("original_exception", "")

        parts = [
            f"LiteLLM returned empty choices. Model: {self.model_name or self.model}",
            f"Response keys: {list(response.keys())}",
        ]

        if error_msg:
            parts.append(f"Error: {error_msg}")
        if error_code:
            parts.append(f"Error Code: {error_code}")
        if error_type:
            parts.append(f"Error Type: {error_type}")
        if original_error:
            parts.append(f"Original Exception: {original_error}")
        parts.append(f"Full Response: {response}")

        return "\n".join(parts)

    def _extract_tool_context_from_kwargs(
        self,
        kwargs: dict[str, Any],
    ) -> tuple[list[str] | None, dict[str, dict[str, Any]] | None]:
        logger.debug(f"_extract_tool_context_from_kwargs keys: {list(kwargs.keys())}")
        tools = kwargs.get("tools")
        if not tools:
            logger.debug(f"tools is empty or not in kwargs. kwargs keys: {list(kwargs.keys())}")
            return None, None

        tool_names: list[str] = []
        tool_schemas: dict[str, dict[str, Any]] = {}
        for tool in tools:
            if isinstance(tool, dict) and "function" in tool:
                name = tool["function"].get("name")
                if name:
                    tool_names.append(name)
                    tool_schemas[name] = tool

        logger.debug(f"extracted tool_names: {tool_names}")
        return (
            tool_names if tool_names else None,
            tool_schemas if tool_schemas else None,
        )

    def _build_final_tool_call_chunk(
        self,
        raw_tool_calls: Sequence[Mapping[str, Any]],
        tool_schemas: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> tuple[ChatGenerationChunk | None, list[dict[str, Any]], list[dict[str, Any]]]:
        return _build_final_tool_call_chunk_fn(raw_tool_calls, tool_schemas)

    @staticmethod
    def _stringify_message_content(content: object) -> str:
        if isinstance(content, str):
            return content.strip()

        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, str):
                    text = block.strip()
                    if text:
                        parts.append(text)
                elif isinstance(block, dict):
                    text = block.get("text")
                    if isinstance(text, str):
                        text = text.strip()
                        if text:
                            parts.append(text)
                else:
                    text = str(block).strip()
                    if text:
                        parts.append(text)
            return "\n".join(parts)

        return str(content).strip()

    @staticmethod
    def _is_system_role_message(message: object) -> bool:
        """Return True when a message should be treated as a system turn.

        LangChain history can surface system instructions through several
        concrete message shapes. We normalize every system-like role here so
        provider-specific compatibility stays centralized in the adapter.
        """
        if isinstance(message, SystemMessage):
            return True

        if isinstance(message, Mapping):
            role = message.get("role")
        else:
            role = getattr(message, "role", None)
            if role is None:
                role = getattr(message, "type", None)

        return isinstance(role, str) and role.lower() == "system"

    def _create_message_dicts(
        self, messages: list[BaseMessage], stop: list[str] | None
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        params = self._client_params
        if stop is not None:
            if "stop" in params:
                raise ValueError("`stop` found in both the input and default params.")
            params["stop"] = stop
        message_dicts = [convert_message_to_dict(m) for m in self._normalize_messages_for_provider(messages)]
        if self._should_promote_system_to_developer() and message_dicts:
            first = message_dicts[0]
            if isinstance(first, dict) and first.get("role") == "system":
                first["role"] = "developer"
        self._stamp_missing_reasoning_content(message_dicts)
        return message_dicts, params

    def _stamp_missing_reasoning_content(self, message_dicts: list[dict[str, Any]]) -> None:
        """Back-fill empty reasoning_content on assistant messages for thinking-mode models.

        DeepSeek/Kimi/MiMo APIs reject requests where assistant messages lack
        the reasoning_content field when thinking mode is active. This stamps
        an empty string on messages missing the field, enabling model-switch
        and session-restore scenarios without 400 errors.
        Skipped for non-thinking models to avoid prefix-cache churn.
        """
        if not _capability_detector.needs_reasoning_content_echo(
            provider=self.custom_llm_provider or "",
            model=self._get_model_name(),
            base_url=self.api_base or "",
        ):
            return
        for msg in message_dicts:
            if msg.get("role") == "assistant" and "reasoning_content" not in msg:
                msg["reasoning_content"] = ""

    def _normalize_messages_for_provider(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        """Normalize outbound messages for provider-specific role quirks.

        MiniMax rejects direct system messages in the current chat/completions
        path, so we fold all system instructions into the first human turn.
        This preserves the instruction content while keeping the outbound role
        sequence valid for the provider.
        """
        if not self._should_demote_system_messages():
            return messages

        system_parts: list[str] = []
        for message in messages:
            if self._is_system_role_message(message):
                text = self._stringify_message_content(message.content)
                if text:
                    system_parts.append(text)

        if not system_parts:
            return [message for message in messages if not self._is_system_role_message(message)]

        merged_system = "\n\n".join(system_parts)
        normalized: list[BaseMessage] = []
        human_rewritten = False

        for message in messages:
            if self._is_system_role_message(message):
                continue

            if not human_rewritten and isinstance(message, HumanMessage):
                content = message.content
                if isinstance(content, list):
                    merged_content: str | list[object] = [
                        {"type": "text", "text": merged_system},
                        *content,
                    ]
                else:
                    merged_content = f"{merged_system}\n\n{content}" if content else merged_system

                normalized.append(
                    HumanMessage(
                        content=merged_content,
                        additional_kwargs=dict(getattr(message, "additional_kwargs", {}) or {}),
                        response_metadata=dict(getattr(message, "response_metadata", {}) or {}),
                        name=getattr(message, "name", None),
                        id=getattr(message, "id", None),
                    )
                )
                human_rewritten = True
            else:
                normalized.append(message)

        if human_rewritten:
            return normalized

        return [HumanMessage(content=merged_system), *normalized]

    def _should_demote_system_messages(self) -> bool:
        model_name = self._get_model_name().lower()
        api_base = (self.api_base or "").lower()
        provider = (self.custom_llm_provider or "").lower()
        combined = " ".join((model_name, api_base, provider))
        return any(hint in combined for hint in _SYSTEM_MESSAGE_DENYLIST_HINTS)

    def _should_promote_system_to_developer(self) -> bool:
        """Whether to promote ``system`` role to ``developer`` for the current model.

        OpenAI GPT-5+, Codex, and o-series models give stronger instruction-following
        weight to ``developer`` role.  Some Codex endpoints reject ``system`` outright.
        This is mutually exclusive with ``_should_demote_system_messages`` (MiniMax path).
        """
        if self._should_demote_system_messages():
            return False
        model_name = self._get_model_name().lower()
        bare_model = model_name.rsplit("/", maxsplit=1)[-1]
        return bool(_DEVELOPER_ROLE_PATTERN.match(bare_model))

    def _create_chat_result(
        self,
        response: Mapping[str, Any],
        available_tools: list[str] | None = None,
        tool_schemas: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> ChatResult:
        generations: list[ChatGeneration] = []
        token_usage = response.get("usage", {})
        choices = response.get("choices", [])

        if not choices:
            raise EmptyChoicesError(self._build_empty_choices_error(response))

        for choice in choices:
            finish_reason = choice.get("finish_reason")

            # Safety termination: suppress truncated tool_calls before message
            # conversion to prevent corrupt arguments from being dispatched.
            has_tool_calls = choice.get("message", {}).get("tool_calls")
            if finish_reason and detect_safety_termination(finish_reason) and has_tool_calls:
                suppress_tool_calls_for_safety(choice["message"], finish_reason)

            try:
                message = convert_dict_to_message(choice["message"], available_tools, tool_schemas)
            except Exception as e:
                logger.error(f" Failed to convert message: {type(e).__name__} - {e!s}")
                raise

            if isinstance(message, AIMessage):
                message.response_metadata = {"model_name": self.model_name or self.model}
                message.usage_metadata = create_usage_metadata(token_usage)

            generations.append(
                ChatGeneration(
                    message=message,
                    generation_info=dict(finish_reason=choice.get("finish_reason")),
                )
            )

        set_model_value = self.model_name or self.model
        llm_output = {"token_usage": token_usage, "model": set_model_value}
        return ChatResult(generations=generations, llm_output=llm_output)

