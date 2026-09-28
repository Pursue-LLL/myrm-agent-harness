"""High-fidelity parser for OpenAI Codex CLI session transcripts (JSON).

[INPUT]
- .types::CanonicalTranscriptTurn, CanonicalTurnRole, CanonicalToolCall, TranscriptParseResult
- .path_remapper::SandboxPathRemapper
- .tool_compactor::compact_tool_output

[OUTPUT]
- CodexTranscriptParser: Structured parser for Codex CLI session files.

[POS]
runtime/context/transcripts/codex_parser.py
Extracts and normalizes raw JSON transcripts from ~/.codex/sessions/ into canonical turns.
"""

from __future__ import annotations

import json
import logging
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


class CodexTranscriptParser:
    """Parses Codex CLI JSON session files into canonical turns."""

    def __init__(
        self,
        sandbox_root: str = "/workspace",
        host_root_hint: str | None = None,
    ) -> None:
        self._sandbox_root = sandbox_root
        self._host_root_hint = host_root_hint

    def parse_file(self, file_path: Path) -> TranscriptParseResult:
        """Parse a Codex session JSON file."""
        with open(file_path, encoding="utf-8", errors="replace") as f:
            return self.parse_stream(f, default_session_id=file_path.stem)

    def parse_stream(self, stream: TextIO, default_session_id: str = "codex-session") -> TranscriptParseResult:
        """Parse JSON document from a stream."""
        raw_content = stream.read()
        try:
            data = json.loads(raw_content)
        except Exception:
            return TranscriptParseResult(
                session_id=default_session_id,
                title="Invalid Codex Session",
                turns=[],
                source_platform="codex",
                created_at=0.0,
                updated_at=0.0,
            )

        if not isinstance(data, dict):
            return TranscriptParseResult(
                session_id=default_session_id,
                title="Invalid Codex Session",
                turns=[],
                source_platform="codex",
                created_at=0.0,
                updated_at=0.0,
            )

        session_id = str(data.get("id") or default_session_id)
        created_at = float(data.get("created_at") or data.get("timestamp") or 0.0)
        messages = data.get("messages") or data.get("history") or data.get("turns") or []
        detected_host_root = self._host_root_hint or str(data.get("workspace_root") or data.get("cwd") or "") or None

        remapper = SandboxPathRemapper(host_root=detected_host_root, sandbox_root=self._sandbox_root)

        turns: list[CanonicalTranscriptTurn] = []
        session_title = str(data.get("title") or "")

        if isinstance(messages, list):
            for idx, msg in enumerate(messages):
                if not isinstance(msg, dict):
                    continue
                role_raw = str(msg.get("role", "")).lower()
                content = str(msg.get("content") or "")
                ts = float(msg.get("timestamp") or created_at)

                if role_raw == "user":
                    if not session_title and content.strip():
                        session_title = content.strip().splitlines()[0][:45]
                    turns.append(
                        CanonicalTranscriptTurn(
                            turn_id=f"codex_u_{idx}",
                            role=CanonicalTurnRole.USER,
                            content=content.strip(),
                            timestamp=ts,
                        )
                    )
                elif role_raw == "assistant":
                    tool_calls: list[CanonicalToolCall] = []
                    raw_tool_calls = msg.get("tool_calls") or []
                    if isinstance(raw_tool_calls, list):
                        for tc_idx, tc in enumerate(raw_tool_calls):
                            if not isinstance(tc, dict):
                                continue
                            call_id = str(tc.get("id") or f"call_{idx}_{tc_idx}")
                            func = tc.get("function") or tc
                            tool_name = str(func.get("name") or "tool")
                            args_str = func.get("arguments") or {}
                            if isinstance(args_str, str):
                                try:
                                    args_dict = json.loads(args_str)
                                except Exception:
                                    args_dict = {"raw": args_str}
                            elif isinstance(args_str, dict):
                                args_dict = args_str
                            else:
                                args_dict = {}

                            remapped_args = remapper.remap_arguments(args_dict)
                            raw_call = CanonicalToolCall(
                                call_id=call_id,
                                tool_name=tool_name,
                                arguments=remapped_args,
                                output=remapper.remap_text(str(tc.get("output") or "")),
                            )
                            tool_calls.append(compact_tool_output(raw_call))

                    turns.append(
                        CanonicalTranscriptTurn(
                            turn_id=f"codex_a_{idx}",
                            role=CanonicalTurnRole.ASSISTANT,
                            content=content.strip(),
                            tool_calls=tool_calls,
                            timestamp=ts,
                        )
                    )

        if not session_title:
            session_title = "Codex CLI Imported Session"

        total_tool_calls = sum(len(t.tool_calls) for t in turns)
        return TranscriptParseResult(
            session_id=session_id,
            title=session_title,
            turns=turns,
            source_platform="codex",
            created_at=created_at,
            updated_at=created_at,
            detected_workspace_hint=detected_host_root,
            total_tool_calls=total_tool_calls,
        )
