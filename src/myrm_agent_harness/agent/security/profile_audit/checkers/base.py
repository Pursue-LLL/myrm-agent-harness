"""Base checker protocol for profile audit.

[INPUT]
- ProfileAuditInput DTO

[OUTPUT]
- list[AuditFinding]

[POS]
Abstract base class for all profile audit checkers. Each checker inspects
one dimension of the Agent Profile configuration.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from myrm_agent_harness.agent.security.profile_audit.types import AuditFinding, ProfileAuditInput


class BaseChecker(ABC):
    """Base class for profile audit checkers."""

    @abstractmethod
    def check(self, audit_input: ProfileAuditInput) -> list[AuditFinding]:
        """Analyze the profile input and return findings."""
        ...
