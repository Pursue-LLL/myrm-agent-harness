# workspace_trust/

## 架构概述

Folder bind trust + side-channel execution control. Harness owns gate logic and run-scoped ContextVars; server owns UserConfig persistence and REST API (`/security/workspace-trust/*`).

详细设计见 [SECURITY_SYSTEM.md](../SECURITY_SYSTEM.md)（Workspace Trust 节，待补全）。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|------|------|------|-------|
| `types.py` | Core | `WorkspaceTrustLevel`、`WorkspaceTrustManifest`、`WorkspaceTrustEntry` | ✅ |
| `manifest.py` | Core | Pre-bind disclosure builder + `manifest_hash` | ✅ |
| `gate.py` | Core | Side-channel block helpers（skills/rules/MCP spawn/repo prefix match） | ✅ |
| `errors.py` | Core | `WorkspaceTrustBlockedError` for MCP spawn and side-channel blocks | ✅ |
| `context.py` | Core | ContextVar：trust level + repo command prefixes | ✅ |
| `protocol.py` | Core | `WorkspaceTrustLookup` protocol（server 注入） | ✅ |
| `provider.py` | Core | Lookup registry；`resolve_workspace_trust_level`（unknown → RESTRICTED） | ✅ |
| `runtime.py` | Core | `apply_workspace_trust_for_root` / `clear_workspace_trust_runtime`（run lifecycle） | ✅ |
| `repo_policy.py` | Core | `.myrm/config.toml` command prefix loader | ✅ |
| `__init__.py` | Package | Public exports | ✅ |

## 边界

- 位于 `agent/security/workspace_trust/`，**非** `toolkits/`，**非** meta-tool。
- Control plane 层：**零改动**。
