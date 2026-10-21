"""High-fidelity parser for Hermes Agent session transcripts (JSON or JSONL).

[INPUT]
- .types::CanonicalTranscriptTurn, CanonicalTurnRole, CanonicalToolCall, TranscriptParseResult
- .path_remapper::SandboxPathRemapper
- .tool_compactor::compact_tool_output

[OUTPUT]
- HermesTranscriptParser: Streaming and document parser for Hermes Agent sessions.

[POS]
runtime/context/transcripts/hermes_parser.py
Extracts and normalizes raw JSON/JSONL transcripts from ~/.hermes/sessions/ into canonical turns.
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


class HermesTranscriptParser:
    """Parses Hermes Agent session files into canonical turns."""

    def __init__(
        self,
        sandbox_root: str = "/workspace",
        host_root_hint: str | None = None,
    ) -> None:
        self._sandbox_root = sandbox_root
        self._host_root_hint = host_root_hint

    def parse_file(self, file_path: Path) -> TranscriptParseResult:
        """Parse a Hermes session JSON or JSONL file."""
        with open(file_path, encoding="utf-8", errors="replace") as f:
            return self.parse_stream(f, default_session_id=file_path.stem)

    def parse_stream(self, stream: TextIO, default_session_id: str = "hermes-session") -> TranscriptParseResult:
        """Parse JSON or JSONL stream from Hermes Agent."""
        raw_content = stream.read()
        lines = [line.strip() for line in raw_content.splitlines() if line.strip()]
        if not lines:
            return TranscriptParseResult(
                session_id=default_session_id,
                title="Empty Hermes Session",
                turns=[],
                source_platform="hermes",
                created_at=0.0,
                updated_at=0.0,
            )

        # Check if first line or entire text is a single JSON document with messages
        is_single_doc = False
        data: dict[str, object] = {}
        try:
            parsed_doc = json.loads(raw_content)
            if isinstance(parsed_doc, dict) and ("messages" in parsed_doc or "turns" in parsed_doc):
                is_single_doc = True
                data = parsed_doc
        except Exception:
            is_single_doc = False

        if is_single_doc:
            return self._parse_single_doc(data, default_session_id)

        # Fallback to JSONL stream
        return self._parse_jsonl_stream(lines, default_session_id)

    def _parse_single_doc(self, data: dict[str, object], default_session_id: str) -> TranscriptParseResult:
        session_id = str(data.get("session_id") or data.get("id") or default_session_id)
        created_at = float(data.get("created_at") or data.get("timestamp") or 0.0)
        messages = data.get("messages") or data.get("turns") or []
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

                if role_raw in {"user", "human"}:
                    if not session_title and content.strip():
                        session_title = content.strip().splitlines()[0][:45]
                    turns.append(
                        CanonicalTranscriptTurn(
                            turn_id=f"hermes_u_{idx}",
                            role=CanonicalTurnRole.USER,
                            content=content.strip(),
                            timestamp=ts,
                        )
                    )
                elif role_raw in {"assistant", "model"}:
                    tool_calls: list[CanonicalToolCall] = []
                    raw_tool_calls = msg.get("tool_calls") or []
                    if isinstance(raw_tool_calls, list):
                        for tc_idx, tc in enumerate(raw_tool_calls):
                            if not isinstance(tc, dict):
                                continue
                            call_id = str(tc.get("id") or f"call_{idx}_{tc_idx}")
                            func = tc.get("function") or tc
                            tool_name = str(func.get("name") or "tool")
                            args_raw = func.get("arguments") or {}
                            if isinstance(args_raw, str):
                                try:
                                    args_dict = json.loads(args_raw)
                                except Exception:
                                    args_dict = {"raw": args_raw}
                            elif isinstance(args_raw, dict):
                                args_dict = args_raw
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
                            turn_id=f"hermes_a_{idx}",
                            role=CanonicalTurnRole.ASSISTANT,
                            content=content.strip(),
                            tool_calls=tool_calls,
                            thinking_trace=str(msg.get("thinking") or "") or None,
                            timestamp=ts,
                        )
                    )

        return TranscriptParseResult(
            session_id=session_id,
            title=session_title or "Hermes Session",
            turns=turns,
            source_platform="hermes",
            created_at=created_at,
            updated_at=created_at,
            detected_workspace_hint=detected_host_root,
        )

    def _parse_jsonl_stream(self, lines: list[str], default_session_id: str) -> TranscriptParseResult:
        turns: list[CanonicalTranscriptTurn] = []
        session_id = default_session_id
        session_title = ""
        created_at = 0.0
        detected_host_root = self._host_root_hint
        remapper = SandboxPathRemapper(host_root=detected_host_root, sandbox_root=self._sandbox_root)

        for idx, line in enumerate(lines):
            try:
                entry = json.loads(line)
            except Exception:
                continue
            if not isinstance(entry, dict):
                continue

            if not session_id or session_id == default_session_id:
                sid = entry.get("session_id") or entry.get("id")
                if isinstance(sid, str) and sid:
                    session_id = sid

            role = str(entry.get("role") or entry.get("type") or "").lower()
            content = str(entry.get("content") or "")
            ts = float(entry.get("timestamp") or 0.0)
            if created_at == 0.0 and ts > 0.0:
                created_at = ts

            if role in {"user", "human"}:
                clean_content = remapper.remap_text(content.strip())
                if not session_title and clean_content:
                    session_title = clean_content.splitlines()[0][:45]
                turns.append(
                    CanonicalTranscriptTurn(
                        turn_id=f"hermes_u_{idx}",
                        role=CanonicalTurnRole.USER,
                        content=clean_content,
                        timestamp=ts,
                    )
                )
            elif role in {"assistant", "model"}:
                clean_content = remapper.remap_text(content.strip())
                turns.append(
                    CanonicalTranscriptTurn(
                        turn_id=f"hermes_a_{idx}",
                        role=CanonicalTurnRole.ASSISTANT,
                        content=clean_content,
                        thinking_trace=str(entry.get("thinking") or "") or None,
                        timestamp=ts,
                    )
                )

        return TranscriptParseResult(
            session_id=session_id,
            title=session_title or "Hermes Session",
            turns=turns,
            source_platform="hermes",
            created_at=created_at,
            updated_at=created_at,
            detected_workspace_hint=detected_host_root,
        )
