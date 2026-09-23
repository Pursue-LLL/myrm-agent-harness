"""Structured source identity card frontmatter and validation contract.

[INPUT]
- utils.markdown_frontmatter (POS: parse_frontmatter)

[OUTPUT]
- SourceCardContract, SourceProvenanceClass, SourceRiskLevel
- parse_source_card, serialize_source_card, validate_source_card

[POS]
Defines identity cards for Layer 2 (sources/) to ensure every piece of evidence has
traceable authorship, platform, capturing timestamp, and risk evaluation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Literal

from myrm_agent_harness.utils.markdown_frontmatter import parse_frontmatter

SourceProvenanceClass = Literal[
    "official_doc",
    "author_claim",
    "untrusted",
    "agent_synthesis",
]

SourceRiskLevel = Literal["low", "medium", "high"]

VALID_PROVENANCE_CLASSES: frozenset[str] = frozenset({
    "official_doc",
    "author_claim",
    "untrusted",
    "agent_synthesis",
})

VALID_RISK_LEVELS: frozenset[str] = frozenset({"low", "medium", "high"})


@dataclass(frozen=True, slots=True)
class SourceCardContract:
    """Identity card contract for an ingested source document (sources/*.md)."""

    source_id: str
    title: str
    author: str
    platform: str
    url_or_path: str
    captured_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )
    provenance_class: SourceProvenanceClass = "author_claim"
    risk_level: SourceRiskLevel = "medium"
    covered_concepts: list[str] = field(default_factory=list)
    verification_notes: str = ""

    def to_frontmatter_dict(self) -> dict[str, object]:
        """Convert to dict for YAML frontmatter serialization."""
        data = asdict(self)
        data["type"] = "source"
        return data


def parse_source_card(content: str, default_source_id: str = "") -> SourceCardContract:
    """Parse a markdown content string containing source card frontmatter."""
    metadata, body = parse_frontmatter(content)
    source_id = str(metadata.get("source_id") or default_source_id or "src_unknown").strip()
    title = str(metadata.get("title") or source_id).strip()
    author = str(metadata.get("author") or "Unknown").strip()
    platform = str(metadata.get("platform") or "web").strip()
    url_or_path = str(metadata.get("url_or_path") or metadata.get("url") or "").strip()
    captured_at = str(
        metadata.get("captured_at") or datetime.now(UTC).isoformat(timespec="seconds")
    ).strip()

    raw_prov = str(metadata.get("provenance_class") or "author_claim").strip()
    provenance_class: SourceProvenanceClass = (
        raw_prov if raw_prov in VALID_PROVENANCE_CLASSES else "author_claim"
    )

    raw_risk = str(metadata.get("risk_level") or "medium").strip()
    risk_level: SourceRiskLevel = raw_risk if raw_risk in VALID_RISK_LEVELS else "medium"

    raw_concepts = metadata.get("covered_concepts") or []
    if isinstance(raw_concepts, list):
        covered_concepts = [str(c).strip() for c in raw_concepts if str(c).strip()]
    else:
        covered_concepts = [str(raw_concepts).strip()] if str(raw_concepts).strip() else []

    meta_notes = str(metadata.get("verification_notes") or "").strip()
    body_notes = body.strip()
    if meta_notes and body_notes and body_notes != meta_notes:
        verification_notes = f"{meta_notes}\n{body_notes}"
    else:
        verification_notes = meta_notes or body_notes

    return SourceCardContract(
        source_id=source_id,
        title=title,
        author=author,
        platform=platform,
        url_or_path=url_or_path,
        captured_at=captured_at,
        provenance_class=provenance_class,
        risk_level=risk_level,
        covered_concepts=covered_concepts,
        verification_notes=verification_notes,
    )


def serialize_source_card(card: SourceCardContract, body_markdown: str = "") -> str:
    """Serialize SourceCardContract into standard markdown with YAML frontmatter."""
    import yaml

    fm_dict = card.to_frontmatter_dict()
    yaml_header = yaml.safe_dump(
        fm_dict,
        sort_keys=False,
        allow_unicode=True,
    ).strip()

    notes = body_markdown.strip() or card.verification_notes.strip()
    if notes:
        return f"---\n{yaml_header}\n---\n\n{notes}\n"
    return f"---\n{yaml_header}\n---\n"
