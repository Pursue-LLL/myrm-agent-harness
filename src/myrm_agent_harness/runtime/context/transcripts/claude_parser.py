"""High-fidelity parser for Anthropic Claude Code session transcripts (JSONL).

[INPUT]
- .types::CanonicalTranscriptTurn, CanonicalTurnRole, CanonicalToolCall, TranscriptParseResult
- .path_remapper::SandboxPathRemapper
- .tool_compactor::compact_tool_output

[OUTPUT]
- ClaudeTranscriptParser: High-throughput streaming parser for Claude Code sessions.

[POS]
runtime/context/transcripts/claude_parser.py
Extracts and normalizes raw JSONL transcripts from ~/.claude/projects/ into canonical turns.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TextIO

from .path_remapper import SandboxPathRemapper
from .tool_compactor import compact_tool_output
from .types import (
    CanonicalToolCall,
    CanonicalTranscriptTurn,
    CanonicalTurnRole,
    TranscriptParseResult,
)

logger = logging.getLogger(__name__)

_SYSTEM_REMINDER_PATTERN = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)
_THINKING_TAG_PATTERN = re.compile(r"<thinking>(.*?)</thinking>", re.DOTALL)


class ClaudeTranscriptParser:
    """Parses Claude Code JSONL files into clean, continuous conversational turns."""

    def __init__(
        self,
        sandbox_root: str = "/workspace",
        host_root_hint: str | None = None,
    ) -> None:
        self._sandbox_root = sandbox_root
        self._host_root_hint = host_root_hint

    def parse_file(self, file_path: Path) -> TranscriptParseResult:
        """Parse a Claude Code JSONL transcript file."""
        with open(file_path, encoding="utf-8", errors="replace") as f:
            return self.parse_stream(f, default_session_id=file_path.stem)

    def parse_stream(self, stream: TextIO, default_session_id: str = "claude-session") -> TranscriptParseResult:
        """Parse lines of JSON from a stream."""
        turns: list[CanonicalTranscriptTurn] = []
        pending_tool_calls: dict[str, dict[str, object]] = {}
        detected_host_root = self._host_root_hint
        first_created_at = 0.0
        last_updated_at = 0.0
        session_title = ""

        remapper = SandboxPathRemapper(host_root=detected_host_root, sandbox_root=self._sandbox_root)

        for line_num, line in enumerate(stream, 1):
            line_str = line.strip()
            if not line_str:
                continue
            try:
                event = json.loads(line_str)
            except Exception:
                continue

            if not isinstance(event, dict):
                continue

            # Update timestamps
            ts = float(event.get("timestamp") or event.get("created_at") or 0.0)
            if ts > 0:
                if first_created_at == 0.0:
                    first_created_at = ts
                last_updated_at = max(last_updated_at, ts)

            # Heuristic host root detection from workspace/cwd in event if not yet detected
            if not detected_host_root:
                cwd = event.get("cwd") or event.get("working_directory") or (event.get("meta") or {}).get("cwd")
                if isinstance(cwd, str) and cwd.startswith(("/", "C:\\", "D:\\")):
                    detected_host_root = cwd
                    remapper = SandboxPathRemapper(host_root=detected_host_root, sandbox_root=self._sandbox_root)

            event_type = str(event.get("type", "")).lower()
            role_raw = str(event.get("role", "")).lower()

            # 1. User message handling
            if role_raw == "user" or event_type in ("user", "user_prompt", "user_message"):
                raw_text = str(event.get("content") or event.get("text") or event.get("message") or "")
                clean_text = _SYSTEM_REMINDER_PATTERN.sub("", raw_text).strip()
                if clean_text:
                    if not session_title:
                        session_title = clean_text.splitlines()[0][:45]

                    turn = CanonicalTranscriptTurn(
                        turn_id=f"claude_u_{line_num}",
                        role=CanonicalTurnRole.USER,
                        content=clean_text,
                        timestamp=ts,
                        source_event_type="user",
                    )
                    turns.append(turn)

            # 2. Assistant message / tool calls
            elif role_raw in ("assistant", "model") or event_type in (
                "assistant",
                "assistant_message",
                "response",
                "model",
            ):
                raw_text = str(event.get("content") or event.get("text") or "")
                thinking_trace: str | None = None

                # Extract <thinking> blocks if embedded
                match = _THINKING_TAG_PATTERN.search(raw_text)
                if match:
                    thinking_trace = match.group(1).strip()
                    raw_text = _THINKING_TAG_PATTERN.sub("", raw_text).strip()
                elif event.get("thought") or event.get("thinking"):
                    thinking_trace = str(event.get("thought") or event.get("thinking")).strip()

                # Process attached tool uses
                turn_tool_calls: list[CanonicalToolCall] = []
                tool_uses = event.get("tool_uses") or event.get("tool_calls") or []
                if isinstance(tool_uses, list):
                    for tu in tool_uses:
                        if not isinstance(tu, dict):
                            continue
                        call_id = str(tu.get("id") or tu.get("tool_use_id") or f"call_{len(turn_tool_calls)}")
                        tool_name = str(tu.get("name") or tu.get("tool_name") or "unknown_tool")
                        raw_args = tu.get("input") or tu.get("arguments") or {}
                        norm_args = raw_args if isinstance(raw_args, dict) else {"raw": raw_args}
                        remapped_args = remapper.remap_arguments(norm_args)

                        raw_call = CanonicalToolCall(
                            call_id=call_id,
                            tool_name=tool_name,
                            arguments=remapped_args,
                            output=None,
                        )
                        turn_tool_calls.append(raw_call)
                        pending_tool_calls[call_id] = {"index": len(turns), "tool_call_idx": len(turn_tool_calls) - 1}

                turn = CanonicalTranscriptTurn(
                    turn_id=f"claude_a_{line_num}",
                    role=CanonicalTurnRole.ASSISTANT,
                    content=raw_text,
                    thinking_trace=thinking_trace,
                    tool_calls=turn_tool_calls,
                    timestamp=ts,
                    source_event_type="assistant",
                )
                turns.append(turn)

            # 3. Tool results / outputs
            elif event_type in ("tool_result", "tool_output") or "tool_result" in event:
                call_id = str(event.get("tool_use_id") or event.get("call_id") or "")
                tool_output_str = str(event.get("content") or event.get("output") or event.get("result") or "")
                tool_output_remapped = remapper.remap_text(tool_output_str)

                # If matching previous assistant tool call, attach and compact
                if call_id in pending_tool_calls:
                    ref = pending_tool_calls.pop(call_id)
                    turn_idx = int(ref["index"])
                    tc_idx = int(ref["tool_call_idx"])
                    if 0 <= turn_idx < len(turns):
                        target_turn = turns[turn_idx]
                        if 0 <= tc_idx < len(target_turn.tool_calls):
                            orig_call = target_turn.tool_calls[tc_idx]
                            updated_call = CanonicalToolCall(
                                call_id=orig_call.call_id,
                                tool_name=orig_call.tool_name,
                                arguments=orig_call.arguments,
                                output=tool_output_remapped,
                                exit_code=int(event.get("exit_code", 0)),
                                is_error=bool(event.get("is_error", False)),
                            )
                            compacted_call = compact_tool_output(updated_call)
                            new_tool_calls = list(target_turn.tool_calls)
                            new_tool_calls[tc_idx] = compacted_call
                            turns[turn_idx] = CanonicalTranscriptTurn(
                                turn_id=target_turn.turn_id,
                                role=target_turn.role,
                                content=target_turn.content,
                                thinking_trace=target_turn.thinking_trace,
                                tool_calls=new_tool_calls,
                                timestamp=target_turn.timestamp,
                                source_event_type=target_turn.source_event_type,
                                metadata=target_turn.metadata,
                            )

        if not session_title:
            session_title = "Claude Code Imported Session"

        total_tool_calls = sum(len(t.tool_calls) for t in turns)
        return TranscriptParseResult(
            session_id=default_session_id,
            title=session_title,
            turns=turns,
            source_platform="claude_code",
            created_at=first_created_at or 0.0,
            updated_at=last_updated_at or first_created_at or 0.0,
            detected_workspace_hint=detected_host_root,
            total_tool_calls=total_tool_calls,
        )
