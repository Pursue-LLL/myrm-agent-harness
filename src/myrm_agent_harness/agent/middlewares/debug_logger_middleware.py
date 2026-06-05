"""调试日志中间件

记录发送给 LLM 的完整消息列表，用于调试和监控。
使用 LangChain 官方 @wrap_model_call 装饰器。

注意：此中间件应放在中间件链的最后（最接近 LLM 调用），
以便查看所有其他中间件处理后的最终消息。

[INPUT]
- (none)

[OUTPUT]
- debug_logger_middleware: Args:

[POS]
Provides debug_logger_middleware.
"""

import logging
from collections.abc import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

logger = logging.getLogger(__name__)


class DebugLoggerMiddleware(AgentMiddleware):  # type: ignore[type-arg]
    """调试日志中间件 - 打印发送给 LLM 的完整消息列表

    此中间件应放在链的最后，以查看最终消息。
    """

    name = "debug_logger_middleware"

    async def awrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]
    ) -> ModelResponse:
        messages = list(request.messages)

        # Build log content (single output to reduce log lines)
        log_lines = []
        log_lines.append("=" * 70)
        log_lines.append(" [Final messages sent to LLM]")

        # System message
        system_prompt = getattr(request, "system_prompt", None)
        system_message = getattr(request, "system_message", None)
        if system_message:
            sys_content = getattr(system_message, "content", "")
            log_lines.append(f"[System] {_format_content(sys_content)}")
        elif system_prompt:
            log_lines.append(f"[System] {_format_content(system_prompt)}")
        else:
            log_lines.append("[System] (none)")

        # Conversation messages
        log_lines.append(f"[Messages] Total: {len(messages)}")
        for idx, msg in enumerate(messages):
            msg_type = type(msg).__name__
            content = getattr(msg, "content", "")

            # Special handling for tool calls (only AIMessage has tool_calls)
            tool_calls = getattr(msg, "tool_calls", None)
            if tool_calls:
                tool_names = [
                    tc.get("name", "") if hasattr(tc, "get") else getattr(tc, "name", "") for tc in tool_calls
                ]
                log_lines.append(f" [{idx}] {msg_type}:  Tool calls -> {tool_names}")
            # Special handling for tool responses
            elif msg_type == "ToolMessage":
                tool_name = getattr(msg, "name", "unknown")
                # Don't truncate error messages for debugging
                is_error = content.startswith("") if content else False
                formatted = content if is_error else _format_content(content)
                log_lines.append(f" [{idx}] {msg_type}({tool_name}): {formatted}")
            else:
                log_lines.append(f" [{idx}] {msg_type}: {_format_content(content)}")

        # Available tools
        tools = list(request.tools) if request.tools else []
        tool_names = [getattr(t, "name", "unknown") for t in tools]
        log_lines.append(f"--- [Available tools] {tool_names}")
        log_lines.append("=" * 70)

        logger.debug("\n".join(log_lines))

        # Call LLM
        return await handler(request)


def _format_content(content: str) -> str:
    """格式化消息内容，保留换行符

    显示前 100 个字符 + 后 100 个字符，如果太长则省略中间部分。

    Args:
        content: 消息内容

    Returns:
        格式化后的字符串
    """
    if not content:
        return "(empty)"

    content_str = str(content)

    # Threshold: use ellipsis format if over 400 chars
    threshold = 400
    head_len = 100
    tail_len = 100

    if len(content_str) <= threshold:
        return content_str
    else:
        head = content_str[:head_len]
        tail = content_str[-tail_len:]
        omitted = len(content_str) - head_len - tail_len
        return f"{head} ...(omitted {omitted} chars)... {tail}"


debug_logger_middleware = DebugLoggerMiddleware()
