"""Verification module for goal completion logic.

[INPUT]
- .gatekeeper::VerificationGatekeeper (POS: Orchestrator)
- .base::VerificationResult (POS: Result type)

[OUTPUT]
- VerificationGatekeeper
- VerificationResult

[POS]
Exports verification entry points for use in goal_agent_tools.
"""

from myrm_agent_harness.agent.goals.verification.base import VerificationResult
from myrm_agent_harness.agent.goals.verification.gatekeeper import (
    VerificationGatekeeper,
)

__all__ = ["VerificationGatekeeper", "VerificationResult"]
