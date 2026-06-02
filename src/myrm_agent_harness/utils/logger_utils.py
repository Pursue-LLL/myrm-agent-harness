"""Unified logging utilities.

[INPUT]
- logging (POS: Python standard library, logging system)

[OUTPUT]
- AgentLogger: Agent-specific logger with unified format and convenience methods
- get_agent_logger(): Get an AgentLogger instance
- get_skill_logger(): Get a skill-specific logger
- get_agent_core_logger(): Get an agent core module logger

[POS]
Unified logging utilities. Provides consistent log format and convenience methods
(step/success/error_detail) for project-wide log output.
"""

from __future__ import annotations

import logging


class AgentLogger:
    """Agent-specific logger with unified format and convenience methods."""

    def __init__(self, logger: logging.Logger):
        self._logger = logger

    def step(self, message: str, *args: object, **kwargs: object) -> None:
        """Log an execution step (INFO level)."""
        if args:
            self._logger.info(f"[step] {message}", *args)
        else:
            extra_info = self._format_kwargs(kwargs)
            self._logger.info("[step] %s%s", message, extra_info)

    def success(self, message: str, *args: object, **kwargs: object) -> None:
        """Log a successful operation (INFO level)."""
        if args:
            self._logger.info(f"[ok] {message}", *args)
        else:
            extra_info = self._format_kwargs(kwargs)
            self._logger.info("[ok] %s%s", message, extra_info)

    def info(self, message: str, *args: object, **kwargs: object) -> None:
        """Log an informational event (INFO level).

        Supports standard logging %-style formatting and custom kwargs.
        """
        if args:
            self._logger.info(message, *args)
        else:
            extra_info = self._format_kwargs(kwargs)
            self._logger.info("%s%s", message, extra_info)

    def warn(self, message: str, *args: object, **kwargs: object) -> None:
        """Log a warning event (WARNING level)."""
        if args:
            self._logger.warning(message, *args)
        else:
            extra_info = self._format_kwargs(kwargs)
            self._logger.warning("%s%s", message, extra_info)

    def error(self, message: str, *args: object, **kwargs: object) -> None:
        """Log an error event (ERROR level)."""
        if args:
            self._logger.error(message, *args)
        else:
            extra_info = self._format_kwargs(kwargs)
            self._logger.error("%s%s", message, extra_info)

    def error_detail(self, message: str, error: Exception, **kwargs: object) -> None:
        """Log a detailed error with exception traceback."""
        extra_info = self._format_kwargs(kwargs)
        self._logger.error("%s%s: %s", message, extra_info, error, exc_info=True)

    def prune(self, message: str, removed: int, total: int, strategy: str = "") -> None:
        """Log a context pruning event."""
        strategy_str = f" ({strategy})" if strategy else ""
        self._logger.info(
            "[prune] %s%s: removed %d/%d messages", message, strategy_str, removed, total
        )

    def token_count(
        self, message: str, tokens: int, total_tokens: int | None = None
    ) -> None:
        """Log token usage statistics."""
        if total_tokens is not None:
            self._logger.info(
                "[tokens] %s: %d tokens (cumulative: %d)", message, tokens, total_tokens
            )
        else:
            self._logger.info("[tokens] %s: %d tokens", message, tokens)

    def decision(self, message: str, reason: str, **kwargs: object) -> None:
        """Log an AI decision with reasoning."""
        extra_info = self._format_kwargs(kwargs)
        self._logger.info("[decision] %s: %s%s", message, reason, extra_info)

    def separator(self, title: str = "", width: int = 80) -> None:
        """Log a visual separator line."""
        self._logger.info("")
        self._logger.info("=" * width)
        if title:
            self._logger.info(title)
            self._logger.info("=" * width)

    def _format_kwargs(self, kwargs: dict[str, object]) -> str:
        """Format extra keyword arguments into a compact string."""
        if not kwargs:
            return ""

        messages_value = kwargs.get("messages")
        other_items = []

        for key, value in kwargs.items():
            if key == "messages":
                continue
            if isinstance(value, str) and len(value) > 100:
                value = value[:100] + "..."
            other_items.append(f"{key}={value}")

        result_parts = []
        if other_items:
            result_parts.append(f" ({', '.join(other_items)})")

        if messages_value is not None and isinstance(messages_value, list):
            formatted_messages = self._format_messages(messages_value)
            result_parts.append(f"\nmessages={formatted_messages}")

        return "".join(result_parts)

    def _format_messages(self, messages: list[object]) -> str:
        """Format a message list with type-per-line layout."""
        if not messages:
            return "[]"

        formatted_items = []
        for idx, msg in enumerate(messages):
            msg_type = type(msg).__name__
            content = getattr(msg, "content", "")
            tool_calls = getattr(msg, "tool_calls", None)
            tool_call_id = getattr(msg, "tool_call_id", None)
            msg_id = getattr(msg, "id", "")

            parts = [f"  [{idx}] {msg_type}:"]
            if msg_id:
                parts.append(f"    id={msg_id}")

            content_str = str(content) if content is not None else None
            if content_str is not None:
                if len(content_str) > 200:
                    content_str = content_str[:200] + "..."
                parts.append(f"    content={content_str}")

            if tool_calls:
                parts.append(f"    tool_calls={len(tool_calls)} call(s)")
            if tool_call_id:
                parts.append(f"    tool_call_id={tool_call_id}")

            formatted_items.append("\n".join(parts))

        return "[\n" + "\n".join(formatted_items) + "\n]"

    def debug(self, message: str, *args: object, **kwargs: object) -> None:
        """Standard debug method (stdlib-compatible)."""
        self._logger.debug(message, *args, **kwargs)

    def warning(self, message: str, *args: object, **kwargs: object) -> None:
        """Standard warning method (stdlib-compatible)."""
        self._logger.warning(message, *args, **kwargs)

    def exception(self, message: str, *args: object, **kwargs: object) -> None:
        """Log ERROR with current exception traceback (stdlib-compatible)."""
        self._logger.exception(message, *args, **kwargs)


def get_agent_logger(name: str) -> AgentLogger:
    """Get an AgentLogger instance.

    Args:
        name: Logger name (typically __name__)

    Returns:
        AgentLogger instance
    """
    python_logger = logging.getLogger(name)
    return AgentLogger(python_logger)


def get_skill_logger(skill_name: str) -> AgentLogger:
    """Get a skill-specific logger."""
    return get_agent_logger(f"app.skills.{skill_name}")


def get_agent_core_logger(module_name: str) -> AgentLogger:
    """Get an agent core module logger."""
    return get_agent_logger(f"app.core.{module_name}")
