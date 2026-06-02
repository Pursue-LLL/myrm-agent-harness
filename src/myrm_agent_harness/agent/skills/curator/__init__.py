"""Skill Curator — automated lifecycle governance for agent-created skills.

[OUTPUT]
- SkillCurator: Stateless curator engine (run sweeps)
- CuratorRunResult: Sweep result
- CuratorTransition: Individual transition record

[POS]
Skill Curator module. Provides automated lifecycle management (stale/archive/consolidation) for skills.
"""

from .engine import SkillCurator
from .types import CuratorRunResult, CuratorTransition

__all__ = [
    "CuratorRunResult",
    "CuratorTransition",
    "SkillCurator",
]
