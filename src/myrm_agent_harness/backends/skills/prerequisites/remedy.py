"""Compatibility stub for remedy generator.

[DEPRECATED]
Consolidated into myrm_agent_harness.backends.skills.prerequisites.remediation
"""

from __future__ import annotations

from .remediation import AutoRemedyGenerator, COMMON_BINARY_PACKAGES

# Backward compatibility alias
BINARY_PACKAGE_MAP = COMMON_BINARY_PACKAGES

__all__ = ["AutoRemedyGenerator", "BINARY_PACKAGE_MAP"]
