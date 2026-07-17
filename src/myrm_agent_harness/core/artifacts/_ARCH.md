# core/artifacts/

## Overview
Framework-agnostic artifact type constants and mappings. Provides ArtifactType enum, extension/MIME-to-type inference, and content classification utilities.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports all artifact constants and utility functions. | ✅ |
| constants.py | Core | ArtifactType enum (code/document/html/pdf/image/svg/mermaid/audio/video/spreadsheet/presentation/word_document/binary/react), extension-to-language/artifact-type mappings, MIME mappings, content classification (is_active_content, is_text_content), inference utilities. | ✅ |
| paths.py | Core | Framework-agnostic workspace artifact vault path resolution (`{workspace}/.agent/vault` by default; override via `AGENT_WORKSPACE_VAULT_RELATIVE`). | ✅ |

## Key Dependencies

- No internal dependencies (foundation layer)
