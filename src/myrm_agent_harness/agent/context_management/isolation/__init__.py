"""Package facade for isolation.

[INPUT]
- agent.context_management.isolation.project_context_isolation_filter::ProjectContextIsolationFilter (POS:
  Guards context against cross-project data bleed and asserts task alignment.)
- agent.context_management.isolation.project_isolation_types::CrossProjectCheckResult,
  ObjectiveRecapAssertion, ObjectiveRecapStatus, ProjectBoundary (POS: Types and models for project
  isolation.)

[OUTPUT]
- Re-exports: CrossProjectCheckResult, ObjectiveRecapAssertion, ObjectiveRecapStatus, ProjectBoundary,
  ProjectContextIsolationFilter

[POS]
Package facade for isolation.
"""

# ============================================================================
# # Project Context Isolation & Objective Recap Module (Item 145)
# ============================================================================

from .project_context_isolation_filter import ProjectContextIsolationFilter
from .project_isolation_types import (
    CrossProjectCheckResult,
    ObjectiveRecapAssertion,
    ObjectiveRecapStatus,
    ProjectBoundary,
)

__all__ = [
    "CrossProjectCheckResult",
    "ObjectiveRecapAssertion",
    "ObjectiveRecapStatus",
    "ProjectBoundary",
    "ProjectContextIsolationFilter",
]
