"""Memory recall budget guardrails.

[INPUT]
- (none)

[OUTPUT]
- normalize_recall_limit: Normalize model-provided recall limit into a safe range.
- truncate_recall_content: Truncate recalled memory content while preserving metadata space.
- line_cost: Calculate newline-aware output cost for recall budget accounting.

[POS]
Memory recall budget guardrail. Keeps agent-facing recall output bounded without coupling to business context.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_RECALL_LIMIT = 5
MIN_RECALL_LIMIT = 1
MAX_RECALL_LIMIT = 15
MAX_RECALL_OUTPUT_CHARS = 12_000
MAX_RECALL_CONTENT_CHARS = 900
MIN_RECALL_CONTENT_CHARS = 80

_OMITTED_CONTENT = "[content omitted: recall output budget exhausted]"


@dataclass(frozen=True)
class BudgetedRecallLine:
    line: str | None
    next_chars: int
    truncated: bool


def normalize_recall_limit(value: object) -> int:
    """Normalize model-provided recall limit into the context-safe range."""
    if value is None or isinstance(value, bool):
        raw_limit = DEFAULT_RECALL_LIMIT
    elif isinstance(value, int):
        raw_limit = value
    elif isinstance(value, str):
        raw_limit = _parse_limit_string(value)
    else:
        raw_limit = DEFAULT_RECALL_LIMIT
    return min(max(raw_limit, MIN_RECALL_LIMIT), MAX_RECALL_LIMIT)


def truncate_recall_content(content: str, max_chars: int = MAX_RECALL_CONTENT_CHARS) -> tuple[str, bool]:
    """Return recall content truncated to fit a tool-output budget."""
    if max_chars < MIN_RECALL_CONTENT_CHARS:
        return _OMITTED_CONTENT, bool(content)
    if len(content) <= max_chars:
        return content, False

    marker = f" ... [truncated {len(content) - max_chars} chars; refine query for more detail]"
    head_chars = max_chars - len(marker)
    if head_chars < MIN_RECALL_CONTENT_CHARS:
        return _OMITTED_CONTENT, True
    return f"{content[:head_chars].rstrip()}{marker}", True


def line_cost(line: str) -> int:
    """Return output budget cost for one newline-joined line."""
    return len(line) + 1


def budget_recall_line(
    *,
    prefix: str,
    content: str,
    suffix: str,
    output_chars: int,
    max_body_chars: int,
    max_content_chars: int = MAX_RECALL_CONTENT_CHARS,
) -> BudgetedRecallLine:
    """Format a recall line if it fits the remaining output budget."""
    remaining = max_body_chars - output_chars - line_cost(prefix + suffix)
    content_limit = min(max_content_chars, remaining)
    truncated_content, was_truncated = truncate_recall_content(content, content_limit)
    line = f"{prefix}{truncated_content}{suffix}"
    if output_chars + line_cost(line) > max_body_chars:
        return BudgetedRecallLine(line=None, next_chars=output_chars, truncated=True)
    return BudgetedRecallLine(line=line, next_chars=output_chars + line_cost(line), truncated=was_truncated)


def _parse_limit_string(value: str) -> int:
    stripped = value.strip()
    if not stripped:
        return DEFAULT_RECALL_LIMIT
    try:
        return int(stripped)
    except ValueError:
        return DEFAULT_RECALL_LIMIT
