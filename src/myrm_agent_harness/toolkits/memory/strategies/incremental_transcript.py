"""Incremental transcript stream parser with truncation protection.

[INPUT]
- io::BinaryIO, io::TextIOBase (POS: Python standard I/O stream primitives)

[OUTPUT]
- TranscriptTurn: Structured single turn of external transcript.
- TranscriptIncrementalChunk: Incremental slice containing turns, offset, and stream metadata.
- IncrementalTranscriptParser: Stateless stream parser for external agent transcripts (Claude Code, Codex).

[POS]
Harness framework-level stream parser for incremental external transcripts.
Provides byte-level watermark tracking, line-truncation protection, and robust turn extraction.
"""

from __future__ import annotations

import io
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import BinaryIO, TextIO

logger = logging.getLogger(__name__)

MAX_INCREMENTAL_LINES = 20_000
MAX_CONTENT_LENGTH = 4_000


@dataclass(slots=True)
class TranscriptTurn:
    """A parsed external conversation turn (user prompt + assistant response)."""

    user_content: str
    assistant_content: str
    tool_names: list[str] = field(default_factory=list)
    timestamp: str = ""
    session_id: str | None = None


@dataclass(slots=True)
class TranscriptIncrementalChunk:
    """Incremental chunk extracted from an external transcript stream."""

    turns: list[TranscriptTurn] = field(default_factory=list)
    session_id: str | None = None
    session_title: str | None = None
    new_byte_offset: int = 0
    consumed_lines: int = 0
    has_incomplete_tail: bool = False
    warnings: list[str] = field(default_factory=list)


class IncrementalTranscriptParser:
    """Stateless parser for incremental transcript logs."""

    @staticmethod
    def parse_stream(
        stream: BinaryIO,
        *,
        start_offset: int = 0,
        max_lines: int = MAX_INCREMENTAL_LINES,
    ) -> TranscriptIncrementalChunk:
        """Parse stream from given byte offset with line-truncation protection."""
        if start_offset > 0:
            stream.seek(start_offset)

        raw_bytes = stream.read()
        if not raw_bytes:
            return TranscriptIncrementalChunk(new_byte_offset=start_offset)

        # Check if the buffer ends with a newline
        has_trailing_newline = raw_bytes.endswith(b"\n") or raw_bytes.endswith(b"\r")
        lines = raw_bytes.splitlines(keepends=True)
        if not lines:
            return TranscriptIncrementalChunk(new_byte_offset=start_offset)

        # Truncation protection: If file does not end with newline, external agent is mid-write
        incomplete_tail = False
        valid_lines: list[bytes] = []
        consumed_bytes = 0

        for idx, line_bytes in enumerate(lines):
            is_last = idx == len(lines) - 1
            if is_last and not has_trailing_newline:
                incomplete_tail = True
                break

            valid_lines.append(line_bytes)
            consumed_bytes += len(line_bytes)
            if len(valid_lines) >= max_lines:
                break

        decoded_lines = [
            line.decode("utf-8", errors="replace").strip()
            for line in valid_lines
            if line.decode("utf-8", errors="replace").strip()
        ]

        chunk = IncrementalTranscriptParser.parse_jsonl_lines(decoded_lines)
        chunk.new_byte_offset = start_offset + consumed_bytes
        chunk.has_incomplete_tail = incomplete_tail
        return chunk

    @staticmethod
    def parse_jsonl_lines(lines: list[str]) -> TranscriptIncrementalChunk:
        """Parse structured turns from raw JSONL line strings."""
        chunk = TranscriptIncrementalChunk(consumed_lines=len(lines))
        user_entries: list[dict[str, object]] = []
        assistant_entries: list[dict[str, object]] = []

        for line_str in lines:
            line_str = line_str.strip()
            if not line_str:
                continue

            try:
                entry = json.loads(line_str)
            except json.JSONDecodeError:
                chunk.warnings.append("invalid_json_line_skipped")
                continue

            if not isinstance(entry, dict):
                continue

            # Extract session title or id hints if present
            session_id = entry.get("session_id") or entry.get("sessionId")
            if isinstance(session_id, str) and not chunk.session_id:
                chunk.session_id = session_id

            entry_type = str(entry.get("type") or entry.get("role") or "").lower()
            if not entry_type and isinstance(entry.get("message"), dict):
                entry_type = str(entry["message"].get("role", "")).lower()

            if entry_type == "summary":
                summary_text = entry.get("summary") or entry.get("content")
                if isinstance(summary_text, str) and not chunk.session_title:
                    chunk.session_title = summary_text[:120]

            elif entry_type == "user":
                user_entries.append(entry)
            elif entry_type == "assistant":
                assistant_entries.append(entry)

        # Build turns pairing user and assistant entries
        chunk.turns = IncrementalTranscriptParser._pair_turns(
            user_entries, assistant_entries, session_id=chunk.session_id
        )
        return chunk

    @staticmethod
    def _pair_turns(
        user_entries: list[dict[str, object]],
        assistant_entries: list[dict[str, object]],
        *,
        session_id: str | None,
    ) -> list[TranscriptTurn]:
        """Pair sequential user and assistant messages into coherent turns."""
        turns: list[TranscriptTurn] = []
        pair_count = min(len(user_entries), len(assistant_entries))

        for idx in range(pair_count):
            user_entry = user_entries[idx]
            asst_entry = assistant_entries[idx]

            u_text = IncrementalTranscriptParser._extract_text(user_entry)
            a_text = IncrementalTranscriptParser._extract_text(asst_entry)
            tools = IncrementalTranscriptParser._extract_tool_names(asst_entry)
            ts = str(
                user_entry.get("timestamp")
                or asst_entry.get("timestamp")
                or datetime.now(UTC).isoformat()
            )

            if u_text or a_text:
                turns.append(
                    TranscriptTurn(
                        user_content=u_text[:MAX_CONTENT_LENGTH],
                        assistant_content=a_text[:MAX_CONTENT_LENGTH],
                        tool_names=tools,
                        timestamp=ts,
                        session_id=session_id,
                    )
                )

        # If user has trailing unreplied query
        if len(user_entries) > pair_count:
            for extra_user in user_entries[pair_count:]:
                u_text = IncrementalTranscriptParser._extract_text(extra_user)
                if u_text:
                    turns.append(
                        TranscriptTurn(
                            user_content=u_text[:MAX_CONTENT_LENGTH],
                            assistant_content="",
                            tool_names=[],
                            timestamp=str(
                                extra_user.get("timestamp") or datetime.now(UTC).isoformat()
                            ),
                            session_id=session_id,
                        )
                    )

        # If assistant has replies to previously consumed user turns
        if len(assistant_entries) > pair_count:
            for extra_asst in assistant_entries[pair_count:]:
                a_text = IncrementalTranscriptParser._extract_text(extra_asst)
                tools = IncrementalTranscriptParser._extract_tool_names(extra_asst)
                if a_text or tools:
                    turns.append(
                        TranscriptTurn(
                            user_content="",
                            assistant_content=a_text[:MAX_CONTENT_LENGTH],
                            tool_names=tools,
                            timestamp=str(
                                extra_asst.get("timestamp") or datetime.now(UTC).isoformat()
                            ),
                            session_id=session_id,
                        )
                    )

        return turns

    @staticmethod
    def _extract_text(entry: dict[str, object]) -> str:
        """Extract plain text message content from various JSONL schemas."""
        msg = entry.get("message")
        if isinstance(msg, dict):
            content = msg.get("content") or msg.get("text")
        else:
            content = entry.get("content") or entry.get("message") or entry.get("text")

        if isinstance(content, dict):
            content = content.get("text") or content.get("content")

        if isinstance(content, str):
            return content.strip()

        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text_val = item.get("text") or item.get("content")
                    if isinstance(text_val, str):
                        parts.append(text_val)
            return "\n".join(parts).strip()

        return ""

    @staticmethod
    def _extract_tool_names(entry: dict[str, object]) -> list[str]:
        """Extract tool invocations from assistant message blocks."""
        tools: list[str] = []
        msg = entry.get("message")
        content = msg.get("content") if isinstance(msg, dict) else entry.get("content")

        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") in {
                    "tool_use",
                    "tool_call",
                }:
                    tool_name = item.get("name")
                    if isinstance(tool_name, str) and tool_name not in tools:
                        tools.append(tool_name)
        return tools
