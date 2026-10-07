"""Instructions ingestion and hierarchical scoping subpackage."""

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
