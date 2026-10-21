"""[INPUT]
- ReferenceTarget: Data structure representing an omni reference target
- ContextSlice: Extracted lightweight context slice model

[OUTPUT]
- ReferenceDimension: Literal of 5-dimensional targets ('file' | 'session' | 'artifact' | 'agent' | 'task')
- OmniReferenceExtractor: Pure class extracting lightweight slices without blowing context budget
- format_omni_context_slices: Prompt injection formatter with provenance provenance headers

[POS]
Harness framework layer omni-context reference and slice expansion engine.
Guarantees clean boundary, pure-python semantics, and context inflation protection.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

ReferenceDimension = Literal["file", "session", "artifact", "agent", "task"]

# Standard prefix matcher for 5 dimensions
REFERENCE_REGEX = re.compile(r"@(file|session|artifact|agent|task):([^\s@]+)")


@dataclass(slots=True)
class ReferenceTarget:
    dimension: ReferenceDimension
    target_id: str
    label: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ContextSlice:
    dimension: ReferenceDimension
    target_id: str
    label: str
    content_slice: str
    is_truncated: bool
    token_estimate: int
    provenance_uri: str


class OmniReferenceExtractor:
    """Extracts bounded context slices from 5-dimensional omni references."""

    MAX_SLICE_CHARS_PER_ITEM = 2000

    @classmethod
    def parse_references_from_text(cls, text: str) -> list[ReferenceTarget]:
        """Parse all @dim:target instances in user input text."""
        matches = REFERENCE_REGEX.findall(text)
        results: list[ReferenceTarget] = []
        seen: set[str] = set()

        for dim, raw_target in matches:
            target = raw_target.rstrip(".,;:!?)'\"")
            if not target:
                continue
            key = f"{dim}:{target}"
            if key in seen:
                continue
            seen.add(key)
            results.append(
                ReferenceTarget(
                    dimension=dim,  # type: ignore[arg-type]
                    target_id=target,
                    label=target,
                )
            )
        return results

    @classmethod
    def create_slice(
        cls,
        target: ReferenceTarget,
        raw_content: str,
        custom_provenance_uri: str | None = None,
    ) -> ContextSlice:
        """Create a bounded slice preventing context explosion."""
        clean_text = raw_content.strip()
        is_truncated = False

        if len(clean_text) > cls.MAX_SLICE_CHARS_PER_ITEM:
            clean_text = clean_text[: cls.MAX_SLICE_CHARS_PER_ITEM].rstrip() + "\n...[truncated for context efficiency]"
            is_truncated = True

        # Simple 4 chars ~ 1 token heuristic
        tokens = max(1, len(clean_text) // 4)
        provenance = custom_provenance_uri or f"myrm://{target.dimension}/{target.target_id}"

        return ContextSlice(
            dimension=target.dimension,
            target_id=target.target_id,
            label=target.label,
            content_slice=clean_text,
            is_truncated=is_truncated,
            token_estimate=tokens,
            provenance_uri=provenance,
        )


def format_omni_context_slices(slices: list[ContextSlice]) -> str:
    """Format extracted context slices into clean, immutable prompt context blocks."""
    if not slices:
        return ""

    lines: list[str] = [
        "<!-- OMNI_CONTEXT_REFERENCE_BLOCK: START -->",
        "<referenced_context_slices>",
    ]

    for s in slices:
        trunc_attr = ' truncated="true"' if s.is_truncated else ""
        lines.append(
            f'  <slice dimension="{s.dimension}" target_id="{s.target_id}" label="{s.label}" provenance="{s.provenance_uri}"{trunc_attr}>'
        )
        lines.append(f"    {s.content_slice}")
        lines.append("  </slice>")

    lines.append("</referenced_context_slices>")
    lines.append("<!-- OMNI_CONTEXT_REFERENCE_BLOCK: END -->")

    return "\n".join(lines)
