"""Salient Tool Output Filter & Verbatim Evidence Extractor.

[INPUT]
- langchain_core.messages::ToolMessage, BaseMessage (POS: LangChain tool message abstraction)

[OUTPUT]
- SalientToolEvidence: Structured salient tool output evidence dataclass
- SalientToolFilterConfig: Configuration thresholds for salience detection and truncation
- extract_salient_tool_evidences: Pure functional extractor for high-value tool outputs before context compaction
- strip_ansi_sequences: Fast regex-based ANSI escape sequence sanitizer

[POS]
Harness framework layer context management. Extracts verbatim tool outputs (errors, failed tests,
non-zero exit codes) before context compaction to ensure historical facts remain searchable and verifiable.
Zero LLM cost, bounded memory budget, and strict Prompt Cache preservation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Mapping, Sequence

# Regex to strip all terminal ANSI escape sequences (colors, cursor control, resets)
_ANSI_ESCAPE_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

# Common salient error keywords for scoring
_HIGH_SEVERITY_KEYWORDS: tuple[str, ...] = (
    "traceback (most recent call last):",
    "syntaxerror:",
    "typeerror:",
    "attributeerror:",
    "importerror:",
    "modulenotfounderror:",
    "assertionerror:",
    "panic:",
    "fatal error:",
    "failed (failures=",
    "build failed",
    "compilation failed",
    "exit code: 1",
    "exit code: 2",
    "exit code 1",
    "command failed",
    "http 403",
    "http 404",
    "http 500",
    "http 502",
    "http 503",
    "http 429",
)

_EXIT_CODE_RE = re.compile(r"(?:exit\s+code\s*[:=]\s*|exit_code\s*[:=]\s*)(\d+)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class SalientToolEvidence:
    """Structured verbatim evidence extracted from a salient tool execution turn."""

    tool_name: str
    tool_call_id: str
    command: str
    exit_code: int | None
    snippet: str
    is_error: bool
    salience_score: float
    occurred_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(frozen=True, slots=True)
class SalientToolFilterConfig:
    """Configurable boundaries for salient tool evidence extraction."""

    max_snippet_chars: int = 2048
    head_chars: int = 1024
    tail_chars: int = 1024
    max_evidences_per_compaction: int = 5
    min_salience_threshold: float = 1.0


def strip_ansi_sequences(text: str) -> str:
    """Strip terminal ANSI formatting to ensure clean full-text search and zero token waste."""
    if not text:
        return ""
    clean = _ANSI_ESCAPE_RE.sub("", text)
    return clean.replace("\r\n", "\n").replace("\r", "")


def _truncate_with_head_tail(text: str, head_chars: int, tail_chars: int) -> str:
    """Keep head and tail context for long outputs while cleanly excising middle noise."""
    total_budget = head_chars + tail_chars
    if len(text) <= total_budget:
        return text

    head = text[:head_chars]
    tail = text[-tail_chars:]
    omitted = len(text) - total_budget
    return f"{head}\n\n[... truncated {omitted} characters ...]\n\n{tail}"


def _detect_exit_code(content: str, metadata: Mapping[str, object] | None) -> int | None:
    """Extract integer exit code from tool payload or structured metadata."""
    if metadata:
        meta_code = metadata.get("exit_code")
        if isinstance(meta_code, int):
            return meta_code

    match = _EXIT_CODE_RE.search(content)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    return None


def _calculate_salience(
    content_lower: str,
    exit_code: int | None,
    is_error_flag: bool,
    tool_name: str,
) -> float:
    """Deterministic salience score calculation without LLM overhead."""
    score = 0.0

    # Non-zero exit code indicates execution failure
    if exit_code is not None and exit_code != 0:
        score += 3.0

    if is_error_flag:
        score += 2.5

    # Check for core error keywords
    for kw in _HIGH_SEVERITY_KEYWORDS:
        if kw in content_lower:
            score += 2.0
            break

    # Prioritize key developer tooling
    if tool_name in {"bash", "bash_code_execute_tool", "python_execute", "test_runner", "curl"}:
        score += 0.5

    return score


def extract_salient_tool_evidences(
    messages: Sequence[object],
    config: SalientToolFilterConfig | None = None,
) -> list[SalientToolEvidence]:
    """Extract high-value verbatim tool outputs from message sequence before compaction.

    Args:
        messages: Sequence of LangChain or Dict message objects
        config: Extraction boundaries and thresholds

    Returns:
        List of SalientToolEvidence ordered by salience score descending
    """
    cfg = config or SalientToolFilterConfig()
    candidates: list[SalientToolEvidence] = []

    for msg in messages:
        # Resolve message fields duck-typed across LangChain ToolMessage and raw dicts
        role = getattr(msg, "type", None) or getattr(msg, "role", None)
        if isinstance(msg, dict):
            role = msg.get("role") or msg.get("type")

        if role not in {"tool", "tool_result"}:
            continue

        raw_content = getattr(msg, "content", None)
        if raw_content is None and isinstance(msg, dict):
            raw_content = msg.get("content")

        content_str = str(raw_content or "")
        if not content_str.strip():
            continue

        clean_text = strip_ansi_sequences(content_str)
        content_lower = clean_text.lower()

        # Extract metadata
        meta: Mapping[str, object] = {}
        if hasattr(msg, "additional_kwargs") and isinstance(msg.additional_kwargs, dict):
            meta = msg.additional_kwargs
        elif isinstance(msg, dict) and "metadata" in msg and isinstance(msg["metadata"], dict):
            meta = msg["metadata"]

        tool_name = str(
            getattr(msg, "name", None)
            or (meta.get("tool_name") if meta else None)
            or "unknown_tool"
        )
        tool_call_id = str(
            getattr(msg, "tool_call_id", None)
            or (meta.get("tool_call_id") if meta else None)
            or ""
        )
        has_error_kw = any(kw in content_lower for kw in _HIGH_SEVERITY_KEYWORDS)
        is_error = bool(
            getattr(msg, "status", "") == "error"
            or meta.get("is_error") is True
            or has_error_kw
        )

        exit_code = _detect_exit_code(clean_text, meta)

        score = _calculate_salience(content_lower, exit_code, is_error, tool_name)
        if score < cfg.min_salience_threshold:
            continue

        truncated_snippet = _truncate_with_head_tail(
            clean_text,
            cfg.head_chars,
            cfg.tail_chars,
        )

        command_hint = str(meta.get("command") or meta.get("input") or "")
        if not command_hint and "command:" in content_lower:
            cmd_match = re.search(r"command\s*:\s*([^\n]+)", clean_text, re.IGNORECASE)
            if cmd_match:
                command_hint = cmd_match.group(1).strip()

        candidates.append(
            SalientToolEvidence(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                command=command_hint[:200],
                exit_code=exit_code,
                snippet=truncated_snippet,
                is_error=is_error or (exit_code is not None and exit_code != 0),
                salience_score=score,
            )
        )

    # Sort candidates by salience descending
    candidates.sort(key=lambda x: x.salience_score, reverse=True)
    return candidates[: cfg.max_evidences_per_compaction]
