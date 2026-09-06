"""Reasoning Anchor Extractor.

Extracts core decision anchors, constraints, and verified conclusions from
heterogeneous LLM reasoning streams (Anthropic thinking blocks, DeepSeek/MiMo
reasoning_content, OpenAI responses reasoning items, and inline think tags).

[INPUT]
- langchain_core.messages::AIMessage (POS: LangChain assistant message)

[OUTPUT]
- ReasoningAnchor: Data model for a preserved reasoning anchor
- extract_raw_reasoning: Normalizes multi-provider thinking outputs to raw text
- extract_reasoning_anchors: Extracts high-fidelity decision anchors from raw reasoning

[POS]
Pure in-memory, deterministic extraction pipeline with zero secondary LLM calls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping, Sequence

from langchain_core.messages import AIMessage

# Explicit decision signal prefixes (case-insensitive normalized)
_DECISION_PREFIX_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^(?:(?:核心)?结论|决策|确定方案|决定|最终结论)[:：]\s*(.+)$", re.IGNORECASE), "decision"),
    (re.compile(r"^(?:CONCLUSION|DECISION|STRATEGY)[:：]\s*(.+)$", re.IGNORECASE), "decision"),
    (re.compile(r"^(?:硬性约束|架构约束|铁律|原则|禁止)[:：]\s*(.+)$", re.IGNORECASE), "constraint"),
    (re.compile(r"^(?:CONSTRAINT|RULE|INVARIANT)[:：]\s*(.+)$", re.IGNORECASE), "constraint"),
    (re.compile(r"^(?:已验证|根因定位|排查结果|关键发现|证实)[:：]\s*(.+)$", re.IGNORECASE), "finding"),
    (re.compile(r"^(?:VERIFIED|ROOT CAUSE|FINDING|DISCOVERY)[:：]\s*(.+)$", re.IGNORECASE), "finding"),
)

_INLINE_THINK_REGEX = re.compile(r"<think>(.*?)</think>", re.DOTALL | re.IGNORECASE)
_MAX_ANCHOR_CHARS = 240
_MAX_TAIL_SCAN_CHARS = 4000


@dataclass(frozen=True)
class ReasoningAnchor:
    """Immutable reasoning decision anchor."""

    anchor_id: str
    turn_index: int
    category: str
    content: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_compact_string(self) -> str:
        """Render anchor into a compact context-friendly format."""
        category_tag = self.category.upper()
        return f"[Anchor #{self.turn_index} ({category_tag})]: {self.content}"


def extract_raw_reasoning(msg: AIMessage) -> str | None:
    """Extract raw thinking/reasoning text from multi-provider assistant message.

    Handles:
    1. content blocks: [{"type": "thinking", "thinking": "..."}] (Anthropic)
    2. additional_kwargs["reasoning_content"] (DeepSeek, MiMo, Kimi)
    3. additional_kwargs["thinking_blocks"]
    4. additional_kwargs["responses_reasoning_items"] (OpenAI Responses API)
    5. string content containing <think>...</think> inline tags
    """
    # 1. Anthropic content block list
    content = msg.content
    if isinstance(content, list):
        collected_blocks: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") in ("thinking", "redacted_thinking"):
                text = block.get("thinking")
                if isinstance(text, str) and text.strip():
                    collected_blocks.append(text.strip())
        if collected_blocks:
            return "\n".join(collected_blocks)

    # 2. String content inline <think> tags
    if isinstance(content, str) and "<think>" in content.lower():
        match = _INLINE_THINK_REGEX.search(content)
        if match:
            extracted = match.group(1).strip()
            if extracted:
                return extracted

    # 3. additional_kwargs providers
    kwargs = msg.additional_kwargs
    if kwargs and isinstance(kwargs, dict):
        rc = kwargs.get("reasoning_content")
        if isinstance(rc, str) and rc.strip():
            return rc.strip()

        tb = kwargs.get("thinking_blocks")
        if isinstance(tb, list):
            items: list[str] = []
            for item in tb:
                if isinstance(item, str) and item.strip():
                    items.append(item.strip())
                elif isinstance(item, dict) and "thinking" in item and isinstance(item["thinking"], str):
                    items.append(item["thinking"].strip())
            if items:
                return "\n".join(items)

        resp_items = kwargs.get("responses_reasoning_items")
        if isinstance(resp_items, list):
            resp_texts: list[str] = [
                str(it.get("summary", it.get("text", ""))).strip()
                for it in resp_items
                if isinstance(it, dict) and (it.get("summary") or it.get("text"))
            ]
            if resp_texts:
                return "\n".join(resp_texts)

    return None


def extract_reasoning_anchors(
    reasoning_text: str | None,
    *,
    turn_index: int = 0,
    max_anchors: int = 2,
) -> list[ReasoningAnchor]:
    """Extract up to max_anchors decision anchors from reasoning text.

    Scans reasoning tail deterministically. Prioritizes lines matching explicit
    decision/constraint/finding prefixes. If none match, extracts final conclusive
    sentences from the tail summary.
    """
    if not reasoning_text or not reasoning_text.strip():
        return []

    # Bounded tail scanning to prevent large string overhead
    bounded_text = reasoning_text[-_MAX_TAIL_SCAN_CHARS:] if len(reasoning_text) > _MAX_TAIL_SCAN_CHARS else reasoning_text
    lines = [line.strip() for line in bounded_text.splitlines() if line.strip()]
    if not lines:
        return []

    anchors: list[ReasoningAnchor] = []
    seen_contents: set[str] = set()

    # Pass 1: Explicit pattern matching on lines (reverse order to get latest conclusions)
    for line in reversed(lines):
        if len(anchors) >= max_anchors:
            break
        # Strip list markers like "- ", "* ", "1. "
        clean_line = re.sub(r"^(?:[-*•]|\d+\.)\s*", "", line).strip()
        for pattern, category in _DECISION_PREFIX_PATTERNS:
            match = pattern.match(clean_line)
            if match:
                raw_extracted = match.group(1).strip()
                extracted = raw_extracted[:_MAX_ANCHOR_CHARS].strip()
                if extracted and extracted not in seen_contents:
                    seen_contents.add(extracted)
                    anchor_id = f"anc_{turn_index}_{len(anchors)}"
                    anchors.append(
                        ReasoningAnchor(
                            anchor_id=anchor_id,
                            turn_index=turn_index,
                            category=category,
                            content=extracted,
                        )
                    )
                break

    # Pass 2: Fallback to conclusive tail sentences if no explicit prefix matched
    if not anchors:
        last_chunk = lines[-1]
        # Sentence splitting by punctuation
        sentences = [s.strip() for s in re.split(r"[。！？\n.!?]+", last_chunk) if len(s.strip()) >= 8]
        if sentences:
            chosen = sentences[-1][:_MAX_ANCHOR_CHARS]
            anchor_id = f"anc_{turn_index}_0"
            anchors.append(
                ReasoningAnchor(
                    anchor_id=anchor_id,
                    turn_index=turn_index,
                    category="finding",
                    content=chosen,
                )
            )

    anchors.reverse()
    return anchors
