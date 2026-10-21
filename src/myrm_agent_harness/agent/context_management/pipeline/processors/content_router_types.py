"""Data types and schemas for adaptive tool result content routing and auto-compaction.

[INPUT]
- dataclasses::dataclass, field (POS: Python 数据类标准库)
- enum::Enum (POS: Python 枚举标准库)

[OUTPUT]
- ToolResultFormatKind: 内容格式枚举 (JSON, TABULAR, DIFF, LOGS, GREP, PLAIN)
- AdaptiveCompactorConfig: 自适应压缩守卫与阈值配置
- AdaptiveCompactionResult: 压缩与路由诊断结果
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ToolResultFormatKind(StrEnum):
    """Detected content format kind for tool execution results."""

    JSON_ARRAY = "json_array"
    TABULAR = "tabular"
    UNIFIED_DIFF = "unified_diff"
    REPEATED_LOGS = "repeated_logs"
    GREP_MATCHES = "grep_matches"
    PLAIN_TEXT = "plain_text"


@dataclass(frozen=True, slots=True)
class AdaptiveCompactorConfig:
    """Defensive thresholds and toggles for multi-format content compaction."""

    min_savings_chars: int = 25
    strip_diff_metadata: bool = True
    min_log_repeat_count: int = 2
    enable_grep_path_grouping: bool = True
    min_grep_lines_to_group: int = 3


@dataclass(frozen=True, slots=True)
class AdaptiveCompactionResult:
    """Outcome and diagnostics of adaptive content routing and compaction."""

    format_kind: ToolResultFormatKind
    is_compacted: bool
    original_text: str
    compacted_text: str
    original_chars: int = 0
    compacted_chars: int = 0
    saved_chars: int = 0
    compression_ratio: float = 0.0
    bypass_reason: str | None = None
    details: dict[str, object] = field(default_factory=dict)
