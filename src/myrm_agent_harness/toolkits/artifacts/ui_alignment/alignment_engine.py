"""[INPUT]
- models: UiVariant, UiVariantStyle, VisualAnnotation, VisualContract

[OUTPUT]
- UiDesignVisualAlignmentEngine: Core engine managing variant comparison, canvas annotations, and contract compilation

[POS]
Harness framework layer engine for Multi-Turn UI Design Visual Alignment (Item 39 P0).
Strictly under 200 lines. Zero `Any`.
"""

from __future__ import annotations

import threading
import time
import uuid

from .models import (
    UiVariant,
    VisualAnnotation,
    VisualContract,
)


class UiDesignVisualAlignmentEngine:
    """Thread-safe engine governing UI design variant comparison and visual contract compilation."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._variants: dict[str, list[UiVariant]] = {}
        self._annotations: dict[str, list[VisualAnnotation]] = {}
        self._contracts: dict[str, VisualContract] = {}

    def register_variant(self, session_id: str, variant: UiVariant) -> UiVariant:
        """Registers a UI visual mockup variant for a given session."""
        with self._lock:
            variants = self._variants.setdefault(session_id, [])
            # Update if already exists, else append
            existing_idx = next(
                (i for i, v in enumerate(variants) if v.variant_id == variant.variant_id),
                None,
            )
            if existing_idx is not None:
                variants[existing_idx] = variant
            else:
                variants.append(variant)
            return variant

    def get_variants(self, session_id: str) -> list[UiVariant]:
        """Returns all registered UI variants for the session."""
        with self._lock:
            return list(self._variants.get(session_id, []))

    def get_variant(self, session_id: str, variant_id: str) -> UiVariant | None:
        """Finds a specific variant by ID."""
        with self._lock:
            for v in self._variants.get(session_id, []):
                if v.variant_id == variant_id:
                    return v
            return None

    def add_annotation(self, variant_id: str, annotation: VisualAnnotation) -> VisualAnnotation:
        """Attaches a visual bounding box annotation and comment to a design variant."""
        with self._lock:
            notes = self._annotations.setdefault(variant_id, [])
            notes.append(annotation)
            return annotation

    def get_annotations(self, variant_id: str) -> list[VisualAnnotation]:
        """Returns all canvas visual annotations on the given design variant."""
        with self._lock:
            return list(self._annotations.get(variant_id, []))

    def compile_visual_contract(
        self,
        session_id: str,
        approved_variant_id: str,
    ) -> VisualContract:
        """Compiles the approved design variant and canvas annotations into an immutable VisualContract."""
        variant = self.get_variant(session_id, approved_variant_id)
        if variant is None:
            raise ValueError(
                f"Variant '{approved_variant_id}' not found for session '{session_id}'"
            )

        annotations = self.get_annotations(approved_variant_id)

        # Build enforcement prompt for downstream coding agent
        prompt_lines: list[str] = [
            "### [VISUAL DESIGN CONTRACT ENFORCEMENT]",
            f"Approved Variant: {variant.title} (ID: {variant.variant_id})",
            f"Visual Style Theme: {variant.style_theme}",
            f"Description: {variant.description}",
            "",
            "#### Design Tokens & Palette:",
        ]

        for token_key, token_val in variant.css_tokens.items():
            prompt_lines.append(f"- {token_key}: {token_val}")

        if annotations:
            prompt_lines.append("")
            prompt_lines.append(f"#### Canvas Visual Feedback Annotations ({len(annotations)} notes):")
            for idx, note in enumerate(annotations, 1):
                prompt_lines.append(
                    f"{idx}. [{note.label}] Region (x: {note.x:.1f}%, y: {note.y:.1f}%, w: {note.width:.1f}%, h: {note.height:.1f}%): \"{note.comment}\""
                )

        prompt_lines.append("")
        prompt_lines.append("#### Structural DOM Skeleton Reference:")
        prompt_lines.append("```html")
        prompt_lines.append(variant.html_content)
        prompt_lines.append("```")
        prompt_lines.append("")
        prompt_lines.append(
            "CRITICAL INSTRUCTION: Implement production components strictly conforming to this approved visual contract. "
            "Preserve layout hierarchy, color tokens, and incorporate all visual canvas annotations. Visual fidelity target: >= 95%."
        )

        enforcement_prompt = "\n".join(prompt_lines)

        contract = VisualContract(
            contract_id=f"vc_{uuid.uuid4().hex[:10]}",
            session_id=session_id,
            approved_variant_id=approved_variant_id,
            style_theme=variant.style_theme,
            dom_outline=variant.html_content[:300],
            design_tokens=dict(variant.css_tokens),
            annotations=annotations,
            enforcement_prompt=enforcement_prompt,
            finalized_at_ms=time.time() * 1000.0,
        )

        with self._lock:
            self._contracts[session_id] = contract

        return contract

    def get_latest_contract(self, session_id: str) -> VisualContract | None:
        """Returns the latest compiled visual contract for the session, if finalized."""
        with self._lock:
            return self._contracts.get(session_id)
