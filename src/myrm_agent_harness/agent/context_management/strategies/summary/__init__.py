"""Summarization strategy: structured summarize, audit, build, parse, prompts."""

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
