"""Public facade of the self verification subsystem.

[INPUT]
- toolkits.memory.self_verification.runner::MemorySelfVerificationRunner (POS: Automated benchmark runner
  for in-place mutation and semantic verification.)
- toolkits.memory.self_verification.types::FactMutationProbeResult, MemoryVerificationReport,
  ProceduralAntiDropProbeResult, VerificationHealthGrade, ZeroLexicalOverlapProbeResult (POS: Typed data
  contracts for the self verification subsystem.)

[OUTPUT]
- Package facade re-exporting 6 public names: FactMutationProbeResult, MemorySelfVerificationRunner,
  MemoryVerificationReport, ProceduralAntiDropProbeResult, VerificationHealthGrade,
  ZeroLexicalOverlapProbeResult

[POS]
Public facade of the self verification subsystem.
"""

from .runner import MemorySelfVerificationRunner
from .types import (
    FactMutationProbeResult,
    MemoryVerificationReport,
    ProceduralAntiDropProbeResult,
    VerificationHealthGrade,
    ZeroLexicalOverlapProbeResult,
)

__all__ = [
    "FactMutationProbeResult",
    "MemorySelfVerificationRunner",
    "MemoryVerificationReport",
    "ProceduralAntiDropProbeResult",
    "VerificationHealthGrade",
    "ZeroLexicalOverlapProbeResult",
]
