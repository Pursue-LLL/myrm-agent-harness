"""Default baseline hard rules enforcing deterministic safety boundaries.

[INPUT]
- None (baseline static security invariants).

[OUTPUT]
- Immutable list of default HardRuleSpec definitions.

[POS]
- Ground-truth catalog of non-negotiable security red lines.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.pre_tool_use_interceptor.types import (
    HardRuleCategory,
    HardRuleSpec,
)

DEFAULT_HARD_RULES: list[HardRuleSpec] = [
    HardRuleSpec(
        rule_id="RULE-PROT-BRANCH",
        category=HardRuleCategory.PROTECTED_BRANCH_PUSH,
        pattern=r"\bgit\s+push\b.*?\b(main|master|release|prod|production)\b",
        description="Prevent direct git push commands targeting main, master, or release branches.",
        enabled=True,
    ),
    HardRuleSpec(
        rule_id="RULE-DESTR-RM",
        category=HardRuleCategory.DESTRUCTIVE_COMMAND,
        pattern=r"\brm\s+-(?:[a-zA-Z]*r[a-zA-Z]*f|[a-zA-Z]*f[a-zA-Z]*r)\s+(?:/|~|/\*|~/|\$HOME|\.\./\.\.)(?:\s|$)",
        description="Prevent destructive filesystem removal targeting root, home, or parent directories.",
        enabled=True,
    ),
    HardRuleSpec(
        rule_id="RULE-PROD-ENV",
        category=HardRuleCategory.PRODUCTION_ENV_MUTATION,
        pattern=r"(?:(?:>|>>)\s*\.env(?:\.prod|\.production)?\b|\b(?:truncate|overwrite|rm)\b.*?\.env(?:\.prod|\.production)?\b)",
        description="Prevent direct truncation, overwrite, or deletion of production environment files.",
        enabled=True,
    ),
    HardRuleSpec(
        rule_id="RULE-DB-DROP",
        category=HardRuleCategory.DATABASE_DROP,
        pattern=r"\b(?:DROP\s+DATABASE|DROP\s+TABLE|TRUNCATE\s+TABLE)\b",
        description="Prevent catastrophic destructive database operations without explicit human confirmation.",
        enabled=True,
    ),
]
