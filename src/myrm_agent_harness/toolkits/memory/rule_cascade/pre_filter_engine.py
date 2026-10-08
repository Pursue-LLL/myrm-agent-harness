"""Pre-filtering engine enforcing physical boundary checks before vector/FTS recall.

[INPUT]
- toolkits.memory.rule_cascade.decay_calculator::TimeDecayCalculator (POS: Calculates exponential half-life
  decay and dynamic confidence for evidence facts.)
- toolkits.memory.rule_cascade.models::DeterministicRuleEntry, EvidencePermissionLevel, FiveDimFilterSpec,
  PreFilteredEvidenceResult (POS: Types and models for rule cascade.)

[OUTPUT]
- FiveDimPreFilterEngine: Pre-filtering engine enforcing physical boundary checks before vector/FTS recall.

[POS]
Pre-filtering engine enforcing physical boundary checks before vector/FTS recall.
"""

# [POS]: src/myrm_agent_harness/toolkits/memory/rule_cascade/pre_filter_engine.py
# [INPUT]: decay_calculator.py, models.py (DeterministicRuleEntry, FiveDimFilterSpec, PreFilteredEvidenceResult)
# [OUTPUT]: FiveDimPreFilterEngine

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.rule_cascade.decay_calculator import (
    TimeDecayCalculator,
)
from myrm_agent_harness.toolkits.memory.rule_cascade.models import (
    DeterministicRuleEntry,
    EvidencePermissionLevel,
    FiveDimFilterSpec,
    PreFilteredEvidenceResult,
)

logger = logging.getLogger(__name__)

_PERMISSION_LEVEL_RANK: dict[EvidencePermissionLevel, int] = {
    EvidencePermissionLevel.PUBLIC: 0,
    EvidencePermissionLevel.WORKSPACE_INTERNAL: 1,
    EvidencePermissionLevel.CONFIDENTIAL_ADMIN: 2,
}


class FiveDimPreFilterEngine:
    """Pre-filtering engine enforcing physical boundary checks before vector/FTS recall.

    Guarantees that unauthorized, expired, or out-of-scope memories are completely blocked
    at query formulation time, never polluting prompt context or relying on LLM self-censorship.
    """

    def __init__(self, decay_calculator: TimeDecayCalculator | None = None) -> None:
        self._decay = decay_calculator or TimeDecayCalculator()

    def filter_evidence(
        self,
        candidates: Sequence[DeterministicRuleEntry],
        spec: FiveDimFilterSpec,
        now: datetime | None = None,
    ) -> PreFilteredEvidenceResult:
        """Evaluate candidate evidence items against the 5-dimensional boundary specification."""
        current_time = now or datetime.now(UTC)
        passed: list[DeterministicRuleEntry] = []
        rejection_reasons: dict[str, int] = defaultdict(int)

        req_perm_rank = (
            _PERMISSION_LEVEL_RANK[spec.required_permission]
            if spec.required_permission is not None
            else _PERMISSION_LEVEL_RANK[EvidencePermissionLevel.CONFIDENTIAL_ADMIN]
        )

        for rule in candidates:
            meta = rule.metadata

            # Dimension 1: Scope filtering
            if spec.allowed_scopes is not None and meta.scope not in spec.allowed_scopes:
                rejection_reasons["scope_disallowed"] += 1
                continue

            if spec.scope_path_prefix is not None:
                prefix = spec.scope_path_prefix.rstrip("/")
                rule_path = meta.scope_path.rstrip("/")
                # Allowed if rule_path starts with prefix OR prefix starts with rule_path (ancestor)
                if not (rule_path.startswith(prefix) or prefix.startswith(rule_path)):
                    rejection_reasons["path_prefix_mismatch"] += 1
                    continue

            # Dimension 2: Source authority
            if meta.source_authority < spec.min_authority:
                rejection_reasons["authority_insufficient"] += 1
                continue

            # Dimension 3: Time elapsed and half-life decay
            elapsed_days = self._decay.calculate_elapsed_days(meta.created_at, now=current_time)
            if spec.max_decay_age_days is not None and elapsed_days > spec.max_decay_age_days:
                rejection_reasons["max_age_exceeded"] += 1
                continue

            # Dimension 4: Effective confidence
            effective_conf = self._decay.compute_effective_confidence(meta, now=current_time)
            if effective_conf < spec.min_confidence:
                rejection_reasons["confidence_too_low"] += 1
                continue

            # Dimension 5: Permission barrier
            rule_perm_rank = _PERMISSION_LEVEL_RANK.get(
                meta.permission, _PERMISSION_LEVEL_RANK[EvidencePermissionLevel.PUBLIC]
            )
            if rule_perm_rank > req_perm_rank:
                rejection_reasons["permission_denied"] += 1
                continue

            passed.append(rule)

        return PreFilteredEvidenceResult(
            items=passed,
            total_evaluated=len(candidates),
            passed_count=len(passed),
            rejection_reasons=dict(rejection_reasons),
        )
