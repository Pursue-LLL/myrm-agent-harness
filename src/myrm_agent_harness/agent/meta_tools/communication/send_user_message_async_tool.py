"""Non-blocking asynchronous agent-to-user communication meta-tool.

[INPUT]
- langchain_core.tools::tool (POS: LangChain tool decorator)
- langchain_core.callbacks.manager::dispatch_custom_event (POS: SSE custom event bridge)
- pydantic::BaseModel, Field (POS: Pydantic input schema validation)

[OUTPUT]
- send_user_message_async: LangChain tool for asynchronous progress updates and questions
- create_send_user_message_async_tool: Factory function
- reset_turn_async_message_limit: Helper to reset rate limits at turn boundaries

[POS]
Meta-tool for non-blocking notifications and questions during long-running tasks.
Returns {"accepted": true} immediately without interrupting the active agent turn.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Literal
from uuid import uuid4

from langchain_core.callbacks.manager import dispatch_custom_event
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

MAX_ASYNC_MESSAGES_PER_TURN = 3


class AsyncMessageRateLimiter:
    """Thread-safe rate limiter for async messages within an agent turn."""

    def __init__(self, max_calls_per_turn: int = MAX_ASYNC_MESSAGES_PER_TURN) -> None:
        self.max_calls = max_calls_per_turn
        self._count = 0
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        with self._lock:
            if self._count >= self.max_calls:
                return False
            self._count += 1
            return True

    def reset(self) -> None:
        with self._lock:
            self._count = 0


_global_rate_limiter = AsyncMessageRateLimiter()


def reset_turn_async_message_limit(limiter: AsyncMessageRateLimiter | None = None) -> None:
    """Reset the turn-level rate limiting counter at turn boundaries."""
    target = limiter or _global_rate_limiter
    target.reset()


class SendUserMessageAsyncInput(BaseModel):
    """Input schema for send_user_message_async."""

    message: str = Field(
        ...,
        min_length=1,
        description="The message content to communicate to the user. Must be informative and concise.",
    )
    category: Literal["progress", "milestone", "question"] = Field(
        default="progress",
        description=(
            "Type of communication: 'progress' for status updates, "
            "'milestone' for completed major phases, "
            "'question' for non-blocking clarifying questions."
        ),
    )
    recommendation: str | None = Field(
        default=None,
        description=(
            "For 'question' category only: the agent's recommended course of action if the user doesn't respond."
        ),
    )
    suggested_replies: list[str] | None = Field(
        default=None,
        max_length=3,
        description=(
            "Optional 1 to 3 concise quick reply options (e.g. ['Proceed with A', 'Use B', 'Skip']) "
            "for the user to click in the UI."
        ),
    )


def create_send_user_message_async_tool(
    rate_limiter: AsyncMessageRateLimiter | None = None,
) -> BaseTool:
    """Create the non-blocking send_user_message_async tool."""
    limiter = rate_limiter or _global_rate_limiter

    @tool(args_schema=SendUserMessageAsyncInput)
    def send_user_message_async(
        message: str,
        category: Literal["progress", "milestone", "question"] = "progress",
        recommendation: str | None = None,
        suggested_replies: list[str] | None = None,
    ) -> str:
        """Send a non-blocking message or clarifying question to the user during task execution.

        Use this tool during complex, multi-step tasks to:
        1. Report key progress milestones without stopping execution ('progress' / 'milestone').
        2. Ask non-blocking questions where a default recommendation is provided ('question').
        3. Provide 1 to 3 quick clickable suggested replies for the user.

        Execution continues immediately after calling this tool; it does NOT pause or stop your turn.
        """
        stripped_message = message.strip()
        if not stripped_message:
            return json.dumps({"accepted": False, "error": "Message must not be empty"})

        if not limiter.acquire():
            logger.warning("send_user_message_async rate limit reached (%d calls)", limiter.max_calls)
            return json.dumps({
                "accepted": False,
                "error": (
                    f"Rate limit reached: maximum {limiter.max_calls} async messages per turn. "
                    "Please continue executing your primary task directly without retrying this tool."
                ),
            })
        call_id = f"async_msg_{uuid4().hex[:8]}"

        sanitized_replies: list[str] | None = None
        if suggested_replies:
            sanitized_replies = [r.strip()[:40] for r in suggested_replies if r and r.strip()][:3]

        payload = {
            "call_id": call_id,
            "message": stripped_message,
            "category": category,
            "recommendation": recommendation.strip() if recommendation else None,
            "suggested_replies": sanitized_replies,
        }

        try:
            dispatch_custom_event("async_user_message", payload)
        except Exception as e:
            logger.warning("Failed to dispatch async_user_message custom event: %s", e)

        ret: dict[str, object] = {
            "accepted": True,
            "call_id": call_id,
            "category": category,
        }
        if sanitized_replies:
            ret["suggested_replies"] = sanitized_replies

        return json.dumps(ret)

    return send_user_message_async

