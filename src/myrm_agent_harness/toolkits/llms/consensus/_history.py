"""Tool-free chat history flattening for consensus and MoA overlay calls.

[POS]
See module docstring.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage


def flatten_tool_free_history(chat_history: list[BaseMessage]) -> list[BaseMessage]:
    """Strip tool artifacts so tool-less reference models avoid provider 400 errors."""
    flat: list[BaseMessage] = []
    for msg in chat_history:
        if isinstance(msg, (HumanMessage, SystemMessage)):
            flat.append(msg)
        elif isinstance(msg, AIMessage):
            content = msg.content or ""
            if content:
                flat.append(AIMessage(content=content))
        elif isinstance(msg, ToolMessage):
            name = getattr(msg, "name", None) or "tool"
            text = str(msg.content)[:500] if msg.content else ""
            if text:
                flat.append(HumanMessage(content=f"[{name} result]: {text}"))
    return flat


__all__ = ["flatten_tool_free_history"]
