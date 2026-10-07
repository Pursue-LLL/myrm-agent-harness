"""Types and models for git okf.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- GovernanceLevel: Governance level determining agent authority over code modifications.
- ConceptStatus: Lifecycle status of an OKF concept.
- OKFGenerated: Provenance tracking who authored the concept and when.
- OKFVerified: Provenance tracking human or machine verification events.
- OKFSource: Provenance source for factual claims.
- OKFConcept: Represents one concept markdown file in an OKF v0.2 knowledge bundle.
- OKFValidationReport: Diagnostics and conformance report for an OKF knowledge bundle.
- OKFSearchResult: Scored match result from in-memory BM25 lexical search.
- ConceptSummaryItem: Lightweight concept summary for two-phase progressive disclosure.
- OKFDisclosureSummary: First-phase progressive disclosure summary card (<300 tokens footprint).

[POS]
Types and models for git okf.
"""

# [POS]: myrm_agent_harness/toolkits/memory/git_okf/models.py
# [INPUT]: Concept metadata, governance rules, validation parameters, search queries
# [OUTPUT]: Strongly-typed Pydantic dataclasses/models for Google OKF v0.2 knowledge bundle

from dataclasses import dataclass, field
from enum import StrEnum


class GovernanceLevel(StrEnum):
    """Governance level determining agent authority over code modifications."""

    CONSTRAINT = "constraint"  # Mandatory rules/guardrails for code modifications
    HOLD = "hold"              # Execution freeze / manual human signoff required
    CONTEXT = "context"        # Informative domain knowledge and background


class ConceptStatus(StrEnum):
    """Lifecycle status of an OKF concept."""

    DRAFT = "draft"
    STABLE = "stable"
    DEPRECATED = "deprecated"


@dataclass(slots=True)
class OKFGenerated:
    """Provenance tracking who authored the concept and when."""

    by: str  # e.g., "agent/myrm-v1" or "human/developer"
    at: str  # ISO 8601 timestamp


@dataclass(slots=True)
class OKFVerified:
    """Provenance tracking human or machine verification events."""

    by: str  # e.g., "human/architect-alice"
    at: str  # ISO 8601 timestamp


@dataclass(slots=True)
class OKFSource:
    """Provenance source for factual claims."""

    resource: str
    id: str = ""
    title: str = ""
    author: str = ""
    last_modified: str = ""
    usage_count: int = 0


@dataclass(slots=True)
class OKFConcept:
    """Represents one concept markdown file in an OKF v0.2 knowledge bundle."""

    id: str                                  # Bundle-relative identifier without .md, e.g. "conventions/auth"
    path: str                                # Relative file path with .md, e.g. "conventions/auth.md"
    type: str                                # Concept type, e.g. "rule", "architecture", "standard"
    title: str = ""
    description: str = ""
    governance: GovernanceLevel = GovernanceLevel.CONTEXT
    status: ConceptStatus = ConceptStatus.STABLE
    stale_after: str = ""                    # ISO 8601 date YYYY-MM-DD
    code_refs: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    generated: OKFGenerated | None = None
    verified: list[OKFVerified] = field(default_factory=list)
    sources: list[OKFSource] = field(default_factory=list)
    body: str = ""                           # Markdown content after frontmatter
    raw_content: str = ""

    def effective_governance(self) -> GovernanceLevel:
        """Derive effective governance level following OKF v0.2 defaults."""
        if self.governance == GovernanceLevel.CONSTRAINT or self.governance == GovernanceLevel.HOLD:
            return self.governance
        if self.id.startswith("conventions/") or self.id.startswith("convention/"):
            return GovernanceLevel.CONSTRAINT
        return GovernanceLevel.CONTEXT


@dataclass(slots=True)
class OKFValidationReport:
    """Diagnostics and conformance report for an OKF knowledge bundle."""

    bundle_path: str
    declared_version: str
    concept_count: int
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    gate_findings: list[str] = field(default_factory=list)
    stale_count: int = 0
    superseded_trust_count: int = 0
    is_conformant: bool = True
    gate_passed: bool = True


@dataclass(slots=True)
class OKFSearchResult:
    """Scored match result from in-memory BM25 lexical search."""

    concept_id: str
    title: str
    type: str
    description: str
    governance: str
    score: float
    matched_fields: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    code_refs: list[str] = field(default_factory=list)
    is_stale: bool = False


@dataclass(slots=True)
class ConceptSummaryItem:
    """Lightweight concept summary for two-phase progressive disclosure."""

    id: str
    title: str
    description: str
    governance: str
    status: str
    is_stale: bool
    code_refs: list[str] = field(default_factory=list)


@dataclass(slots=True)
class OKFDisclosureSummary:
    """First-phase progressive disclosure summary card (<300 tokens footprint)."""

    bundle_path: str
    total_concepts: int
    stale_count: int
    concepts: list[ConceptSummaryItem] = field(default_factory=list)
