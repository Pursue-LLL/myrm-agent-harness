"""Instructions ingestion and hierarchical scoping subpackage."""

from .project_instruction_types import (
    DiscoveredInstructionFile,
    InstructionPriorityTier,
    ProjectInstructionConfig,
    ProjectInstructionIngestResult,
)
from .workspace_project_instruction_ingestor import (
    WorkspaceProjectInstructionAutoIngestor,
)

__all__ = [
    "DiscoveredInstructionFile",
    "InstructionPriorityTier",
    "ProjectInstructionConfig",
    "ProjectInstructionIngestResult",
    "WorkspaceProjectInstructionAutoIngestor",
]
