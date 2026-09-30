"""Clean transcript reducer for cross-tool external session imports.

[INPUT]
- raw_lines: list[str] | list[dict[str, object]] (raw JSONL entries from Claude Code, Codex, Hermes)

[OUTPUT]
- CleanReductionResult: Deterministic, sanitized, tool-folded turns with token reduction metrics.

[POS]
Harness framework-level pure reducer. Strips vendor-specific CoT thinking, system prompts,
folds verbose tool stdout/stderr into compact Markdown callouts, scrubs sensitive credentials,
and outputs immutable turns that maximize LLM prefix prompt caching.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"sk-[a-zA-Z0-9_-]{20,}", re.ASCII), "[REDACTED_API_KEY]"),
    (re.compile(r"ghp_[a-zA-Z0-9]{36}", re.ASCII), "[REDACTED_GH_TOKEN]"),
    (re.compile(r"(?i)bearer\s+[a-zA-Z0-9_.-]{20,}", re.ASCII), "Bearer [REDACTED_TOKEN]"),
    (re.compile(r"AKIA[0-9A-Z]{16}", re.ASCII), "[REDACTED_AWS_KEY]"),
]

MAX_TOOL_OUTPUT_CHARS = 300


@dataclass(slots=True)
class CleanTurn:
    """A cleaned, model-agnostic conversation turn ready for instant resume."""

    turn_index: int
    user_content: str
    assistant_content: str
    tools_summary: list[str] = field(default_factory=list)
    timestamp: str = ""
    raw_tokens_estimate: int = 0
    clean_tokens_estimate: int = 0


@dataclass(slots=True)
class CleanReductionResult:
    """Summary and turns resulting from clean transcript reduction."""

    turns: list[CleanTurn] = field(default_factory=list)
    session_id: str | None = None
    session_title: str | None = None
    cwd: str | None = None
    source_tool: str = "generic"
    raw_char_count: int = 0
    clean_char_count: int = 0
    reduction_ratio: float = 0.0
    warnings: list[str] = field(default_factory=list)


def scrub_secrets(text: str) -> str:
    """Scrub common high-risk API keys and bearer tokens from text."""
    if not text:
        return ""
    result = text
    for pattern, replacement in SECRET_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def _estimate_tokens(text: str) -> int:
    """Deterministic token count estimate (approx 4 chars per token)."""
    return max(1, len(text) // 4) if text else 0


def _truncate_tool_output(output: str) -> str:
    """Truncate massive stdout/stderr into a compact preview."""
    output = output.strip()
    lines = output.splitlines()
    if len(lines) > 6 or len(output) > MAX_TOOL_OUTPUT_CHARS:
        head = "\n".join(lines[:3])
        tail = "\n".join(lines[-2:]) if len(lines) >= 5 else lines[-1]
        omitted = max(1, len(lines) - 5) if len(lines) >= 5 else 1
        return f"{head}\n... [{omitted} lines omitted] ...\n{tail}"
    return output


def _detect_source(entries: Sequence[Mapping[str, object]]) -> str:
    """Detect external tool origin from entry signatures."""
    for entry in entries:
        if "type" in entry and str(entry["type"]) in {"tool_use", "tool_result"}:
            return "claude_code"
        if "tool_calls" in entry or "turn_id" in entry:
            return "codex_cli"
        if "agent_name" in entry or "hermes" in str(entry.get("session_id", "")):
            return "hermes"
    return "generic"


class CleanTranscriptReducer:
    """Pure-function reducer for external transcripts."""

    @classmethod
    def reduce(
        cls,
        entries_or_lines: Sequence[str | Mapping[str, object]],
    ) -> CleanReductionResult:
        """Execute deterministic reduction over transcript entries."""
        parsed_entries: list[dict[str, object]] = []
        raw_char_count = 0
        warnings: list[str] = []

        for item in entries_or_lines:
            if isinstance(item, str):
                raw_char_count += len(item)
                item_str = item.strip()
                if not item_str:
                    continue
                try:
                    obj = json.loads(item_str)
                    if isinstance(obj, dict):
                        parsed_entries.append(obj)
                except json.JSONDecodeError:
                    warnings.append("skipped_invalid_json_line")
            elif isinstance(item, Mapping):
                dict_obj = dict(item)
                raw_char_count += len(json.dumps(dict_obj, default=str))
                parsed_entries.append(dict_obj)

        if not parsed_entries:
            return CleanReductionResult(
                raw_char_count=raw_char_count,
                warnings=warnings,
            )

        source_tool = _detect_source(parsed_entries)
        session_id: str | None = None
        session_title: str | None = None
        cwd: str | None = None

        # Pass 1: Extract global metadata
        for e in parsed_entries:
            if not session_id:
                sid = e.get("session_id") or e.get("sessionId") or e.get("id")
                if isinstance(sid, str) and sid:
                    session_id = sid
            if not session_title:
                t = e.get("title") or e.get("session_title") or e.get("summary")
                if isinstance(t, str) and t:
                    session_title = t.strip()[:100]
            if not cwd:
                d = e.get("cwd") or e.get("working_directory") or e.get("workspace")
                if isinstance(d, str) and d:
                    cwd = d.strip()

        # Pass 2: Extract turns while dropping system prompts and vendor CoT
        turns: list[CleanTurn] = []
        pending_user: str | None = None
        pending_asst_parts: list[str] = []
        pending_tools: list[str] = []
        pending_timestamp: str = ""
        pending_raw_chars = 0
        turn_index = 0

        def flush_turn() -> None:
            nonlocal pending_user, pending_asst_parts, pending_tools, pending_timestamp
            nonlocal pending_raw_chars, turn_index
            if pending_user is None and not pending_asst_parts and not pending_tools:
                return

            asst_text = "\n\n".join(p for p in pending_asst_parts if p.strip()).strip()
            if pending_tools:
                tools_block = "\n".join(f"> 🛠️ {t}" for t in pending_tools)
                asst_text = f"{tools_block}\n\n{asst_text}".strip() if asst_text else tools_block

            clean_user = scrub_secrets(pending_user or "")
            clean_asst = scrub_secrets(asst_text)
            clean_turn_chars = len(clean_user) + len(clean_asst)

            turns.append(
                CleanTurn(
                    turn_index=turn_index,
                    user_content=clean_user,
                    assistant_content=clean_asst,
                    tools_summary=list(pending_tools),
                    timestamp=pending_timestamp,
                    raw_tokens_estimate=_estimate_tokens(" " * max(1, pending_raw_chars)),
                    clean_tokens_estimate=_estimate_tokens(" " * max(1, clean_turn_chars)),
                )
            )
            turn_index += 1
            pending_user = None
            pending_asst_parts = []
            pending_tools = []
            pending_timestamp = ""
            pending_raw_chars = 0

        for entry in parsed_entries:
            role = str(
                entry.get("role")
                or entry.get("type")
                or (entry.get("message", {}) if isinstance(entry.get("message"), dict) else {}).get("role", "")
            ).lower()

            # Ignore system prompts to avoid prompt leakage and cache miss
            if role in {"system", "system_prompt", "developer"}:
                continue

            # Record timestamp if available
            ts = str(entry.get("timestamp") or entry.get("created_at") or "")
            if ts and not pending_timestamp:
                pending_timestamp = ts

            content_raw = entry.get("content") or entry.get("message", {}).get("content") if isinstance(entry.get("message"), dict) else entry.get("content")
            entry_chars = len(json.dumps(entry, default=str))

            if role in {"user", "human"}:
                # If there's already an active user and assistant, flush previous turn
                if pending_user is not None and (pending_asst_parts or pending_tools):
                    flush_turn()

                text_val = cls._extract_text(content_raw)
                pending_user = text_val
                pending_raw_chars += entry_chars

            elif role in {"assistant", "model", "ai"}:
                pending_raw_chars += entry_chars
                text_val, tool_calls = cls._extract_assistant_payload(entry, content_raw)
                if text_val:
                    pending_asst_parts.append(text_val)
                pending_tools.extend(tool_calls)

            elif role in {"tool", "tool_result"}:
                pending_raw_chars += entry_chars
                output = cls._extract_text(content_raw)
                name = str(entry.get("name") or entry.get("tool_name") or "tool")
                truncated = _truncate_tool_output(output)
                pending_tools.append(f"[{name}] -> {truncated}")

        # Flush final turn if present
        flush_turn()

        # Compute reduction metrics
        clean_char_count = sum(len(t.user_content) + len(t.assistant_content) for t in turns)
        reduction_ratio = (
            max(0.0, 1.0 - (clean_char_count / max(1, raw_char_count)))
            if raw_char_count > 0
            else 0.0
        )

        if not session_title and turns:
            session_title = turns[0].user_content[:60].replace("\n", " ").strip()

        return CleanReductionResult(
            turns=turns,
            session_id=session_id,
            session_title=session_title or "Imported Session",
            cwd=cwd,
            source_tool=source_tool,
            raw_char_count=raw_char_count,
            clean_char_count=clean_char_count,
            reduction_ratio=round(reduction_ratio, 4),
            warnings=warnings,
        )

    @classmethod
    def _extract_text(cls, content: object) -> str:
        """Extract clean text without CoT / thinking tags."""
        if isinstance(content, str):
            # Strip XML-like thinking blocks: <thinking>...</thinking>
            return re.sub(r"(?s)<thinking>.*?</thinking>", "", content).strip()
        if isinstance(content, list):
            chunks: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    item_type = str(item.get("type", "")).lower()
                    if item_type in {"text", "output"}:
                        text = str(item.get("text", "")).strip()
                        if text:
                            chunks.append(text)
                    # Exclude thinking blocks
                elif isinstance(item, str):
                    chunks.append(item.strip())
            return "\n\n".join(chunks).strip()
        return ""

    @classmethod
    def _extract_assistant_payload(
        cls,
        entry: Mapping[str, object],
        content: object,
    ) -> tuple[str, list[str]]:
        """Extract clean assistant response text and tool summaries."""
        tool_summaries: list[str] = []
        text_parts: list[str] = []

        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = str(block.get("type", "")).lower()
                if block_type in {"thinking", "redacted_thinking"}:
                    continue
                if block_type == "text":
                    txt = cls._extract_text(block.get("text", "")).strip()
                    if txt:
                        text_parts.append(txt)
                elif block_type == "tool_use":
                    tool_name = str(block.get("name", "tool"))
                    tool_input = block.get("input", {})
                    input_preview = json.dumps(tool_input, ensure_ascii=False)
                    if len(input_preview) > 60:
                        input_preview = f"{input_preview[:57]}..."
                    tool_summaries.append(f"[Executed: {tool_name} {input_preview}]")
        else:
            txt = cls._extract_text(content)
            if txt:
                text_parts.append(txt)

        # Check for OpenAI-style tool_calls
        raw_tool_calls = entry.get("tool_calls")
        if isinstance(raw_tool_calls, list):
            for tc in raw_tool_calls:
                if isinstance(tc, dict):
                    func = tc.get("function", {})
                    if isinstance(func, dict):
                        fname = str(func.get("name", "tool"))
                        fargs = str(func.get("arguments", ""))
                        if len(fargs) > 60:
                            fargs = f"{fargs[:57]}..."
                        tool_summaries.append(f"[Executed: {fname} {fargs}]")

        clean_text = "\n\n".join(text_parts).strip()
        return clean_text, tool_summaries


def clean_reduce_transcript(
    entries_or_lines: Sequence[str | Mapping[str, object]],
) -> CleanReductionResult:
    """Convenience functional wrapper for CleanTranscriptReducer.reduce."""
    return CleanTranscriptReducer.reduce(entries_or_lines)
