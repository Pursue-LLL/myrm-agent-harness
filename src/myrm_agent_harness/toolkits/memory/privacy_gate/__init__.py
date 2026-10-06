# [POS]: myrm_agent_harness/toolkits/memory/privacy_gate/__init__.py
# [INPUT]: None
# [OUTPUT]: MemoryPrivacyBoundaryGate, DeterministicSecretDetector, PathAndExclusionMatcher, types
"""Public entry point for memory privacy boundary and allowlist gate.

Provides static secret scanning, .myrmignore path matching, and hard veto enforcement
to prevent secret leakage into long-term memory or versioned Markdown Wikis.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.privacy_gate.gate import MemoryPrivacyBoundaryGate
from myrm_agent_harness.toolkits.memory.privacy_gate.rule_matcher import PathAndExclusionMatcher
from myrm_agent_harness.toolkits.memory.privacy_gate.secret_detector import DeterministicSecretDetector
from myrm_agent_harness.toolkits.memory.privacy_gate.types import (
    InvalidPrivacyConfigError,
    MemoryPrivacyConfig,
    MemoryPrivacyError,
    PrivacyBoundaryViolationError,
    PrivacyCheckResult,
    PrivacySensitivityLevel,
    PrivacyViolationType,
    SecretFinding,
)

__all__ = [
    "DeterministicSecretDetector",
    "InvalidPrivacyConfigError",
    "MemoryPrivacyBoundaryGate",
    "MemoryPrivacyConfig",
    "MemoryPrivacyError",
    "PathAndExclusionMatcher",
    "PrivacyBoundaryViolationError",
    "PrivacyCheckResult",
    "PrivacySensitivityLevel",
    "PrivacyViolationType",
    "SecretFinding",
]
