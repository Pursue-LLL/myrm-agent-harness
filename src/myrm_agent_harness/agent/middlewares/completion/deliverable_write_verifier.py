"""Deliverable write claim and unwritten code block verifier for CompletionGuard.

Detects when the assistant's final response either:
1. Claims a workspace file was written or saved without tool call records.
2. Generates substantial deliverable code or document blocks in the message body
   without invoking file_write_tool / file_edit_tool to persist them to workspace.

Complements _mutation_verifier with zero-call deliverable hallucination and leakage blocking.

[INPUT]
- Assistant final text + LoopGuard CallRecord window + optional latest user query text

[OUTPUT]
- check_deliverable_write_claim(): claim-based block reason or None
- check_unwritten_deliverables(): content-heuristic block reason and unwritten items
- detect_unwritten_deliverables(): list of detected unwritten deliverable items

[POS]
Harness middleware helper; invoked from CompletionGuard.aafter_model at completion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.security.guards.loop_guard import SuccessLevel

if TYPE_CHECKING:
    from myrm_agent_harness.agent.security.guards.loop_guard import CallRecord

_FILE_WRITE_TOOLS: frozenset[str] = frozenset(
    {
        "file_write_tool",
        "file_edit_tool",
    }
)

_WRITE_CLAIM_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?i)\b(saved to|wrote to|written to|saved as|created (?:the )?file|exported to|generated (?:the )?file)\b"
    ),
    re.compile(r"(已保存|已写入|写入到|保存至|保存到|已生成(?:文件|报告)?|已创建(?:文件)?|文件已)"),
)

_FILE_PATH_INDICATOR: re.Pattern[str] = re.compile(
    r"(?i)(`[^`]+`|workspace/[A-Za-z0-9_./-]+|[A-Za-z0-9_./-]+\.[A-Za-z0-9]{1,12})"
)

_CODE_BLOCK_PATTERN: re.Pattern[str] = re.compile(r"```([a-zA-Z0-9_\-+]*)\n([\s\S]*?)```")

_FILENAME_HINT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^(?:#|//|/\*|<!--)\s*(?:filename|filepath|file)?[:\s]*([a-zA-Z0-9_\-./]+\.[a-zA-Z0-9]{1,8})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:#|//)\s*([a-zA-Z0-9_\-./]+\.(?:py|ts|tsx|js|jsx|html|css|sh|sql|json|yaml|yml|md|csv))\b",
        re.IGNORECASE,
    ),
)

_IGNORED_LANGUAGES: frozenset[str] = frozenset(
    {
        "",
        "text",
        "txt",
        "plain",
        "plaintext",
        "output",
        "terminal",
        "console",
        "log",
        "diff",
    }
)

_LANG_TO_EXT_MAP: dict[str, str] = {
    "python": ".py",
    "py": ".py",
    "javascript": ".js",
    "js": ".js",
    "jsx": ".jsx",
    "typescript": ".ts",
    "ts": ".ts",
    "tsx": ".tsx",
    "html": ".html",
    "htm": ".html",
    "css": ".css",
    "bash": ".sh",
    "sh": ".sh",
    "shell": ".sh",
    "zsh": ".sh",
    "sql": ".sql",
    "json": ".json",
    "yaml": ".yaml",
    "yml": ".yaml",
    "csv": ".csv",
    "markdown": ".md",
    "md": ".md",
}

_EXPLANATION_INTENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?i)\b(what is|explain|difference between|how does|why does|what are|example|sample|demo|snippet|don't save|do not save|no need to save|just show|just explain)\b"
    ),
    re.compile(r"(什么是|解释一下|解释|为什么|区别是什么|怎么理解|如何理解|原理是什么|原理|例子|示例|演示|片段|不用保存|无需保存|不要保存|仅供参考|只看不写|纯演示)"),
)

_DELIVERABLE_INTENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\b(write|create|implement|build|generate|develop|scaffold|code|save to|write to|export)\b"),
    re.compile(r"(写一个|实现|开发|创建|生成|编写|输出|做个|写个|保存至|保存到|落盘|导出)"),
)

_BASH_COMMAND_ONLY_PATTERN: re.Pattern[str] = re.compile(
    r"^(?:npm|pnpm|yarn|pip|uv|cargo|go|docker|git|cd|ls|cat|curl|python|python3|node)\s+"
)


@dataclass(frozen=True)
class UnwrittenDeliverable:
    """Represents a substantial code or artifact deliverable found in assistant message."""

    language: str
    content: str
    line_count: int
    filename_hint: str | None
    suggested_ext: str
    is_code: bool


def detect_claimed_file_write(content: str) -> bool:
    """Return True when assistant text likely claims a deliverable file write."""
    text = content.strip()
    if not text:
        return False

    has_claim = any(pattern.search(text) for pattern in _WRITE_CLAIM_PATTERNS)
    if not has_claim:
        return False

    return _FILE_PATH_INDICATOR.search(text) is not None


def has_successful_file_write_calls(records: list[CallRecord]) -> bool:
    """Return True when at least one successful file write/edit tool call exists."""
    for record in records:
        if record.tool_name not in _FILE_WRITE_TOOLS:
            continue
        if record.success_level != SuccessLevel.FAILURE:
            return True
    return False


def _extract_filename_hint(code_body: str) -> str | None:
    lines = code_body.strip().splitlines()
    for line in lines[:3]:
        line_clean = line.strip()
        for pattern in _FILENAME_HINT_PATTERNS:
            match = pattern.search(line_clean)
            if match:
                return match.group(1).strip()
    return None


def _is_bash_command_snippet(lines: list[str]) -> bool:
    if len(lines) > 8:
        return False
    return all(
        not line.strip() or line.strip().startswith("#") or bool(_BASH_COMMAND_ONLY_PATTERN.match(line.strip()))
        for line in lines
    )


def detect_unwritten_deliverables(
    content: str,
    latest_user_text: str | None = None,
) -> list[UnwrittenDeliverable]:
    """Inspect assistant content for unpersisted substantive code blocks or artifacts.

    Applies heuristics to separate pedagogical explanations from physical deliverables.
    """
    text = content.strip()
    if not text:
        return []

    user_text = (latest_user_text or "").strip()
    is_pure_explanation = any(p.search(user_text) for p in _EXPLANATION_INTENT_PATTERNS) if user_text else False
    is_explicit_deliverable = any(p.search(user_text) for p in _DELIVERABLE_INTENT_PATTERNS) if user_text else False

    deliverables: list[UnwrittenDeliverable] = []

    for match in _CODE_BLOCK_PATTERN.finditer(text):
        raw_lang = match.group(1).strip().lower()
        body = match.group(2)
        lines = [line for line in body.splitlines() if line.strip()]
        line_count = len(lines)

        if raw_lang in _IGNORED_LANGUAGES:
            continue

        if raw_lang in ("bash", "sh", "shell", "zsh") and _is_bash_command_snippet(lines):
            continue

        filename_hint = _extract_filename_hint(body)
        suggested_ext = _LANG_TO_EXT_MAP.get(raw_lang, ".txt")
        is_code = raw_lang not in ("markdown", "md", "csv", "json", "yaml", "yml")

        # Threshold evaluation with byte density awareness for structured data
        byte_count = len(body.encode("utf-8"))
        is_substantive = False
        if filename_hint is not None:
            # Explicit filename comment is a strong indicator of a file deliverable
            is_substantive = line_count >= 5
        elif not is_code and is_explicit_deliverable:
            # Structured data (csv, json, yaml) under explicit deliverable intent:
            # Wide tables or compact JSON configs might have fewer lines but substantial payload
            is_substantive = line_count >= 10 or (line_count >= 5 and byte_count >= 250)
        elif not is_code:
            # Standard structured data deliverable
            is_substantive = line_count >= 14 or (line_count >= 6 and byte_count >= 350)
        elif is_explicit_deliverable:
            # User specifically requested writing/implementing a code artifact
            is_substantive = line_count >= 12
        elif is_pure_explanation:
            # Pure educational inquiry: require substantial full-file structure
            is_substantive = line_count >= 24 and (
                "if __name__ == '__main__':" in body
                or 'if __name__ == "__main__":' in body
                or "export default" in body
                or "<!DOCTYPE html>" in body
            )
        else:
            # Standard threshold for unsolicited substantive code delivery
            is_substantive = line_count >= 16

        if is_substantive:
            deliverables.append(
                UnwrittenDeliverable(
                    language=raw_lang,
                    content=body,
                    line_count=line_count,
                    filename_hint=filename_hint,
                    suggested_ext=suggested_ext,
                    is_code=is_code,
                )
            )

    return deliverables


def check_deliverable_write_claim(content: str, records: list[CallRecord]) -> str | None:
    """Block completion when a write is claimed without any successful write tool call."""
    if not detect_claimed_file_write(content):
        return None
    if has_successful_file_write_calls(records):
        return None
    return (
        "The assistant response claims a workspace file was written or saved, "
        "but no successful file_write_tool or file_edit_tool calls were recorded. "
        "Use a file write tool before finishing, or revise the response."
    )


def check_unwritten_deliverables(
    content: str,
    records: list[CallRecord],
    latest_user_text: str | None = None,
) -> tuple[str | None, list[UnwrittenDeliverable]]:
    """Block completion when substantial deliverable code exists without any write tool call."""
    if has_successful_file_write_calls(records):
        return None, []

    unwritten = detect_unwritten_deliverables(content, latest_user_text=latest_user_text)
    if not unwritten:
        return None, []

    item_summaries: list[str] = []
    for item in unwritten:
        name_desc = item.filename_hint or f"unnamed_{item.language}_deliverable{item.suggested_ext}"
        item_summaries.append(f"{name_desc} ({item.line_count} lines)")

    summary_str = ", ".join(item_summaries)
    reason = (
        f"Substantial unpersisted deliverables detected in final response: [{summary_str}]. "
        "The agent generated complete code/artifact content but omitted persisting it to workspace. "
        "Call file_write_tool to save the file(s) before finishing."
    )
    return reason, unwritten


def check_unwritten_deliverable(
    content: str,
    records: list[CallRecord],
    latest_user_text: str | None = None,
) -> str | None:
    """Convenience helper returning only the block reason for unwritten deliverables."""
    reason, _ = check_unwritten_deliverables(content, records, latest_user_text=latest_user_text)
    return reason


__all__ = [
    "UnwrittenDeliverable",
    "check_deliverable_write_claim",
    "check_unwritten_deliverable",
    "check_unwritten_deliverables",
    "detect_claimed_file_write",
    "detect_unwritten_deliverables",
    "has_successful_file_write_calls",
]
