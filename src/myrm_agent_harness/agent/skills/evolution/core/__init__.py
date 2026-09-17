"""Public surface of the skill evolution core package.

[INPUT]
- agent.skills.evolution.core.gene_bank::GeneBankArchive
  (POS: MAP-Elites 质量-多样性精英存档层)
- agent.skills.evolution.core.types::EvolutionLayer, EvolutionProposal, EvolutionRequest,
  EvolutionType, ExecutionAnalysis, FailurePathology, GeneCellKey, GeneEliteRecord,
  SkillLineage, SkillMetrics, SkillRecord, SkillVerificationType, VerificationProof
  (POS: 技能演化数据契约层)

[OUTPUT]
- GeneBankArchive plus the evolution proposal/analysis/lineage type contracts

[POS]
Public surface of the skill evolution core. Import from here rather than from the internal
modules so the archive layout can evolve without breaking callers.
"""

from myrm_agent_harness.agent.skills.evolution.core.gene_bank import GeneBankArchive
from myrm_agent_harness.agent.skills.evolution.core.types import (
    EvolutionLayer,
    EvolutionProposal,
    EvolutionRequest,
    EvolutionType,
    ExecutionAnalysis,
    FailurePathology,
    GeneCellKey,
    GeneEliteRecord,
    SkillLineage,
    SkillMetrics,
    SkillRecord,
    SkillVerificationType,
    VerificationProof,
)

__all__ = [
    "EvolutionLayer",
    "EvolutionProposal",
    "EvolutionRequest",
    "EvolutionType",
    "ExecutionAnalysis",
    "FailurePathology",
    "GeneBankArchive",
    "GeneCellKey",
    "GeneEliteRecord",
    "SkillLineage",
    "SkillMetrics",
    "SkillRecord",
    "SkillVerificationType",
    "VerificationProof",
]
