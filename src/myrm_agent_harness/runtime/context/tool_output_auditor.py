"""Runtime tool output token auditor and dynamic semantic truncation engine.

[INPUT]
- utils.text_utils::get_token_count, truncate_text_to_tokens (POS: Token estimation)

[OUTPUT]
- ToolAuditRecord: Per-call audit record tracking token and character savings
- ToolHungerStats: Aggregated per-tool consumption and overflow statistics
- ToolAuditorSummary: System-wide audit report with top-hungry tool rankings
- DynamicSemanticTruncationConfig: Configurable thresholds and line budgets
- DynamicSemanticTruncator: Structural extractor retaining error traces and head/tail
- ToolOutputTokenAuditor: Stateful runtime auditor and interceptor

[POS]
Harness runtime context layer. Intercepts tool outputs to eliminate token blowups,
saving up to 50%+ tokens while preserving diagnostic fidelity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final

from myrm_agent_harness.utils.text_utils import (
    get_token_count,
    truncate_text_to_tokens,
)

_DEFAULT_MAX_TOKENS_BUDGET: Final[int] = 2000
_DEFAULT_MAX_CHARS_BUDGET: Final[int] = 8000
_DEFAULT_HEAD_LINES: Final[int] = 20
_DEFAULT_TAIL_LINES: Final[int] = 25
_DEFAULT_MIDDLE_PATTERN_LINES: Final[int] = 30

_ERROR_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?i)(traceback|exception|error|failed|failure|panic|critical|fatal|syntaxerror|assertionerror|errno)",
)
_MATCH_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?i)(match(?:es)?|found \d+|result(?:s)?:\s*\d+|total \d+)",
)


@dataclass(slots=True, frozen=True)
class ToolAuditRecord:
    """Execution telemetry for a single tool call output."""

    call_id: str
    tool_name: str
    original_chars: int
    original_tokens: int
    truncated_chars: int
    truncated_tokens: int
    saved_tokens: int
    is_truncated: bool
    omitted_lines: int
    preserved_patterns: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ToolHungerStats:
    """Aggregated consumption metrics for a specific tool."""

    tool_name: str
    call_count: int = 0
    total_original_tokens: int = 0
    total_saved_tokens: int = 0
    truncation_count: int = 0

    @property
    def average_tokens_per_call(self) -> float:
        """Calculate average original tokens per call."""
        if self.call_count == 0:
            return 0.0
        return self.total_original_tokens / self.call_count

    @property
    def truncation_rate(self) -> float:
        """Calculate frequency of output truncation."""
        if self.call_count == 0:
            return 0.0
        return self.truncation_count / self.call_count

    @property
    def savings_ratio(self) -> float:
        """Calculate token reduction percentage achieved."""
        if self.total_original_tokens == 0:
            return 0.0
        return self.total_saved_tokens / self.total_original_tokens


@dataclass(slots=True, frozen=True)
class ToolAuditorSummary:
    """Comprehensive snapshot of token savings across all audited tools."""

    total_calls: int
    truncated_calls: int
    total_original_tokens: int
    total_saved_tokens: int
    overall_savings_ratio: float
    tool_stats: dict[str, ToolHungerStats]

    def top_hungry_tools(self, k: int = 5) -> list[tuple[str, int]]:
        """Return top-k tools by total original token volume."""
        sorted_tools = sorted(
            self.tool_stats.values(),
            key=lambda stat: stat.total_original_tokens,
            reverse=True,
        )
        return [(item.tool_name, item.total_original_tokens) for item in sorted_tools[:k]]


@dataclass(slots=True, frozen=True)
class DynamicSemanticTruncationConfig:
    """Parameters governing dynamic semantic truncation."""

    max_tokens_budget: int = _DEFAULT_MAX_TOKENS_BUDGET
    max_chars_budget: int = _DEFAULT_MAX_CHARS_BUDGET
    head_lines: int = _DEFAULT_HEAD_LINES
    tail_lines: int = _DEFAULT_TAIL_LINES
    max_middle_pattern_lines: int = _DEFAULT_MIDDLE_PATTERN_LINES


class DynamicSemanticTruncator:
    """Structural truncator preserving command heads, diagnostic tails, and error frames."""

    def __init__(
        self,
        config: DynamicSemanticTruncationConfig | None = None,
    ) -> None:
        self.config = config or DynamicSemanticTruncationConfig()

    def truncate(
        self,
        text: str,
    ) -> tuple[str, bool, int, list[str]]:
        """Perform semantic truncation if text exceeds configured budgets.

        Returns:
            Tuple of (processed_text, is_truncated, omitted_lines_count, preserved_patterns).
        """
        if not text:
            return "", False, 0, []

        orig_chars = len(text)
        orig_tokens = get_token_count(text)

        if (
            orig_tokens <= self.config.max_tokens_budget
            and orig_chars <= self.config.max_chars_budget
        ):
            return text, False, 0, []

        lines = text.splitlines(keepends=True)
        total_lines = len(lines)
        min_lines_needed = self.config.head_lines + self.config.tail_lines

        if total_lines <= min_lines_needed:
            # Low line count but massive lines (e.g. minified output or JSON blob)
            truncated_body = truncate_text_to_tokens(
                text,
                self.config.max_tokens_budget,
            )
            omitted = max(0, total_lines - 2)
            banner = (
                f"\n... [共 {total_lines} 行 / {orig_chars} 字符，因单行超限已执行 Token 边界紧缩截断] ...\n"
            )
            return f"{truncated_body}{banner}", True, omitted, ["token_boundary_fallback"]

        head_part = "".join(lines[: self.config.head_lines])
        tail_part = "".join(lines[-self.config.tail_lines :])
        middle_lines = lines[self.config.head_lines : -self.config.tail_lines]

        extracted_patterns: list[str] = []
        middle_selected: list[str] = []

        for line in middle_lines:
            if len(middle_selected) >= self.config.max_middle_pattern_lines:
                break
            if _ERROR_PATTERN.search(line):
                middle_selected.append(line)
                if "error_trace" not in extracted_patterns:
                    extracted_patterns.append("error_trace")
            elif _MATCH_PATTERN.search(line):
                middle_selected.append(line)
                if "keyword_match" not in extracted_patterns:
                    extracted_patterns.append("keyword_match")

        omitted_lines = max(0, len(middle_lines) - len(middle_selected))
        middle_content = "".join(middle_selected)
        middle_snippet = (
            f"\n... [保留中间关键行 {len(middle_selected)} 处] ...\n{middle_content}"
            if middle_selected
            else ""
        )

        banner = (
            f"\n... [共 {total_lines} 行 / {orig_chars} 字符，已动态语义折叠 {omitted_lines} 行无关键特征日志，"
            f"保留头部 {self.config.head_lines} 行、尾部 {self.config.tail_lines} 行及 {len(middle_selected)} 处关键诊断。可通过精细参数进一步查询] ...\n"
        )

        assembled = f"{head_part}{middle_snippet}{banner}{tail_part}"

        # Hard guard: if assembled still exceeds max_tokens_budget, enforce boundary
        assembled_tokens = get_token_count(assembled)
        if assembled_tokens > self.config.max_tokens_budget:
            assembled = truncate_text_to_tokens(assembled, self.config.max_tokens_budget)

        return assembled, True, omitted_lines, extracted_patterns


class ToolOutputTokenAuditor:
    """Runtime manager auditing tool output tokens and applying semantic truncation."""

    def __init__(
        self,
        config: DynamicSemanticTruncationConfig | None = None,
    ) -> None:
        self._truncator = DynamicSemanticTruncator(config)
        self._records: list[ToolAuditRecord] = []
        self._stats: dict[str, ToolHungerStats] = {}

    def audit_and_truncate(
        self,
        tool_name: str,
        output: str,
        call_id: str = "",
    ) -> tuple[str, ToolAuditRecord]:
        """Audit raw tool output, apply semantic truncation if needed, and record metrics."""
        orig_chars = len(output)
        orig_tokens = get_token_count(output)

        processed_text, is_truncated, omitted_lines, preserved_patterns = self._truncator.truncate(output)

        trunc_chars = len(processed_text)
        trunc_tokens = get_token_count(processed_text)
        saved_tokens = max(0, orig_tokens - trunc_tokens)

        record = ToolAuditRecord(
            call_id=call_id,
            tool_name=tool_name,
            original_chars=orig_chars,
            original_tokens=orig_tokens,
            truncated_chars=trunc_chars,
            truncated_tokens=trunc_tokens,
            saved_tokens=saved_tokens,
            is_truncated=is_truncated,
            omitted_lines=omitted_lines,
            preserved_patterns=preserved_patterns,
        )

        self._records.append(record)
        self._record_stats(record)

        return processed_text, record

    def _record_stats(self, record: ToolAuditRecord) -> None:
        """Update per-tool cumulative metrics."""
        stats = self._stats.get(record.tool_name)
        if stats is None:
            stats = ToolHungerStats(tool_name=record.tool_name)
            self._stats[record.tool_name] = stats

        stats.call_count += 1
        stats.total_original_tokens += record.original_tokens
        stats.total_saved_tokens += record.saved_tokens
        if record.is_truncated:
            stats.truncation_count += 1

    def get_summary(self) -> ToolAuditorSummary:
        """Compute aggregated audit summary across all recorded tool calls."""
        total_calls = len(self._records)
        truncated_calls = sum(1 for rec in self._records if rec.is_truncated)
        total_orig = sum(rec.original_tokens for rec in self._records)
        total_saved = sum(rec.saved_tokens for rec in self._records)
        overall_ratio = (total_saved / total_orig) if total_orig > 0 else 0.0

        return ToolAuditorSummary(
            total_calls=total_calls,
            truncated_calls=truncated_calls,
            total_original_tokens=total_orig,
            total_saved_tokens=total_saved,
            overall_savings_ratio=overall_ratio,
            tool_stats=dict(self._stats),
        )

    def reset(self) -> None:
        """Clear all historical records and statistics."""
        self._records.clear()
        self._stats.clear()
