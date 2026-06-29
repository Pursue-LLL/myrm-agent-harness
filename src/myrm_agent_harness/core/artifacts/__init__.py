"""Core artifact types — framework-agnostic artifact constants and mappings.

Re-exports ArtifactType and related utility functions/mappings.
The artifact *registry* (runtime) remains in ``agent.artifacts``.
"""

from myrm_agent_harness.core.artifacts.constants import (
    ACTIVE_CONTENT_MIME_TYPES,
    EXTENSION_TO_ARTIFACT_TYPE,
    EXTENSION_TO_LANGUAGE,
    ArtifactMappings,
    ArtifactType,
    get_all_mappings,
    infer_artifact_type_from_extension,
    infer_artifact_type_from_mime,
    infer_language_from_extension,
    is_active_content,
    is_text_content,
)
from myrm_agent_harness.core.artifacts.paths import (
    ARTIFACT_VAULT_DIR_NAME,
    WORKSPACE_AGENT_DIR_NAME,
    resolve_workspace_artifact_vault_dir,
    workspace_vault_relative_parts,
)

__all__ = [
    "ARTIFACT_VAULT_DIR_NAME",
    "WORKSPACE_AGENT_DIR_NAME",
    "ACTIVE_CONTENT_MIME_TYPES",
    "EXTENSION_TO_ARTIFACT_TYPE",
    "EXTENSION_TO_LANGUAGE",
    "ArtifactMappings",
    "ArtifactType",
    "get_all_mappings",
    "infer_artifact_type_from_extension",
    "infer_artifact_type_from_mime",
    "infer_language_from_extension",
    "is_active_content",
    "is_text_content",
    "resolve_workspace_artifact_vault_dir",
    "workspace_vault_relative_parts",
]
