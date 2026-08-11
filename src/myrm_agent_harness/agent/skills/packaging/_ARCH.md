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
| evals.py | Core | `eval_cases` ↔ `evals.json` 纯序列化/校验原语（带 schema_version），供 server 导出/导入侧复用。 | ✅ |

## Key Dependencies

- `agent`
- `backends`
