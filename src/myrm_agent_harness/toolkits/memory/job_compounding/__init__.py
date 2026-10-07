"""[POS]: src/myrm_agent_harness/toolkits/memory/job_compounding/__init__.py
[INPUT]: Submodules for models, job builder, compounding engine, and maturity tracker.
[OUTPUT]: Public exports for the domain job description and preference compounding suite.
"""

from .compounding_engine import PreferenceCompoundingEngine
from .job_builder import JobDescriptionBuilder
from .maturity_tracker import CompoundingMaturityTracker
from .models import (
    ApprovalBoundarySpec,
    CompoundedRule,
    CompoundingMaturityReport,
    JobDescriptionSpec,
    MaturityTier,
    RuleType,
)

__all__ = [
    "ApprovalBoundarySpec",
    "CompoundedRule",
    "CompoundingMaturityReport",
    "CompoundingMaturityTracker",
    "JobDescriptionBuilder",
    "JobDescriptionSpec",
    "MaturityTier",
    "PreferenceCompoundingEngine",
    "RuleType",
]
