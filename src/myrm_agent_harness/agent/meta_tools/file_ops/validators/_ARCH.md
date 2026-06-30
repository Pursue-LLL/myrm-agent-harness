# validators/

## Overview
Validators module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Validators module. | — |
| auto_verify.py | Core | Smart Auto-Verify. Infers and runs CLI linters after file edits when Agent does not provide explicit verify_command. Provides soft diagnostic feedback. | ✅ |
| base.py | Core | Provides Validator. | ✅ |
| binary_validator.py | Core | Binary file validator | ✅ |
| config_protection_validator.py | Core | Config protection validator. Blocks agent modifications to existing linter/formatter config files, forcing code fixes over config weakening. | ✅ |
| delta_syntax_validator.py | Core | In-memory delta syntax validator. Zero-overhead syntax checking for structural languages. | ✅ |
| invariant_validator.py | Core | Goal-scoped invariant file protection: blocks writes matching active Goal protected_paths before they happen. | ✅ |
| path_validator.py | Core | Path security validator with symlink detection and actionable error hints for LLM self-correction. | ✅ |
| permission_validator.py | Core | Provides PermissionValidator. | ✅ |
| sensitive_file_validator.py | Core | Sensitive file validator | ✅ |
| size_validator.py | Core | Provides SizeValidator. | ✅ |
| validator_chain.py | Core | Provides ValidatorChain. | ✅ |
