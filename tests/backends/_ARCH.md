# tests/backends/

## Overview

Tests mirroring `src/myrm_agent_harness/backends/` — profiles, secrets, and skills storage adapters.

## Submodule Index

| Path | Coverage |
|------|----------|
| `skills/` | Skill backend protocols, factory, snapshot, scanning, decorators, `config_version` Volume persistence |
| `skills/scanning/` | Static/AST/LLM skill security scanners |
| `skills/decorators/` | Version-aware and quarantine-aware decorators |
| Root `test_*.py` | Cross-cutting backends (profiles, secrets, watcher, snapshot performance) |

## Key test files

| File | Role |
|------|------|
| `skills/test_config_version.py` | `MYRM_DATA_DIR/.skill_config_version` bump/get, corrupt-file fallback + WARNING log |
| `test_watcher.py` | SkillWatcher debounced snapshot updates |
| `test_snapshot.py` | SQLite skill snapshot CRUD |

## Key Dependencies

- Design reference: [backends/_ARCH.md](../../src/myrm_agent_harness/backends/_ARCH.md)
- Skills module: [skills/_ARCH.md](../../src/myrm_agent_harness/backends/skills/_ARCH.md)
