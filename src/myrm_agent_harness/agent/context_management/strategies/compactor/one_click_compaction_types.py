"""Data contracts and schemas for one-click context compaction and HUD economy.

[INPUT]
- dataclasses::dataclass, field (POS: Python 数据类标准库)
- langchain_core.messages::BaseMessage (POS: LangChain 消息基础类型)

[OUTPUT]
- OneClickCompactionConfig: 一键会话瘦身策略配置
- OneClickCompactionResult: 一键瘦身执行诊断与 HUD 徽标数据契约
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class OneClickCompactionConfig:
    """Configuration for one-click context compaction."""

    keep_recent_rounds: int = 2
    min_content_length_to_purify: int = 120
    model_name: str = "default"
    estimate_char_to_token_ratio: float = 4.0


@dataclass(frozen=True, slots=True)
class OneClickCompactionResult:
    """Diagnostic outcome and HUD economy metrics of one-click compaction."""

    session_id: str
    original_messages_count: int
    compacted_messages_count: int
    raw_tokens: int
    compacted_tokens: int
    released_tokens: int
    compression_ratio: float
    estimated_cost_saved_usd: float
    feedback_badge: str
    purified_tool_count: int
    details: dict[str, object] = field(default_factory=dict)
