# core/artifacts/

## Overview
Framework-agnostic artifact type constants and mappings. Provides ArtifactType enum, extension/MIME-to-type inference, and content classification utilities.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports all artifact constants and utility functions. | ✅ |
| constants.py | Core | ArtifactType enum (code/document/html/pdf/image/svg/mermaid/audio/video/binary/spreadsheet), extension-to-language/artifact-type mappings, MIME mappings, content classification (is_active_content, is_text_content), inference utilities. | ✅ |

## Key Dependencies

- No internal dependencies (foundation layer)
