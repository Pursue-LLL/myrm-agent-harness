"""Turn Outline projection extractor and types for lightweight session fold navigation.

[INPUT]
- List of raw message dicts or objects with role, content, id, created_at, extra_data.

[OUTPUT]
- TurnOutlineItem: Dataclass representing a single turn's lightweight fold outline.
- TurnOutlineProjection: Dataclass representing the aggregated session turn outlines.
- TurnOutlineExtractor: Functional extractor implementing the projection fold logic.

[POS]
Harness-level turn outline projection utility.
Maintains a ~600-byte per turn fold summary (user prompt preview <=50 chars, assistant reply preview <=120 chars)
allowing UI timeline rails to render 100+ turns at minimal memory (<60KB) and jump without layout jitter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Sequence


@dataclass(slots=True, frozen=True)
class TurnOutlineItem:
    """Lightweight outline metadata for a single conversation turn."""

    turn_index: int
    user_message_id: str
    assistant_message_id: str | None = None
    prompt_preview: str = ""
    reply_preview: str = ""
    created_at: datetime | None = None
    tool_counts: dict[str, int] = field(default_factory=dict)
    has_artifacts: bool = False
    has_errors: bool = False


@dataclass(slots=True, frozen=True)
class TurnOutlineProjection:
    """Aggregated full-session turn outline projection."""

    chat_id: str
    total_turns: int
    turns: list[TurnOutlineItem] = field(default_factory=list)
    version: int = 1


class TurnOutlineExtractor:
    """Extractor for creating lightweight TurnOutlineProjections from raw session message sequences."""

    _THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
    _CODE_BLOCK_RE = re.compile(r"```[a-zA-Z0-9_\-]*\n?|```", re.IGNORECASE)
    _FILE_SPILLOVER_RE = re.compile(r"<file_spillover\b[^>]*/>", re.IGNORECASE)
    _MULTIPLE_WHITESPACE_RE = re.compile(r"\s+")

    @classmethod
    def sanitize_preview_text(cls, text: str, max_chars: int) -> str:
        """Sanitize raw LLM or user text into a clean single-line preview snippet."""
        if not text:
            return ""

        # Strip think blocks
        cleaned = cls._THINK_BLOCK_RE.sub(" ", text)
        # Strip spillover tags
        cleaned = cls._FILE_SPILLOVER_RE.sub(" ", cleaned)
        # Strip code markdown backticks
        cleaned = cls._CODE_BLOCK_RE.sub(" ", cleaned)
        # Normalize whitespace and newlines
        cleaned = cls._MULTIPLE_WHITESPACE_RE.sub(" ", cleaned).strip()

        if len(cleaned) <= max_chars:
            return cleaned
        return cleaned[:max_chars].rstrip() + "..."

    @classmethod
    def extract_projection(
        cls,
        chat_id: str,
        messages: Sequence[Any],
        *,
        max_prompt_chars: int = 50,
        max_reply_chars: int = 120,
    ) -> TurnOutlineProjection:
        """Fold session messages into a sequence of TurnOutlineItems."""
        turns: list[TurnOutlineItem] = []
        turn_index = 0

        current_user_msg_id: str | None = None
        current_prompt_preview: str = ""
        current_assistant_msg_id: str | None = None
        current_reply_preview: str = ""
        current_turn_created_at: datetime | None = None
        current_tool_counts: dict[str, int] = {}
        current_has_artifacts: bool = False
        current_has_errors: bool = False

        def _flush_turn() -> None:
            nonlocal turn_index, current_user_msg_id, current_prompt_preview
            nonlocal current_assistant_msg_id, current_reply_preview
            nonlocal current_turn_created_at, current_tool_counts
            nonlocal current_has_artifacts, current_has_errors

            if current_user_msg_id is not None:
                turn_index += 1
                turns.append(
                    TurnOutlineItem(
                        turn_index=turn_index,
                        user_message_id=current_user_msg_id,
                        assistant_message_id=current_assistant_msg_id,
                        prompt_preview=current_prompt_preview,
                        reply_preview=current_reply_preview,
                        created_at=current_turn_created_at,
                        tool_counts=dict(current_tool_counts),
                        has_artifacts=current_has_artifacts,
                        has_errors=current_has_errors,
                    )
                )

            current_user_msg_id = None
            current_prompt_preview = ""
            current_assistant_msg_id = None
            current_reply_preview = ""
            current_turn_created_at = None
            current_tool_counts = {}
            current_has_artifacts = False
            current_has_errors = False

        for msg in messages:
            # Extract common attributes from dict or object
            if isinstance(msg, dict):
                role = msg.get("role", "")
                content = msg.get("content", "")
                msg_id = msg.get("id") or msg.get("message_id") or ""
                created_at = msg.get("created_at") or msg.get("sent_at")
                extra_data = msg.get("extra_data") or {}
            else:
                role = getattr(msg, "role", "")
                content = getattr(msg, "content", "")
                msg_id = getattr(msg, "id", "")
                created_at = getattr(msg, "created_at", None) or getattr(msg, "sent_at", None)
                extra_data = getattr(msg, "extra_data", None) or {}

            if not isinstance(extra_data, dict):
                extra_data = {}

            if role == "user":
                # Flush previous completed turn if new user message appears
                _flush_turn()
                current_user_msg_id = str(msg_id)
                current_prompt_preview = cls.sanitize_preview_text(str(content or ""), max_prompt_chars)
                if isinstance(created_at, datetime):
                    current_turn_created_at = created_at

            elif role == "assistant":
                current_assistant_msg_id = str(msg_id)
                current_reply_preview = cls.sanitize_preview_text(str(content or ""), max_reply_chars)

                # Inspect tools, progress steps, and artifacts from extra_data
                progress_steps = extra_data.get("progressSteps")
                if isinstance(progress_steps, list):
                    for step in progress_steps:
                        if isinstance(step, dict):
                            tool_name = step.get("tool_name")
                            if isinstance(tool_name, str) and tool_name:
                                current_tool_counts[tool_name] = current_tool_counts.get(tool_name, 0) + 1
                            if step.get("status") == "error" or step.get("error"):
                                current_has_errors = True

                if extra_data.get("uiArtifacts") or extra_data.get("stagedArtifacts"):
                    current_has_artifacts = True

        # Flush final turn
        _flush_turn()

        return TurnOutlineProjection(
            chat_id=chat_id,
            total_turns=len(turns),
            turns=turns,
            version=1,
        )
