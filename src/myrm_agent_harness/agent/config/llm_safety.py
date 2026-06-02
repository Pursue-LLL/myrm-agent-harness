"""Provider Safety — normalize messages before LLM calls.

Inspired by lime's provider_safety.rs, adapted for LangChain architecture.

[INPUT]
- langchain_core.messages::BaseMessage, (POS: Core message type definitions. All cross-channel communication data structures are defined here; zero I/O, pure data.)

[OUTPUT]
- normalize_messages(): Clean invalid tool calls and orphan responses
- SafetyWrappedChatModel: Transparent BaseChatModel wrapper

[POS]
Provider safety layer. Prevents API errors from invalid tool calls and dirty conversation history.
Transparent wrapper — zero configuration required, automatically applied by framework.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, cast

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage
    from langchain_core.outputs import ChatResult

logger = get_agent_logger(__name__)


def normalize_messages(messages: Sequence[BaseMessage]) -> list[BaseMessage]:
    """Normalize message chain before sending to LLM provider.

    Removes:
    1. Invalid tool requests (wrong role or failed parsing)
    2. Orphan tool responses (no matching request)
    3. Duplicate tool responses (multiple responses for same request)

    Ensures strict tool request-response pairing.

    Args:
        messages: Original message sequence

    Returns:
        Cleaned message list (may be shorter)

    Example:
        >>> messages = [
        ...     HumanMessage(content="run ls"),
        ...     AIMessage(content="", tool_calls=[{"id": "1", "name": "bash", "args": {...}}]),
        ...     ToolMessage(content="file.txt", tool_call_id="1"),
        ... ]
        >>> normalized = normalize_messages(messages)
        >>> len(normalized) == 3  # All valid
    """
    if not messages:
        return []

    # Collect valid tool request IDs
    valid_request_ids: set[str] = set()
    matched_request_ids: set[str] = set()
    removed_invalid_requests = 0
    removed_invalid_responses = 0

    normalized: list[BaseMessage] = []

    # First pass: collect valid requests and filter messages
    for msg in messages:
        if isinstance(msg, AIMessage):
            # Check tool_calls validity
            if msg.tool_calls:
                valid_calls = []
                for tc in msg.tool_calls:
                    # Tool call must have id and valid structure
                    tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                    if tc_id and isinstance(tc_id, str):
                        valid_request_ids.add(tc_id)
                        valid_calls.append(tc)
                    else:
                        removed_invalid_requests += 1

                # Keep message only if it has valid content or valid tool calls
                if valid_calls or msg.content:
                    # Clone message with filtered tool_calls
                    cloned = msg.model_copy(deep=True)
                    cloned.tool_calls = valid_calls
                    normalized.append(cloned)
                elif msg.content:
                    # Keep message with content even if all tool calls invalid
                    cloned = msg.model_copy(deep=True)
                    cloned.tool_calls = []
                    normalized.append(cloned)
                # else: drop message entirely (no content, no valid tools)
            else:
                # No tool calls, keep as-is
                normalized.append(msg)

        elif isinstance(msg, ToolMessage):
            # Tool response must have matching request
            tc_id = getattr(msg, "tool_call_id", None)
            if tc_id and tc_id in valid_request_ids and tc_id not in matched_request_ids:
                matched_request_ids.add(tc_id)
                normalized.append(msg)
            else:
                removed_invalid_responses += 1

        else:
            # HumanMessage, SystemMessage, etc. — keep as-is
            normalized.append(msg)

    # Second pass: filter to keep only matched tool pairs
    # Remove tool requests that never got a response AND tool responses for unmatched requests
    final: list[BaseMessage] = []
    for msg in normalized:
        if isinstance(msg, AIMessage):
            if msg.tool_calls:
                # Keep only matched tool calls
                matched_calls = [
                    tc
                    for tc in msg.tool_calls
                    if (tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)) in matched_request_ids
                ]
                if matched_calls or msg.content:
                    cloned = msg.model_copy(deep=True)
                    cloned.tool_calls = matched_calls
                    final.append(cloned)
            else:
                final.append(msg)

        elif isinstance(msg, ToolMessage):
            tc_id = getattr(msg, "tool_call_id", None)
            if tc_id and tc_id in matched_request_ids:
                final.append(msg)

        else:
            final.append(msg)

    # Remove empty messages (no content and no tool calls)
    final = [msg for msg in final if msg.content or (hasattr(msg, "tool_calls") and msg.tool_calls)]

    if removed_invalid_requests > 0 or removed_invalid_responses > 0:
        logger.warning(
            "[ProviderSafety] Normalized tool messages before LLM call: "
            f"removed {removed_invalid_requests} invalid requests, "
            f"{removed_invalid_responses} invalid responses, "
            f"{len(messages)} → {len(final)} messages"
        )

    return final


class SafetyWrappedChatModel(BaseChatModel):
    """Transparent BaseChatModel wrapper that normalizes messages before LLM calls.

    Implements the full BaseChatModel protocol, forwarding all calls to the wrapped LLM
    after message normalization.

    Example:
        >>> from langchain_openai import ChatOpenAI
        >>> base_llm = ChatOpenAI(model="gpt-4")
        >>> safe_llm = wrap_chat_model_with_safety(base_llm)
        >>> # Use safe_llm like any BaseChatModel
        >>> result = await safe_llm.ainvoke([...])  # Messages auto-normalized
    """

    def __init__(self, wrapped_llm: BaseChatModel) -> None:
        """Initialize wrapper.

        Args:
            wrapped_llm: The LLM instance to wrap
        """
        super().__init__()
        self._wrapped = wrapped_llm

    def _generate(
        self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: Any = None, **kwargs: Any
    ) -> "ChatResult":
        """Sync generation (normalize + forward)."""
        normalized = normalize_messages(messages)
        return self._wrapped._generate(normalized, stop=stop, run_manager=run_manager, **kwargs)

    async def _agenerate(
        self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: Any = None, **kwargs: Any
    ) -> "ChatResult":
        """Async generation (normalize + forward)."""
        normalized = normalize_messages(messages)
        return await self._wrapped._agenerate(normalized, stop=stop, run_manager=run_manager, **kwargs)

    def _stream(
        self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: Any = None, **kwargs: Any
    ) -> Any:
        """Sync streaming (normalize + forward)."""
        normalized = normalize_messages(messages)
        return self._wrapped._stream(normalized, stop=stop, run_manager=run_manager, **kwargs)

    def _astream(
        self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: Any = None, **kwargs: Any
    ) -> Any:
        """Async streaming (normalize + forward)."""
        normalized = normalize_messages(messages)
        return self._wrapped._astream(normalized, stop=stop, run_manager=run_manager, **kwargs)

    @property
    def _llm_type(self) -> str:
        """Return wrapped LLM type."""
        return self._wrapped._llm_type

    @property
    def _identifying_params(self) -> dict[str, Any]:
        """Return wrapped LLM params."""
        return self._wrapped._identifying_params

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "BaseChatModel":
        """Forward bind_tools to wrapped LLM."""
        bound = self._wrapped.bind_tools(tools, **kwargs)
        # Wrap the bound model too
        return SafetyWrappedChatModel(bound)

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        """Forward structured output to wrapped LLM."""
        structured = self._wrapped.with_structured_output(schema, **kwargs)
        # Return wrapped to maintain safety
        return SafetyWrappedChatModel(cast(BaseChatModel, structured))


def wrap_chat_model_with_safety(llm: BaseChatModel) -> BaseChatModel:
    """Wrap a BaseChatModel with provider safety.

    Transparent operation — the wrapped model behaves identically to the original,
    except messages are normalized before each LLM call to prevent API errors from
    invalid tool calls or orphan tool responses.

    Args:
        llm: Original BaseChatModel instance

    Returns:
        Wrapped instance with safety guarantees

    Example:
        >>> from langchain_openai import ChatOpenAI
        >>> base_llm = ChatOpenAI(model="gpt-4")
        >>> safe_llm = wrap_chat_model_with_safety(base_llm)
        >>> # All subsequent calls automatically normalized
        >>> await safe_llm.ainvoke([...])
    """
    if isinstance(llm, SafetyWrappedChatModel):
        # Already wrapped, avoid double-wrapping
        return llm
    return SafetyWrappedChatModel(llm)


__all__ = [
    "SafetyWrappedChatModel",
    "normalize_messages",
    "wrap_chat_model_with_safety",
]
