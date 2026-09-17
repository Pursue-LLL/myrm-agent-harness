"""Deterministic single-pass parser for structured semantic slots.

[INPUT]
- .sparse_types::SemanticSlot (POS: Memory sparse mutation data contract layer)
- .sparse_types::SlotKind (POS: Memory sparse mutation data contract layer)

[OUTPUT]
- SemanticSlotParser: Single-pass deterministic slot syntax parser

[POS]
Memory sparse mutation syntax parsing layer. Scans markdown, key-value pairs, and clauses into slots.
"""

from __future__ import annotations

import re
from typing import ClassVar

from .sparse_types import SemanticSlot, SlotKind


class SemanticSlotParser:
    """Zero-LLM deterministic single-pass stateful parser for semantic slots."""

    NEGATION_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"(?:不再使用|不要使用|禁用|弃用|移除|删除|no\s+longer|remove|delete|deprecate)",
        re.IGNORECASE,
    )
    LIST_PREFIX_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"^(\s*)([-*+]|\d+\.)\s+(.*)$"
    )
    KV_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"^([^:：\n]+)([:：])\s*(.*)$"
    )

    @classmethod
    def normalize_key(cls, raw_key: str) -> str:
        """Normalize a slot key for invariant structural matching."""
        cleaned = cls.NEGATION_PATTERN.sub("", raw_key)
        cleaned = re.sub(r"[\s\W_]+", "", cleaned.lower())
        return cleaned or raw_key.strip().lower()

    @classmethod
    def parse(cls, text: str) -> list[SemanticSlot]:
        """Parse structured Markdown, lists, or clauses into semantic slots."""
        if not text or not text.strip():
            return []

        slots: list[SemanticSlot] = []
        raw_lines = text.splitlines()

        for idx, raw_line in enumerate(raw_lines):
            stripped = raw_line.strip()
            if not stripped:
                continue

            indent_len = len(raw_line) - len(raw_line.lstrip(" "))
            bullet = ""
            payload = stripped

            bullet_match = cls.LIST_PREFIX_PATTERN.match(raw_line)
            if bullet_match:
                indent_len = len(bullet_match.group(1))
                bullet = bullet_match.group(2) + " "
                payload = bullet_match.group(3).strip()

            is_negated = bool(cls.NEGATION_PATTERN.search(payload))

            clause_delim = "; " if "; " in payload else ("；" if "；" in payload else "")
            if clause_delim:
                raw_clauses = [c.strip() for c in payload.split(clause_delim) if c.strip()]
                for clause in raw_clauses:
                    c_neg = bool(cls.NEGATION_PATTERN.search(clause))
                    c_kv = cls.KV_PATTERN.match(clause)
                    if c_kv:
                        c_k = c_kv.group(1).strip()
                        c_sep = f"{c_kv.group(2)} "
                        c_val = c_kv.group(3).strip()
                        slots.append(
                            SemanticSlot(
                                key=cls.normalize_key(c_k),
                                value=c_val,
                                raw_line=clause,
                                indent_level=indent_len,
                                bullet_prefix=bullet,
                                separator=c_sep,
                                kind=SlotKind.CLAUSE,
                                line_index=idx,
                                is_negated=c_neg,
                                clause_delimiter=clause_delim,
                            )
                        )
                    else:
                        slots.append(
                            SemanticSlot(
                                key=cls.normalize_key(clause),
                                value=clause,
                                raw_line=clause,
                                indent_level=indent_len,
                                bullet_prefix=bullet,
                                separator="",
                                kind=SlotKind.CLAUSE,
                                line_index=idx,
                                is_negated=c_neg,
                                clause_delimiter=clause_delim,
                            )
                        )
            else:
                kv_match = cls.KV_PATTERN.match(payload)
                if kv_match:
                    raw_k = kv_match.group(1).strip()
                    sep = f"{kv_match.group(2)} "
                    val = kv_match.group(3).strip()
                    slots.append(
                        SemanticSlot(
                            key=cls.normalize_key(raw_k),
                            value=val,
                            raw_line=raw_line,
                            indent_level=indent_len,
                            bullet_prefix=bullet,
                            separator=sep,
                            kind=SlotKind.KEY_VALUE,
                            line_index=idx,
                            is_negated=is_negated,
                        )
                    )
                else:
                    slots.append(
                        SemanticSlot(
                            key=cls.normalize_key(payload),
                            value=payload,
                            raw_line=raw_line,
                            indent_level=indent_len,
                            bullet_prefix=bullet,
                            separator="",
                            kind=SlotKind.LIST_ITEM if bullet else SlotKind.PROSE_LINE,
                            line_index=idx,
                            is_negated=is_negated,
                        )
                    )

        return slots

    @classmethod
    def is_structured(cls, slots: list[SemanticSlot]) -> bool:
        """Check if slots form a compound structured set (KV, bullet lists, clauses)."""
        if not slots:
            return False
        has_explicit_kv = any(s.kind == SlotKind.KEY_VALUE for s in slots)
        has_bullet_or_clause = any(s.kind in (SlotKind.LIST_ITEM, SlotKind.CLAUSE) for s in slots)
        return has_explicit_kv or (has_bullet_or_clause and len(slots) >= 1) or len(slots) > 1


__all__ = ["SemanticSlotParser"]
