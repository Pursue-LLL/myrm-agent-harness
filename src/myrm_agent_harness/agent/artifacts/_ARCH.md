# artifacts/

## Overview
Artifacts system — artifact lifecycle management.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Artifacts system — artifact lifecycle management. | — |
| constants.py | Core | Provides ArtifactType, ArtifactMappings, is_active_content. | ✅ |
| context.py | Core | Provides ArtifactContext, ArtifactContextManager, get_artifact_context. | ✅ |
| file_id_registry.py | Core | Short `@file_*` ID registry; `register_file` + `lookup_short_file_id` for SSE `short_file_id`. | ✅ |
| filters.py | Core | File filtering rules for artifact collection. | ✅ |
| registry.py | Core | Provides GeneratedFile, ArtifactRegistry, RealtimeContentEvent. | ✅ |
| types.py | Config | Provides ArtifactInfo, infer_language, infer_artifact_type. | ✅ |
| ui_artifact.py | Core | Provides UIComponentType, UIComponent, UIAction. | ✅ |
| ui_registry.py | Core | Provides UIRegistry, get_ui_registry, register_ui_artifact, register_ui_data_update. | ✅ |
| bundle_manifest.py | Core | Provides DeliverableManifest, DeliverableItem, DeliverableCategory, DeliverableStatus for bundle packaging. | ✅ |
| reconciler.py | Core | Physical disk artifact reconciliation and verification engine; extracts and verifies existing file paths from tool outputs and registers them into ArtifactRegistry. | ✅ |
| vault.py | Core | Shared Artifact Vault — `vault://` store under `{workspace}/.agent/vault`; consumed by subagent auto-vault, file_read_tool, artifact listener, Kanban content_ref | ✅ |
