# artifacts/

## Overview
Artifacts system — artifact lifecycle management.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Artifacts system — artifact lifecycle management. | — |
| constants.py | Core | Provides ArtifactType, ArtifactMappings, is_active_content. | ✅ |
| context.py | Core | Provides ArtifactContext, ArtifactContextManager, get_artifact_context. | ✅ |
| file_id_registry.py | Core | Example: | ✅ |
| filters.py | Core | File filtering rules for artifact collection. | ✅ |
| registry.py | Core | Provides GeneratedFile, ArtifactRegistry, RealtimeContentEvent. | ✅ |
| types.py | Config | Provides ArtifactInfo, infer_language, infer_artifact_type. | ✅ |
| ui_artifact.py | Core | Provides UIComponentType, UIComponent, UIAction. | ✅ |
| ui_registry.py | Core | Provides UIRegistry, get_ui_registry. | ✅ |
| vault.py | Core | Shared Artifact Vault — `vault://` zero-copy store under `{workspace}/.agent/vault` via `core.artifacts.paths` | ✅ |
