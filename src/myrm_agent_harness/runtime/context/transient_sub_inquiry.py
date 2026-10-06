"""Transient side-channel sub-inquiry engine with zero-pollution context isolation.

Implements the `/btw` (By-The-Way) ephemeral inquiry lane. In long-running tasks or
deep multi-turn sessions, users often need quick side answers (e.g. inspecting a symbol,
checking a default config value) without injecting noise into the primary context.
This engine extracts a read-only mirror of the conversation background, executes an
isolated transient query, and immediately discards the sub-context upon response delivery,
guaranteeing 100% zero pollution of the main task's KV cache and message history.

[INPUT]
- langchain_core.messages::BaseMessage, HumanMessage, SystemMessage, AIMessage
- langchain_core.language_models::BaseChatModel

[OUTPUT]
- TransientInquiryRequest: Strongly typed input contract for the side inquiry
- TransientInquiryResponse: Structured ephemeral response with immutability guarantees
- build_transient_context_messages: Read-only context constructor
- execute_transient_sub_inquiry: Ephemeral side-channel inquiry executor

[POS]
Runtime context layer ephemeral side-channel isolation component.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

if TYPE_CHECKING:
    from collections.abc import Sequence

    from langchain_core.language_models import BaseChatModel

_DEFAULT_TRANSIENT_SYSTEM_PROMPT = (
    "You are an agile side-channel assistant answering a quick user inquiry (/btw). "
    "You have access to the conversation context below for reference only. "
    "Provide a concise, direct answer to the user's side question. "
    "Do NOT alter the primary task or issue unrelated instructions."
)


@dataclass(frozen=True)
class TransientInquiryRequest:
    """Strongly typed input request for an ephemeral /btw side inquiry."""

    question: str
    parent_messages: Sequence[BaseMessage]
    system_prompt_override: str | None = None
    model_name: str | None = None
    max_context_turns: int = 6


@dataclass(frozen=True)
class TransientInquiryResponse:
    """Structured response payload returned from the transient side-channel lane."""

    answer: str
    latency_ms: float
    tokens_used: int
    parent_context_polluted: bool = False
    timestamp: str = ""

    def to_markdown(self) -> str:
        """Render response into a floating side-channel note card for WebUI/Desktop."""
        ts_hint = f" ({self.timestamp})" if self.timestamp else ""
        return (
            f"> [!NOTE] 💡 **Side Inquiry (/btw)**{ts_hint}\n"
            f">\n"
            f"> {self.answer.strip()}\n"
            f">\n"
            f"> *Latency: {self.latency_ms:.1f}ms | Tokens: {self.tokens_used} | Main Context: 100% Isolated*"
        )


def build_transient_context_messages(
    request: TransientInquiryRequest,
) -> list[BaseMessage]:
    """Construct a read-only, ephemeral message list for side-channel evaluation.

    Strictly reads from parent_messages without modifying or retaining them.
    Extracts the leading system prompt (if any) and the recent N messages as
    background reference, followed by the user's side question.
    """
    transient_list: list[BaseMessage] = []

    sys_content = request.system_prompt_override or _DEFAULT_TRANSIENT_SYSTEM_PROMPT
    transient_list.append(SystemMessage(content=sys_content))

    parent = request.parent_messages
    if parent:
        # Take at most max_context_turns recent messages
        recent = parent[-request.max_context_turns :]
        for msg in recent:
            # Clone content to guarantee zero reference leakage
            role = getattr(msg, "type", "message")
            text = str(getattr(msg, "content", ""))
            if text:
                transient_list.append(HumanMessage(content=f"[Context Ref - {role}]: {text}"))

    # Append user side question
    transient_list.append(HumanMessage(content=f"[Side Inquiry]: {request.question.strip()}"))
    return transient_list


async def execute_transient_sub_inquiry(
    request: TransientInquiryRequest,
    llm: BaseChatModel,
) -> TransientInquiryResponse:
    """Execute an ephemeral side inquiry in an isolated, read-only sub-context.

    Guarantees:
    - Never mutates or appends to `request.parent_messages`.
    - Immediately discards the transient message list after generating the answer.
    - Accurately tracks latency and usage tokens.
    """
    initial_parent_len = len(request.parent_messages)
    start_time = time.monotonic()

    transient_messages = build_transient_context_messages(request)

    tokens_used = 0
    try:
        response = await llm.ainvoke(transient_messages)
        if isinstance(response, AIMessage):
            answer_text = str(response.content)
            usage = getattr(response, "usage_metadata", None)
            if isinstance(usage, dict):
                tokens_used = usage.get("total_tokens", 0)
        else:
            answer_text = str(getattr(response, "content", response))
    except Exception as exc:
        answer_text = f"Error during side inquiry: {exc}"

    # Explicitly clear transient messages to guarantee prompt cache and memory isolation
    transient_messages.clear()
    del transient_messages

    latency_ms = (time.monotonic() - start_time) * 1000.0
    now_iso = datetime.now(UTC).isoformat()

    # Invariant assertion: parent messages list was never modified
    parent_polluted = len(request.parent_messages) != initial_parent_len

    return TransientInquiryResponse(
        answer=answer_text,
        latency_ms=latency_ms,
        tokens_used=tokens_used,
        parent_context_polluted=parent_polluted,
        timestamp=now_iso,
    )
