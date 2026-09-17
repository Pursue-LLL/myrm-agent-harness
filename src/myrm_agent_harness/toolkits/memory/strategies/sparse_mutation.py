"""Sparse Semantic Mask Minimal Overwrite and Informed Retention Mutation Engine.

Provides deterministic, sub-millisecond slot extraction, sparse action masking
(RETAIN / OVERWRITE / APPEND / REMOVE), and minimal in-place reconstruction for
evolving compound memories without catastrophic context loss or blind appending.

[INPUT]
- .sparse_types::(SemanticSlot, SlotAction, SlotKind, SparseMaskItem, SparseMutationResult) (POS: Memory sparse mutation data contract layer)
- .sparse_parser::SemanticSlotParser (POS: Memory sparse mutation syntax parsing layer)
- existing_text: str (Structured compound text containing key-values, lists, or clauses)
- candidate_text: str (Patch or delta statement intended for memory evolution)

[OUTPUT]
- SlotAction: Action directive (RETAIN / OVERWRITE / APPEND / REMOVE)
- SlotKind: Structural classification of semantic slot
- SemanticSlot: Extracted structural slot with normalized key, indentation, and value
- SparseMaskItem: Individual slot mutation diff instruction
- SparseMutationResult: Complete mutation payload with in-place text and audit metrics
- SemanticSlotParser: Single-pass deterministic slot syntax parser
- SparseSemanticMaskGenerator: Global best similarity comparator and action mask generator
- MinimalOverwritePipeline: In-place text synthesizer preserving original layout
- apply_sparse_mutation: High-level zero-LLM deterministic entrypoint

[POS]
Memory sparse mutation and informed retention strategy layer. Pure Python standard library + Pydantic.
Zero network overhead (<0.5ms), zero LLM token cost, 100% deterministic layout preservation.
"""

from __future__ import annotations

import re
from typing import ClassVar

from .sparse_parser import SemanticSlotParser
from .sparse_types import (
    SemanticSlot,
    SlotAction,
    SlotKind,
    SparseMaskItem,
    SparseMutationResult,
)


class SparseSemanticMaskGenerator:
    """Compares slot sets and generates sparse diff action masks."""

    NATURAL_KINDS: ClassVar[tuple[SlotKind, ...]] = (
        SlotKind.CLAUSE,
        SlotKind.LIST_ITEM,
        SlotKind.PROSE_LINE,
    )

    @classmethod
    def _compute_natural_similarity(cls, ex_slot: SemanticSlot, cand: SemanticSlot) -> float:
        """Compute natural language similarity score between two non-KV slots."""
        if cand.is_negated or ex_slot.kind not in cls.NATURAL_KINDS or cand.kind not in cls.NATURAL_KINDS:
            return 0.0

        v1, v2 = ex_slot.value.lower(), cand.value.lower()
        k1, k2 = ex_slot.key, cand.key

        tokens1 = re.findall(r"[a-zA-Z0-9_]+|[\u4e00-\u9fa5]", v1)
        tokens2 = re.findall(r"[a-zA-Z0-9_]+|[\u4e00-\u9fa5]", v2)
        if not tokens1 or not tokens2:
            return 0.0

        # Subject identifier anchoring: if first token is a technical identifier and identical, match with high confidence
        if tokens1[0] == tokens2[0] and (len(tokens1[0]) >= 4 or "_" in tokens1[0]):
            return 0.9

        # Distinct technical identifier prefixes must never collide
        if ("_" in tokens1[0] or "_" in tokens2[0]) and tokens1[0] != tokens2[0]:
            return 0.0

        common_len = 0
        for c1, c2 in zip(k1, k2, strict=False):
            if c1 == c2:
                common_len += 1
            else:
                break
        min_len = min(len(k1), len(k2))
        prefix_ratio = (common_len / min_len) if min_len > 0 else 0.0

        set1, set2 = set(tokens1), set(tokens2)
        jaccard = len(set1 & set2) / max(len(set1 | set2), 1)

        if common_len >= 4 and prefix_ratio >= 0.4:
            return max(jaccard, prefix_ratio)
        if jaccard >= 0.5:
            return jaccard
        return 0.0

    @classmethod
    def generate_mask(
        cls,
        existing_slots: list[SemanticSlot],
        candidate_slots: list[SemanticSlot],
    ) -> list[SparseMaskItem]:
        """Generate diff action directives using two-stage global best matching."""
        mask_items: list[SparseMaskItem] = []
        matched_cand: dict[int, tuple[SemanticSlot, bool]] = {}
        used_candidates: set[int] = set()

        # Step 1: Exact key matches
        for ex_idx, ex_slot in enumerate(existing_slots):
            for c_idx, cand in enumerate(candidate_slots):
                if c_idx in used_candidates:
                    continue
                if cand.key == ex_slot.key:
                    matched_cand[ex_idx] = (cand, False)
                    used_candidates.add(c_idx)
                    break

        # Step 2: Negation / tombstone matches
        for ex_idx, ex_slot in enumerate(existing_slots):
            if ex_idx in matched_cand:
                continue
            ex_val_norm = SemanticSlotParser.normalize_key(ex_slot.value)
            for c_idx, cand in enumerate(candidate_slots):
                if c_idx in used_candidates or not cand.is_negated:
                    continue
                cand_subj = cand.key
                if cand_subj and (
                    cand_subj in ex_val_norm or cand_subj in ex_slot.key or ex_val_norm in cand_subj
                ):
                    matched_cand[ex_idx] = (cand, True)
                    used_candidates.add(c_idx)
                    break

        # Step 3: Global best similarity match for remaining non-KV slots
        pairs: list[tuple[float, int, int]] = []
        for ex_idx, ex_slot in enumerate(existing_slots):
            if ex_idx in matched_cand or ex_slot.kind not in (
                SlotKind.CLAUSE,
                SlotKind.LIST_ITEM,
                SlotKind.PROSE_LINE,
            ):
                continue
            for c_idx, cand in enumerate(candidate_slots):
                if c_idx in used_candidates or cand.is_negated:
                    continue
                score = cls._compute_natural_similarity(ex_slot, cand)
                if score > 0.0:
                    pairs.append((score, ex_idx, c_idx))

        pairs.sort(key=lambda x: x[0], reverse=True)
        for _score, ex_idx, c_idx in pairs:
            if ex_idx not in matched_cand and c_idx not in used_candidates:
                matched_cand[ex_idx] = (candidate_slots[c_idx], False)
                used_candidates.add(c_idx)

        # Step 4: Assemble mask items for existing slots
        for ex_idx, ex_slot in enumerate(existing_slots):
            match = matched_cand.get(ex_idx)
            if match is None:
                mask_items.append(
                    SparseMaskItem(
                        slot_key=ex_slot.key,
                        action=SlotAction.RETAIN,
                        old_value=ex_slot.value,
                        new_value=ex_slot.value,
                        raw_diff=f"  {ex_slot.raw_line}",
                    )
                )
            else:
                cand, is_tombstone = match
                if is_tombstone or cand.is_negated:
                    mask_items.append(
                        SparseMaskItem(
                            slot_key=ex_slot.key,
                            action=SlotAction.REMOVE,
                            old_value=ex_slot.value,
                            new_value=None,
                            raw_diff=f"- {ex_slot.raw_line}",
                        )
                    )
                elif ex_slot.value.strip().lower() != cand.value.strip().lower():
                    mask_items.append(
                        SparseMaskItem(
                            slot_key=ex_slot.key,
                            action=SlotAction.OVERWRITE,
                            old_value=ex_slot.value,
                            new_value=cand.value,
                            raw_diff=f"~ {ex_slot.value} -> {cand.value}",
                        )
                    )
                else:
                    mask_items.append(
                        SparseMaskItem(
                            slot_key=ex_slot.key,
                            action=SlotAction.RETAIN,
                            old_value=ex_slot.value,
                            new_value=ex_slot.value,
                            raw_diff=f"  {ex_slot.raw_line}",
                        )
                    )

        # Step 5: Append unmapped positive candidates
        for c_idx, cand in enumerate(candidate_slots):
            if c_idx not in used_candidates and not cand.is_negated:
                mask_items.append(
                    SparseMaskItem(
                        slot_key=cand.key,
                        action=SlotAction.APPEND,
                        old_value=None,
                        new_value=cand.value,
                        raw_diff=f"+ {cand.raw_line}",
                    )
                )

        return mask_items


def _extract_display_key(raw_text: str, sep: str, default_key: str) -> str:
    cleaned = raw_text.strip()
    for delimiter in (sep, ":", "："):
        if delimiter and delimiter in cleaned:
            return cleaned.split(delimiter)[0].strip()
    return default_key


class MinimalOverwritePipeline:
    """Executes sparse masks into reconstructed text and audit metadata."""

    @classmethod
    def apply(
        cls,
        existing_text: str,
        existing_slots: list[SemanticSlot],
        candidate_slots: list[SemanticSlot],
        mask_items: list[SparseMaskItem],
    ) -> SparseMutationResult:
        """Synthesize newly mutated text while preserving layout, hierarchy, and unaffected slots."""
        mask_by_key = {m.slot_key: m for m in mask_items}
        retained = sum(1 for m in mask_items if m.action == SlotAction.RETAIN)
        overwritten = sum(1 for m in mask_items if m.action == SlotAction.OVERWRITE)
        appended = sum(1 for m in mask_items if m.action == SlotAction.APPEND)
        removed = sum(1 for m in mask_items if m.action == SlotAction.REMOVE)

        if overwritten == 0 and appended == 0 and removed == 0:
            return SparseMutationResult(
                original_text=existing_text,
                mutated_text=existing_text,
                mask_items=mask_items,
                is_mutated=False,
                retained_count=retained,
                overwritten_count=0,
                appended_count=0,
                removed_count=0,
                summary="No changes detected; all slots retained.",
            )

        output_lines: list[str] = []
        appended_slots = [
            s
            for s in candidate_slots
            if mask_by_key.get(s.key) and mask_by_key[s.key].action == SlotAction.APPEND
        ]

        slots_by_line: dict[int, list[SemanticSlot]] = {}
        for s in existing_slots:
            slots_by_line.setdefault(s.line_index, []).append(s)

        for line_idx in sorted(slots_by_line.keys()):
            line_slots = slots_by_line[line_idx]
            if len(line_slots) == 1:
                ex_slot = line_slots[0]
                mask = mask_by_key.get(ex_slot.key)
                if mask is None or mask.action == SlotAction.RETAIN:
                    output_lines.append(ex_slot.raw_line)
                elif mask.action == SlotAction.OVERWRITE:
                    indent = " " * ex_slot.indent_level
                    bullet = ex_slot.bullet_prefix
                    if ex_slot.kind == SlotKind.KEY_VALUE:
                        sep = ex_slot.separator or ": "
                        raw_k = ex_slot.raw_line.lstrip(" ").removeprefix(bullet)
                        k_display = _extract_display_key(raw_k, sep, ex_slot.key)
                        output_lines.append(f"{indent}{bullet}{k_display}{sep}{mask.new_value}")
                    else:
                        output_lines.append(f"{indent}{bullet}{mask.new_value}")
                elif mask.action == SlotAction.REMOVE:
                    continue
            else:
                first_slot = line_slots[0]
                indent = " " * first_slot.indent_level
                bullet = first_slot.bullet_prefix
                delim = first_slot.clause_delimiter or "; "

                line_parts: list[str] = []
                for s in line_slots:
                    mask = mask_by_key.get(s.key)
                    if mask is None or mask.action == SlotAction.RETAIN:
                        line_parts.append(s.raw_line)
                    elif mask.action == SlotAction.OVERWRITE:
                        if s.separator:
                            sep = s.separator or ": "
                            k_display = _extract_display_key(s.raw_line, sep, s.key)
                            line_parts.append(f"{k_display}{sep}{mask.new_value}")
                        else:
                            line_parts.append(mask.new_value or "")
                    elif mask.action == SlotAction.REMOVE:
                        continue

                if line_parts:
                    output_lines.append(f"{indent}{bullet}" + delim.join(line_parts))

        default_indent = existing_slots[0].indent_level if existing_slots else 0
        default_bullet = existing_slots[0].bullet_prefix if existing_slots else "- "
        for app_slot in appended_slots:
            if app_slot.raw_line:
                output_lines.append(app_slot.raw_line)
            else:
                indent = " " * default_indent
                output_lines.append(f"{indent}{default_bullet}{app_slot.key}: {app_slot.value}")

        mutated_text = "\n".join(output_lines)
        summary = (
            f"Sparse mutation: {retained} retained, {overwritten} overwritten, "
            f"{appended} appended, {removed} removed."
        )

        return SparseMutationResult(
            original_text=existing_text,
            mutated_text=mutated_text,
            mask_items=mask_items,
            is_mutated=True,
            retained_count=retained,
            overwritten_count=overwritten,
            appended_count=appended,
            removed_count=removed,
            summary=summary,
        )


def apply_sparse_mutation(existing_text: str, candidate_text: str) -> SparseMutationResult:
    """High-level zero-LLM deterministic entrypoint for sparse memory mutation."""
    ex_slots = SemanticSlotParser.parse(existing_text)
    cand_slots = SemanticSlotParser.parse(candidate_text)

    if not SemanticSlotParser.is_structured(ex_slots) and not SemanticSlotParser.is_structured(
        cand_slots
    ):
        return SparseMutationResult(
            original_text=existing_text,
            mutated_text=existing_text,
            mask_items=[],
            is_mutated=False,
            retained_count=0,
            overwritten_count=0,
            appended_count=0,
            removed_count=0,
            summary="Unstructured atomic prose line; sparse mutation skipped.",
        )

    if not ex_slots:
        cand_mask = [
            SparseMaskItem(
                slot_key=s.key,
                action=SlotAction.APPEND,
                old_value=None,
                new_value=s.value,
                raw_diff=f"+ {s.raw_line}",
            )
            for s in cand_slots
        ]
        return SparseMutationResult(
            original_text=existing_text,
            mutated_text=candidate_text,
            mask_items=cand_mask,
            is_mutated=True,
            retained_count=0,
            overwritten_count=0,
            appended_count=len(cand_slots),
            removed_count=0,
            summary=f"Initialized {len(cand_slots)} slots from candidate.",
        )

    masks = SparseSemanticMaskGenerator.generate_mask(ex_slots, cand_slots)
    return MinimalOverwritePipeline.apply(existing_text, ex_slots, cand_slots, masks)


__all__ = [
    "MinimalOverwritePipeline",
    "SemanticSlot",
    "SemanticSlotParser",
    "SlotAction",
    "SlotKind",
    "SparseMaskItem",
    "SparseMutationResult",
    "SparseSemanticMaskGenerator",
    "apply_sparse_mutation",
]
