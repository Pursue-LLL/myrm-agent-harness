# packaging/

## Overview
Skills Packaging module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package |   Init   | — |
| packer.py | Core | Provides PackageResult, SkillPacker. | ✅ |
| unpacker.py | Core | Provides UnpackResult, SkillUnpacker. | ✅ |
| validator.py | Core | ZIP package validation with root checks, forbidden-file filtering, and archive-security contract (entry-limit + executable-binary rejection). | ✅ |

## Key Dependencies

- `agent`
- `backends`
