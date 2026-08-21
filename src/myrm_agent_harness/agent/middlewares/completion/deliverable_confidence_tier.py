"""Deliverable Confidence Tier SSOT and physical evidence resolver.

Defines the core DeliverableConfidenceTier enumeration and deterministic resolver
that evaluates session CallRecords, file mutations, and verification results to
assign a verifiable confidence tier to the agent's delivery.

[INPUT]
- agent.security.guards.loop_guard::CallRecord, ToolGroup, SuccessLevel, VerificationCategory, get_tool_group

[OUTPUT]
- DeliverableConfidenceTier: SSOT enum (VERIFIED, ARTIFACT, RESEARCH, PLAN)
- DeliverableTierMetadata: Structured delivery confidence report
- resolve_deliverable_tier(): Deterministic physical evidence aggregator (<0.05ms)

[POS]
Core SSOT contract for delivery confidence evaluation; consumed by CompletionGuard,
Server SSE/API, Cron post-run assurance, and WebUI/Tauri frontend badges.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.security.guards.loop_guard import (
    CallRecord,
    SuccessLevel,
    ToolGroup,
    VerificationCategory,
    get_tool_group,
)

if TYPE_CHECKING:
    from myrm_agent_harness.agent.goals.verification.base import AggregatedVerificationResult


class DeliverableConfidenceTier(str, Enum):
    """Deliverable Confidence Tier SSOT."""

    VERIFIED = "VERIFIED"  # Passed automated tests/checks or independent sandbox re-run
    ARTIFACT = "ARTIFACT"  # Concrete workspace deliverable file created/modified on disk
    RESEARCH = "RESEARCH"  # Informational output backed by external research/search citations
    PLAN = "PLAN"  # Conceptual plan, discussion, or unverified initial proposal


@dataclass(frozen=True, slots=True)
class DeliverableTierEvidence:
    """Evidence metrics supporting the deliverable confidence tier."""

    verification_count: int = 0
    verification_categories: list[str] = field(default_factory=list)
    files_written: list[str] = field(default_factory=list)
    sources_count: int = 0
    gatekeeper_passed: bool = False
    details: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "verification_count": self.verification_count,
            "verification_categories": list(self.verification_categories),
            "files_written": list(self.files_written),
            "sources_count": self.sources_count,
            "gatekeeper_passed": self.gatekeeper_passed,
            "details": self.details,
        }


@dataclass(frozen=True, slots=True)
class DeliverableTierMetadata:
    """Complete deliverable tier descriptor attached to outgoing messages/results."""

    tier: DeliverableConfidenceTier
    evidence: DeliverableTierEvidence

    def to_dict(self) -> dict[str, object]:
        return {
            "tier": self.tier.value,
            "evidence": self.evidence.to_dict(),
        }


def resolve_deliverable_tier(
    records: list[CallRecord],
    *,
    gatekeeper_result: AggregatedVerificationResult | None = None,
    cron_verified: bool | None = None,
    content: str = "",
) -> DeliverableTierMetadata:
    """Deterministically resolve the DeliverableConfidenceTier from session facts.

    Priority hierarchy:
    1. VERIFIED: Successful automated tests/lint/build, or passed Gatekeeper/Cron verification.
    2. ARTIFACT: Successful file write/edit tool calls with real workspace modifications.
    3. RESEARCH: Successful web search/fetch/reading tool calls.
    4. PLAN: Default baseline for conceptual plans or pure LLM reasoning.
    """
    # 1. Evaluate verification facts
    verifications: list[str] = []
    for record in records:
        if (
            record.verification_type is not None
            and record.success_level not in (SuccessLevel.FAILURE, SuccessLevel.EMPTY_OK)
        ):
            verifications.append(record.verification_type.value)

    has_gatekeeper_pass = gatekeeper_result is not None and gatekeeper_result.passed and bool(gatekeeper_result.per_criterion)
    is_cron_verified = cron_verified is True
    is_verified = (len(verifications) > 0) or has_gatekeeper_pass or is_cron_verified

    # 2. Evaluate file artifact writes
    files_written: list[str] = []
    for record in records:
        grp = get_tool_group(record.tool_name)
        if (
            grp == ToolGroup.WRITE
            and record.success_level != SuccessLevel.FAILURE
        ):
            path = str(record.args.get("path", "")).strip()
            if path and path not in files_written:
                files_written.append(path)

    # 3. Evaluate external research sources
    sources_count = 0
    for record in records:
        grp = get_tool_group(record.tool_name)
        if (
            grp in (ToolGroup.SEARCH, ToolGroup.BROWSER, ToolGroup.NETWORK)
            and record.success_level != SuccessLevel.FAILURE
        ):
            sources_count += 1

    evidence = DeliverableTierEvidence(
        verification_count=len(verifications),
        verification_categories=sorted(set(verifications)),
        files_written=files_written,
        sources_count=sources_count,
        gatekeeper_passed=has_gatekeeper_pass,
        details=(
            f"{len(verifications)} verifications passed"
            if is_verified
            else (
                f"{len(files_written)} artifacts written"
                if files_written
                else (f"{sources_count} research sources consulted" if sources_count > 0 else "Plan/Discussion")
            )
        ),
    )

    if is_verified:
        return DeliverableTierMetadata(tier=DeliverableConfidenceTier.VERIFIED, evidence=evidence)

    if files_written:
        return DeliverableTierMetadata(tier=DeliverableConfidenceTier.ARTIFACT, evidence=evidence)

    if sources_count > 0:
        return DeliverableTierMetadata(tier=DeliverableConfidenceTier.RESEARCH, evidence=evidence)

    return DeliverableTierMetadata(tier=DeliverableConfidenceTier.PLAN, evidence=evidence)


__all__ = [
    "DeliverableConfidenceTier",
    "DeliverableTierEvidence",
    "DeliverableTierMetadata",
    "resolve_deliverable_tier",
]
