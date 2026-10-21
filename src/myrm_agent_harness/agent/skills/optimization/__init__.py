"""Skill Optimization Toolkit

Building blocks for skill version history and skill content security validation.

## Framework Layer (myrm-agent-harness)

Protocol-based, no business dependencies:
- **SkillSecurityValidator**: multi-layer security validation of skill content
- **SkillOptimizationStorage**: protocol the business layer implements for skill version history
- **SkillVersion**: record of one skill version (content, author, active flag)

## Business Layer (myrm-agent-server)

- **SQLAlchemyStorage**: SkillOptimizationStorage adapter (SQLite/PostgreSQL)
"""

from .config import SecurityConfig
from .protocols import SkillOptimizationStorage, StorageError
from .security import SkillSecurityValidator
from .types import SecurityError, SecurityValidationResult, SkillVersion

__all__ = [
    "SecurityConfig",
    "SecurityError",
    "SecurityValidationResult",
    "SkillOptimizationStorage",
    "SkillSecurityValidator",
    "SkillVersion",
    "StorageError",
]
