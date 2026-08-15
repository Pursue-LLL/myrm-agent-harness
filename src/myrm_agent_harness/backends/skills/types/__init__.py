"""Skill system data types domain (aggregate facade).

[INPUT]
- Skill frontmatter contracts, enums, runtime metadata, dependency declarations.
- Skill instance / state protocols and security scan results.

[OUTPUT]
- Aggregate facade re-exporting every public name of the ``types`` subpackage:
  - types_contract: SkillContract* structured frontmatter contract types
  - types_enums: SkillTrust, SkillLifecycleStatus, SkillPermission enums
  - types_instance: SkillInstanceConfig, SkillStateProtocol, SkillInstance
  - types_metadata: SkillMetadata runtime representation
  - types_requires: SkillRequires and MCPSkillData dependency types
  - types_security: SecurityFindingDetail and SecurityScanSummary
  - types_usage: SkillUsageStats / SkillUsageRecord usage statistics
  - types_visibility: skill_visible_for_tools tool-conditional visibility filter
  - types_coercion: safe list coercion for type deserialization

[POS]
Framework generic skill system. The stable public entry point stays at
``backends.skills.types``; the nine ``types_*`` implementation modules are
co-located here under this facade.
"""

from myrm_agent_harness.backends.skills.types.types_contract import (
    SkillContract,
    SkillContractJudgment,
    SkillContractTrap,
    SkillContractVerification,
)
from myrm_agent_harness.backends.skills.types.types_enums import (
    SkillLifecycleStatus,
    SkillPermission,
    SkillTrust,
)
from myrm_agent_harness.backends.skills.types.types_instance import (
    SkillInstance,
    SkillInstanceConfig,
    SkillStateProtocol,
)
from myrm_agent_harness.backends.skills.types.types_metadata import SkillMetadata
from myrm_agent_harness.backends.skills.types.types_requires import MCPSkillData, SkillRequires
from myrm_agent_harness.backends.skills.types.types_security import SecurityFindingDetail, SecurityScanSummary
from myrm_agent_harness.backends.skills.types.types_usage import SkillUsageStats
from myrm_agent_harness.backends.skills.types.types_visibility import skill_visible_for_tools

__all__ = [
    "MCPSkillData",
    "SecurityFindingDetail",
    "SecurityScanSummary",
    "SkillContract",
    "SkillContractJudgment",
    "SkillContractTrap",
    "SkillContractVerification",
    "SkillInstance",
    "SkillInstanceConfig",
    "SkillLifecycleStatus",
    "SkillMetadata",
    "SkillPermission",
    "SkillRequires",
    "SkillStateProtocol",
    "SkillTrust",
    "SkillUsageStats",
    "skill_visible_for_tools",
]
