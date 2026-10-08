"""Topic Drift Demarcation and Auto-Renamed Session Fork module.

[INPUT]
- agent.context_management.topic_drift_fork.session_fork_manager::SessionForkManager (POS: Session Fork
  Manager coordinating auto-renaming, carryover summary extraction, and clean session forking.)
- agent.context_management.topic_drift_fork.topic_drift_detector::TopicDriftDetector (POS: Topic drift
  detector assessing task milestone closure and cross-task semantic divergence.)
-
  agent.context_management.topic_drift_fork.topic_drift_fork_suite::TopicDriftDemarcationAndAutoRenamedSessionForkSuite
  (POS: Topic Drift Demarcation and Auto-Renamed Session Fork Suite master class.)
- agent.context_management.topic_drift_fork.topic_drift_types::DriftSignalKind, ForkExecutionResult,
  SessionForkSuggestion, TopicDriftEvaluation (POS: Data contracts and type definitions for topic drift
  demarcation and auto-renamed session forking.)

[OUTPUT]
- Re-exports: DriftSignalKind, ForkExecutionResult, SessionForkManager, SessionForkSuggestion,
  TopicDriftDemarcationAndAutoRenamedSessionForkSuite, TopicDriftEvaluation

[POS]
Topic Drift Demarcation and Auto-Renamed Session Fork module.
"""

from .session_fork_manager import SessionForkManager
from .topic_drift_detector import TopicDriftDetector
from .topic_drift_fork_suite import TopicDriftDemarcationAndAutoRenamedSessionForkSuite
from .topic_drift_types import (
    DriftSignalKind,
    ForkExecutionResult,
    SessionForkSuggestion,
    TopicDriftEvaluation,
)

__all__ = [
    "DriftSignalKind",
    "ForkExecutionResult",
    "SessionForkManager",
    "SessionForkSuggestion",
    "TopicDriftDemarcationAndAutoRenamedSessionForkSuite",
    "TopicDriftEvaluation",
]
