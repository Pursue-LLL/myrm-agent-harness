"""Data contracts and types for lazy-loaded subdirectory rules discovery and dynamic tool injection.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- SubdirectoryRuleDiscoveryMode: Injection mode defining when subdirectory rules should be appended to tool
  output.
- DiscoveredSubdirectoryRule: An on-demand discovered rule file located in a subdirectory.
- DynamicToolInjectionEnvelope: Envelope containing the augmented tool execution result with localized
  rules.

[POS]
Data contracts and types for lazy-loaded subdirectory rules discovery and dynamic tool injection.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum


class SubdirectoryRuleDiscoveryMode(StrEnum):
    """Injection mode defining when subdirectory rules should be appended to tool output."""

    ON_FIRST_ACCESS = "on_first_access"  # Injects only once per session per directory (cache-friendly)
    ALWAYS_ATTACH = "always_attach"  # Attaches rules to every tool execution targeting this directory


@dataclass(frozen=True)
class DiscoveredSubdirectoryRule:
    """An on-demand discovered rule file located in a subdirectory."""

    rule_path: str
    directory_scope: str
    rule_content: str
    sha256_hash: str = field(init=False)
    token_count: int = field(init=False)

    def __post_init__(self) -> None:
        clean = self.rule_content.strip()
        h = hashlib.sha256(clean.encode("utf-8")).hexdigest()
        tokens = max(1, len(clean) // 4)
        object.__setattr__(self, "sha256_hash", h)
        object.__setattr__(self, "token_count", tokens)


@dataclass(frozen=True)
class DynamicToolInjectionEnvelope:
    """Envelope containing the augmented tool execution result with localized rules."""

    original_tool_output: str
    augmented_tool_output: str
    injected_rules: tuple[DiscoveredSubdirectoryRule, ...] = field(default_factory=tuple)
    was_injected: bool = False
    directory_matched: str = ""
