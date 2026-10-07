"""Skill Curator — automated lifecycle governance for agent-created skills.

[OUTPUT]
- SkillCurator: Stateless curator engine (run sweeps)
- CuratorRunResult: Sweep result
- CuratorTransition: Individual transition record

[POS]
Skill Curator module. Provides automated lifecycle management (stale/archive/consolidation) for skills.
"""

from .anti_sycophancy_adversarial_engine import (
    AntiSycophancyAdversarialEngine,
)
from .anti_sycophancy_types import (
    AdversarialCriticRole,
    AdversarialReviewResult,
    CuratedAction,
    CuratedItemVerdict,
    CuratorCustomRules,
    CuratorDismantlingReport,
    CuratorEvaluationMetric,
)
from .engine import SkillCurator
from .self_dismantling_curator_engine import SelfDismantlingCuratorEngine
from .types import CuratorRunResult, CuratorTransition

__all__ = [
    "AdversarialCriticRole",
    "AdversarialReviewResult",
    "AntiSycophancyAdversarialEngine",
    "CuratedAction",
    "CuratedItemVerdict",
    "CuratorCustomRules",
    "CuratorDismantlingReport",
    "CuratorEvaluationMetric",
    "CuratorRunResult",
    "CuratorTransition",
    "SelfDismantlingCuratorEngine",
    "SkillCurator",
]
