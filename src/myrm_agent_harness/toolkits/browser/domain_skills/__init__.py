"""Domain executable skills — browser domain-level acceleration.

[INPUT]
- (none)

[OUTPUT]
- DomainSkillStore: Domain skill registry.
- DomainSkillManifest: Manifest for a domain skill set.
- DomainTool: Single tool declaration.
- get_global_domain_skill_store: Singleton accessor.

[POS]
Executable-layer domain skills for browser automation acceleration.
"""

from .store import DomainSkillStore, get_global_domain_skill_store
from .types import DomainSkillManifest, DomainTool

__all__ = [
    "DomainSkillManifest",
    "DomainSkillStore",
    "DomainTool",
    "get_global_domain_skill_store",
]
