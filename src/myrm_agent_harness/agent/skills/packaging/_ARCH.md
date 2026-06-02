# packaging/

## Overview
Skills Packaging module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package |   Init   | — |
| packer.py | Core | Provides PackageResult, SkillPacker. | ✅ |
| unpacker.py | Core | Provides UnpackResult, SkillUnpacker. | ✅ |
| validator.py | Core | Provides SkillPackageInfo, suggest_valid_skill_name, is_forbidden_file. | ✅ |

## Key Dependencies

- `agent`
- `backends`
