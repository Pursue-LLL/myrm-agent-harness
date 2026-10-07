"""Instructions ingestion and hierarchical scoping subpackage.

[INPUT]
- agent.context_management.instructions.project_instruction_types::DiscoveredInstructionFile,
  InstructionPriorityTier, ProjectInstructionConfig, ProjectInstructionIngestResult (POS: Data types and
  schemas for workspace project instruction auto-ingestion.)
- agent.context_management.instructions.upward_instruction_types::EcosystemPriority, InstructionEcosystem,
  LegacySkillsDirectory, ScannedInstructionFile, UpwardResolutionResult (POS: Types and models for upward
  instruction.)
- agent.context_management.instructions.upward_project_instruction_resolver::UpwardProjectInstructionResolver
  (POS: Recursively resolves project instructions upward along directory tree and claims legacy skills.)
-
  agent.context_management.instructions.workspace_project_instruction_ingestor::WorkspaceProjectInstructionAutoIngestor
  (POS: Workspace project instruction auto-ingestion and hierarchical merger engine.)

[OUTPUT]
- Re-exports: DiscoveredInstructionFile, EcosystemPriority, InstructionEcosystem, InstructionPriorityTier,
  LegacySkillsDirectory, ProjectInstructionConfig, ProjectInstructionIngestResult, ScannedInstructionFile,
  UpwardProjectInstructionResolver, UpwardResolutionResult, WorkspaceProjectInstructionAutoIngestor

[POS]
Instructions ingestion and hierarchical scoping subpackage.
"""

from .project_instruction_types import (
    DiscoveredInstructionFile,
    InstructionPriorityTier,
    ProjectInstructionConfig,
    ProjectInstructionIngestResult,
)
from .upward_instruction_types import (
    EcosystemPriority,
    InstructionEcosystem,
    LegacySkillsDirectory,
    ScannedInstructionFile,
    UpwardResolutionResult,
)
from .upward_project_instruction_resolver import (
    UpwardProjectInstructionResolver,
)
from .workspace_project_instruction_ingestor import (
    WorkspaceProjectInstructionAutoIngestor,
)

__all__ = [
    "DiscoveredInstructionFile",
    "EcosystemPriority",
    "InstructionEcosystem",
    "InstructionPriorityTier",
    "LegacySkillsDirectory",
    "ProjectInstructionConfig",
    "ProjectInstructionIngestResult",
    "ScannedInstructionFile",
    "UpwardProjectInstructionResolver",
    "UpwardResolutionResult",
    "WorkspaceProjectInstructionAutoIngestor",
]
