# tests/agent/skills/

## Overview

Tests mirroring `src/myrm_agent_harness/agent/skills/` layout.

## Submodule Index

| Path | Coverage |
|------|----------|
| `discovery/` | Aliyun/ModelScope sources + batch installers |
| `sync/` | Manifest (`test_sync_manifest.py`), manager (`test_sync_manager.py`), quality gate, integration (`test_skill_sync.py`) |
| `evolution/` | Skill evolution pipeline components |
| `curator/` | SkillCurator lifecycle + consolidation |
| `optimization/` | Batch executor, scheduler, observability |
| `packaging/` | Skill pack/unpack/validate |
| `mcp/` | MCP session store + notify |
| `history/` | JSONL / tracking backends |
| Root `test_*.py` | Cross-cutting skill utilities (sanitizer, discovery service, fallback) |

## Key Dependencies

- Design reference: [SKILL_SYSTEM_DESIGN.md](../../../src/myrm_agent_harness/agent/skills/SKILL_SYSTEM_DESIGN.md)
