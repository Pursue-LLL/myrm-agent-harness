"""Verification module for goal completion logic.

[INPUT]
- .gatekeeper::VerificationGatekeeper (POS: Orchestrator)
- .base::VerificationResult, AggregatedVerificationResult (POS: Result types)

[OUTPUT]
- VerificationGatekeeper
- VerificationResult
- AggregatedVerificationResult

[POS]
Exports verification entry points for use in goal_agent_tools.
"""

from myrm_agent_harness.agent.goals.verification.base import (
    AggregatedVerificationResult,
    VerificationResult,
)
from myrm_agent_harness.agent.goals.verification.gatekeeper import (
    VerificationGatekeeper,
)

__all__ = ["AggregatedVerificationResult", "VerificationGatekeeper", "VerificationResult"]
