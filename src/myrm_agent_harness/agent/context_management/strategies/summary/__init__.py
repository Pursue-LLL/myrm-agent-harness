"""Summarization strategy: structured summarize, audit, build, parse, prompts.

[INPUT]
- chat_history / focus topic: 待总结对话与关注主题

[OUTPUT]
- generate_structured_summary(): 结构化摘要生成
- should_summarize(): 是否触发摘要
- extract_protected_head(): 受保护头部提取
- FOCUS_TOPIC_SUFFIX / UNVERIFIED_CONTEXT_MARKER: 提示词与标记常量

[POS]
Context summarization strategy — generates structured summaries with audit trail,
preserving protected head context and marking unverified content.
"""

from .summarize_circuit_guard import is_summarize_circuit_open
from .summarizer import generate_structured_summary, should_summarize
from .summary_builder import (
    UNVERIFIED_CONTEXT_MARKER,
    extract_protected_head,
)
from .summary_prompts import (
    FOCUS_TOPIC_SUFFIX,
    SUMMARY_MERGE_PROMPT_TEMPLATE,
    SUMMARY_PROMPT_TEMPLATE,
)

__all__ = [
    "FOCUS_TOPIC_SUFFIX",
    "SUMMARY_MERGE_PROMPT_TEMPLATE",
    "SUMMARY_PROMPT_TEMPLATE",
    "UNVERIFIED_CONTEXT_MARKER",
    "extract_protected_head",
    "generate_structured_summary",
    "is_summarize_circuit_open",
    "should_summarize",
]
