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
| markdown_vault_write_guard.py | Core | Preserves YAML frontmatter on vault `.md` writes; pairs with vault_scope + FormatObserver skip | ✅ |
| office_bash_audit.py | Core | Post-bash Office fidelity audit (OPC metrics, xlsx formulas, layout QA, recalc, baseline-missing honest warn, corrupt-file read warn) | ✅ |
| office_write_guard.py | Core | Secondary guard: warn on direct text writes to Office binary paths | ✅ |
| invariant_validator.py | Core | Goal-scoped invariant file protection: blocks writes matching active Goal protected_paths before they happen. | ✅ |
| path_validator.py | Core | Path security validator with symlink detection and actionable error hints for LLM self-correction. | ✅ |
| permission_validator.py | Core | Provides PermissionValidator. | ✅ |
| sensitive_file_validator.py | Core | Sensitive file validator | ✅ |
| size_validator.py | Core | Provides SizeValidator. | ✅ |
| validator_chain.py | Core | Provides ValidatorChain. | ✅ |

## Tests

- `tests/agent/meta_tools/file_ops/validators/test_delta_syntax_validator.py`
- `tests/agent/meta_tools/file_ops/validators/test_markdown_vault_write_guard.py`
- `tests/agent/meta_tools/file_ops/validators/test_office_bash_audit.py`
- `tests/agent/meta_tools/file_ops/validators/test_office_write_guard.py`
- `tests/agent/meta_tools/file_ops/validators/test_office_golden_opc.py`
- `tests/utils/test_markdown_frontmatter.py`
- `tests/agent/meta_tools/file_ops/utils/test_vault_scope.py`
