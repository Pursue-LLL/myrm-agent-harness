"""Engine for 4-layer progressive disclosure cognitive path and evidence traceability.

Coordinates the 5-stage architectural discovery state machine, dynamically
assembles minimal required context per stage, and enforces evidence attribution citations.
"""

import logging
import re
import time
from typing import Optional

from .progressive_disclosure_types import (
    AttributionValidationResult,
    CognitiveMilestoneFact,
    DisclosureStage,
    EvidenceCitation,
    ProgressiveDisclosureConfig,
)

logger = logging.getLogger(__name__)

STAGE_SEQUENCE: list[DisclosureStage] = [
    DisclosureStage.BUSINESS_META,
    DisclosureStage.ARCHITECTURE_TOPOLOGY,
    DisclosureStage.SERVICE_SCHEMA,
    DisclosureStage.INFRASTRUCTURE_GUARD,
    DisclosureStage.CODE_EVIDENCE_GROUNDING,
    DisclosureStage.COMPLETED,
]


class ProgressiveDisclosureEngine:
    """Core engine driving progressive cognitive disclosure and evidence attribution enforcement."""

    def __init__(self, config: Optional[ProgressiveDisclosureConfig] = None) -> None:
        self.config = config or ProgressiveDisclosureConfig()
        self._session_stages: dict[str, DisclosureStage] = {}
        self._session_milestones: dict[str, list[CognitiveMilestoneFact]] = {}
        self._session_intents: dict[str, str] = {}

    def initialize_session_path(self, session_id: str, task_intent: str) -> DisclosureStage:
        """Initialize session cognitive path at Stage 1 (BUSINESS_META)."""
        initial_stage = DisclosureStage.BUSINESS_META
        self._session_stages[session_id] = initial_stage
        self._session_milestones[session_id] = []
        self._session_intents[session_id] = task_intent
        logger.info("Initialized progressive disclosure for session %s at stage %s", session_id, initial_stage.value)
        return initial_stage

    def get_current_stage(self, session_id: str) -> DisclosureStage:
        """Return the current active disclosure stage for the session."""
        return self._session_stages.get(session_id, DisclosureStage.BUSINESS_META)

    def advance_stage(
        self,
        session_id: str,
        stage_findings: str,
        citations: list[EvidenceCitation],
    ) -> DisclosureStage:
        """Record findings for the current stage and step to the next progressive stage."""
        current_stage = self.get_current_stage(session_id)
        if current_stage == DisclosureStage.COMPLETED:
            return DisclosureStage.COMPLETED

        # Record milestone fact for the concluded stage
        fact = CognitiveMilestoneFact(
            stage=current_stage,
            key_finding=stage_findings,
            citations=list(citations),
            recorded_at=time.time(),
        )
        self._session_milestones.setdefault(session_id, []).append(fact)

        # Transition to next stage in canonical sequence
        idx = STAGE_SEQUENCE.index(current_stage)
        next_stage = STAGE_SEQUENCE[idx + 1] if idx + 1 < len(STAGE_SEQUENCE) else DisclosureStage.COMPLETED
        self._session_stages[session_id] = next_stage
        logger.info(
            "Session %s transitioned from %s to %s with %d citations",
            session_id,
            current_stage.value,
            next_stage.value,
            len(citations),
        )
        return next_stage

    def assemble_stage_context(
        self,
        session_id: str,
        stage_specific_payload: str,
    ) -> dict[str, str]:
        """Assemble minimal stage-focused context, condensing prior milestones into compact digests."""
        current_stage = self.get_current_stage(session_id)
        milestones = self._session_milestones.get(session_id, [])

        # Build condensed summary of established prior milestone facts
        milestone_lines: list[str] = []
        for m in milestones:
            cite_tags = " ".join([c.format_tag() for c in m.citations])
            milestone_lines.append(f"- [{m.stage.value}] {m.key_finding} {cite_tags}".strip())

        established_facts_block = "\n".join(milestone_lines) if milestone_lines else "None (initial stage)"

        system_guidance = (
            f"Current Cognitive Stage: [{current_stage.value.upper()}]\n"
            f"Established Architectural Facts:\n{established_facts_block}\n"
            "Rule: Focus exclusively on current stage objectives. Ground all conclusions in explicit evidence."
        )

        return {
            "session_id": session_id,
            "stage": current_stage.value,
            "guidance_header": system_guidance,
            "stage_payload": stage_specific_payload,
        }

    def validate_evidence_attribution(
        self,
        session_id: str,
        proposal_text: str,
    ) -> AttributionValidationResult:
        """Audit architectural proposal text to ensure assertions contain valid evidence citation tags."""
        # Find citations in formats like: [代码] path/to/file:123, [契约] file.yaml:45, [原则] policy.md:12
        citation_pattern = r"\[(代码|契约|原则|规则)\]\s+([\w\.\/\-_]+):(\d+)"
        matches = re.findall(citation_pattern, proposal_text)

        citations_found: list[str] = [f"[{m[0]}] {m[1]}:{m[2]}" for m in matches]
        violations: list[str] = []

        # Check for architectural claims and action assertions
        action_keywords = [
            "modify", "change", "refactor", "update", "implement", "enforce", "integrate",
            "修改", "重构", "调用", "依赖", "实现", "引入", "规范",
        ]
        lines = [line.strip() for line in proposal_text.splitlines() if line.strip()]
        claim_lines = [
            line for line in lines
            if (any(kw in line.lower() for kw in action_keywords) or re.search(citation_pattern, line))
            and not line.startswith("#")
        ]

        total_claims = len(claim_lines)
        verified_claims = 0

        for claim in claim_lines:
            if re.search(citation_pattern, claim):
                verified_claims += 1
            else:
                if self.config.strict_evidence_enforcement:
                    violations.append(f"Unsubstantiated architectural claim lacking evidence citation: '{claim[:80]}...'")

        unverified_claims = total_claims - verified_claims
        is_valid = (len(violations) == 0) and (len(citations_found) > 0 or total_claims == 0)

        if not citations_found and total_claims > 0:
            is_valid = False
            violations.append("Proposal contains action items but 0 evidence citations were detected.")

        return AttributionValidationResult(
            is_valid=is_valid,
            total_claims=total_claims,
            verified_claims=verified_claims,
            unverified_claims=unverified_claims,
            violations=violations,
            citations_found=citations_found,
        )

    def get_cognitive_path_summary(self, session_id: str) -> list[CognitiveMilestoneFact]:
        """Retrieve full audit trail of established cognitive milestone facts for the session."""
        return list(self._session_milestones.get(session_id, []))
