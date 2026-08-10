# tests/agent/skills/

## Overview

Tests mirroring `src/myrm_agent_harness/agent/skills/` layout.

## Submodule Index

| Path | Coverage |
|------|----------|
| `market/` | Market sources (Aliyun/ModelScope) + batch installers + BaseSkillMarketService |
| `sync/` | Manifest (`test_sync_manifest.py`), manager (`test_sync_manager.py`), quality gate, integration (`test_skill_sync.py`) |
| `evolution/` | Skill evolution pipeline components |
| `curator/` | SkillCurator lifecycle + consolidation |
| `optimization/` | Batch executor, scheduler, observability |
| `packaging/` | Skill pack/unpack/validate |
| `mcp/` | MCP proxy validation, tool name SSOT, session store + notify · `test_proxy_service.py` · `test_tool_name_utils.py` · `test_proxy_validation.py` |
| `history/` | JSONL / tracking backends |
| `runtime/` | Command path rewriting + skill script detection (`test_command_paths.py`), catalog delivery (`test_skill_catalog_delivery.py`), registry MCP lifecycle (`test_registry_mcp_lifecycle.py`) |
| Root `test_*.py` | Cross-cutting skill utilities (sanitizer, discovery service, fallback) |

## Key Dependencies

- Design reference: [SKILL_SYSTEM.md](../../../src/myrm_agent_harness/agent/skills/SKILL_SYSTEM.md)
