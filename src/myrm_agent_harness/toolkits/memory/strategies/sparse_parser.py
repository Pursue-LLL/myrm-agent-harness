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

    TOMBSTONE_DIRECTIVE_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"^(?:"
        r"(?:不再使用|不要使用|禁用|弃用|废弃|移除|删除)\s*"
        r"|"
        r"(?:no\s+longer|deprecate(?:d)?|disable(?:d)?|obsolete|delete|remove)\b\s*"
        r")",
        re.IGNORECASE,
    )
    TOMBSTONE_VALUE_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"^(?:deprecated|disabled|obsolete|false|none|null|已废弃|已禁用|禁用|移除|删除)$",
        re.IGNORECASE,
    )
    LIST_PREFIX_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"^(\s*)([-*+]|\d+\.)\s+(.*)$"
    )
    KV_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"^([^\n]{1,120}?)(:\s+|：\s*)(.*)$"
    )
    CLAUSE_SPLIT_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"(?:;\s*|；\s*)")

    @classmethod
    def is_tombstone(cls, raw_key: str, val: str = "") -> bool:
        """Check if slot represents an explicit tombstone deletion directive."""
        if cls.TOMBSTONE_DIRECTIVE_PATTERN.match(raw_key.strip()):
            return True
        return bool(val and cls.TOMBSTONE_VALUE_PATTERN.match(val.strip()))

    @classmethod
    def normalize_key(cls, raw_key: str) -> str:
        """Normalize a slot key for invariant structural matching."""
        cleaned = cls.TOMBSTONE_DIRECTIVE_PATTERN.sub("", raw_key.strip())
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

            if ";" in payload or "；" in payload:
                raw_clauses = [c.strip() for c in cls.CLAUSE_SPLIT_PATTERN.split(payload) if c.strip()]
            else:
                raw_clauses = []

            if len(raw_clauses) > 1:
                delim = "；" if "；" in payload else "; "
                for clause in raw_clauses:
                    c_kv = cls.KV_PATTERN.match(clause)
                    if c_kv:
                        c_k = c_kv.group(1).strip()
                        c_sep = f"{c_kv.group(2).strip()} "
                        c_val = c_kv.group(3).strip()
                        c_neg = cls.is_tombstone(c_k, c_val)
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
                                clause_delimiter=delim,
                            )
                        )
                    else:
                        c_neg = cls.is_tombstone(clause)
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
                                clause_delimiter=delim,
                            )
                        )
            else:
                kv_match = cls.KV_PATTERN.match(payload)
                if kv_match:
                    raw_k = kv_match.group(1).strip()
                    sep = f"{kv_match.group(2).strip()} "
                    val = kv_match.group(3).strip()
                    is_negated = cls.is_tombstone(raw_k, val)
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
                    is_negated = cls.is_tombstone(payload)
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
