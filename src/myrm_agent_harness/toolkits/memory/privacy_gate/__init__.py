"""Public entry point for memory privacy boundary and allowlist gate.

Provides static secret scanning, .myrmignore path matching, and hard veto enforcement
to prevent secret leakage into long-term memory or versioned Markdown Wikis.
Strict typing applied: No `Any` types allowed.

[INPUT]
- toolkits.memory.privacy_gate.gate::MemoryPrivacyBoundaryGate (POS: Memory privacy boundary gate enforcing
  exclusion rules, secret detection, and safe redaction.)
- toolkits.memory.privacy_gate.rule_matcher::PathAndExclusionMatcher (POS: Path and content rule matcher for
  memory privacy boundaries.)
- toolkits.memory.privacy_gate.secret_detector::DeterministicSecretDetector (POS: Deterministic
  pattern-based detector for high-risk secrets and credentials.)
- toolkits.memory.privacy_gate.types::InvalidPrivacyConfigError, MemoryPrivacyConfig, MemoryPrivacyError,
  PrivacyBoundaryViolationError, PrivacyCheckResult, PrivacySensitivityLevel, PrivacyViolationType,
  SecretFinding (POS: Type definitions and contracts for memory privacy boundary and allowlist gate.)

[OUTPUT]
- Package facade re-exporting 11 public names: DeterministicSecretDetector, InvalidPrivacyConfigError,
  MemoryPrivacyBoundaryGate, MemoryPrivacyConfig, MemoryPrivacyError, PathAndExclusionMatcher,
  PrivacyBoundaryViolationError, PrivacyCheckResult, PrivacySensitivityLevel, PrivacyViolationType,
  SecretFinding

[POS]
Public entry point for memory privacy boundary and allowlist gate.
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
