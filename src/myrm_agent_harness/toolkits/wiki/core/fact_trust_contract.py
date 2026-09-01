"""Shared Workspace Trust Structure contract.

[INPUT]
utils.markdown_frontmatter::parse_frontmatter (POS: YAML FM parse SSOT)

[OUTPUT]
FactStatus, FactTrustLevel, FACT_STATUSES, resolve_fact_status, FactTrustPolicy,
DEFAULT_FACT_TRUST_POLICY

[POS]
Harness SSOT for three-tier fact trust contract (published_truth, in_progress_draft, deprecated)
across Wiki concepts, workspace documents, and RAG retrieval gating.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from myrm_agent_harness.utils.markdown_frontmatter import parse_frontmatter

FACT_STATUS_KEY = "fact_status"


class FactStatus(StrEnum):
    """Three-tier fact status classification for shared workspace trust structure."""

    PUBLISHED_TRUTH = "published_truth"
    IN_PROGRESS_DRAFT = "in_progress_draft"
    DEPRECATED = "deprecated"


FACT_STATUSES: frozenset[str] = frozenset(member.value for member in FactStatus)


class FactTrustLevel(StrEnum):
    """Normalized trust level for UI display and audit logging."""

    HIGH = "high"  # published_truth
    MEDIUM = "medium"  # in_progress_draft
    LOW = "low"  # deprecated


@dataclass(frozen=True, slots=True)
class FactTrustPolicy:
    """Weight multipliers and filtering policy for three-tier fact retrieval."""

    truth_boost: float = 1.2
    draft_multiplier: float = 0.3
    deprecated_multiplier: float = 0.1
    include_drafts_by_default: bool = False
    include_deprecated_by_default: bool = False

    def get_multiplier(self, status: FactStatus) -> float:
        if status == FactStatus.PUBLISHED_TRUTH:
            return self.truth_boost
        if status == FactStatus.IN_PROGRESS_DRAFT:
            return self.draft_multiplier
        if status == FactStatus.DEPRECATED:
            return self.deprecated_multiplier
        return 1.0


DEFAULT_FACT_TRUST_POLICY = FactTrustPolicy()


def infer_fact_status_from_path(file_path: str | Path) -> FactStatus:
    """Infer default fact status from path conventions (truth/, drafts/, archive/)."""
    path_str = str(file_path).replace("\\", "/").lower()
    parts = [p for p in path_str.split("/") if p]
    if any(p in ("archive", "deprecated", "legacy") for p in parts):
        return FactStatus.DEPRECATED
    if any(p in ("drafts", "draft", "in_progress", "wip") for p in parts):
        return FactStatus.IN_PROGRESS_DRAFT
    if any(p in ("truth", "facts", "verified", "production") for p in parts):
        return FactStatus.PUBLISHED_TRUTH
    return FactStatus.PUBLISHED_TRUTH


def resolve_fact_status(content: str, *, file_path: str | Path | None = None) -> FactStatus:
    """
    Resolve fact status with Frontmatter having top priority over directory path.

    1. Explicit `fact_status` in Frontmatter
    2. Fallback to `publish_status` (published -> published_truth, draft -> in_progress_draft, blocked -> deprecated)
    3. Path convention inference (if file_path provided)
    4. Default: PUBLISHED_TRUTH
    """
    metadata, _body = parse_frontmatter(content)
    raw_status = str(metadata.get(FACT_STATUS_KEY, "")).strip().lower()
    if raw_status in FACT_STATUSES:
        return FactStatus(raw_status)

    publish_status = str(metadata.get("publish_status", "")).strip().lower()
    if publish_status == "draft":
        return FactStatus.IN_PROGRESS_DRAFT
    if publish_status == "blocked":
        return FactStatus.DEPRECATED
    if publish_status == "published":
        return FactStatus.PUBLISHED_TRUTH

    if file_path is not None:
        return infer_fact_status_from_path(file_path)

    return FactStatus.PUBLISHED_TRUTH
