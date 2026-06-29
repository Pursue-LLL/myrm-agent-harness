# skills/

## Overview
Skill backend implementations — read/write/discovery protocols, local/memory/storage backends, lifecycle cache, security scanning integration, and permission helpers.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Public re-exports for skill backends, protocols, permissions, and decorators. | ✅ |
| _runtime.py | Internal | Builds runtime SkillMetadata from frontmatter plus computed fields. | ✅ |
| _utils.py | Internal | SKILL.md frontmatter parsing and shared parsing utilities. | ✅ |
| composite.py | Core | Routes skill requests across multiple backends with prefix-based fallback. | ✅ |
| config_version.py | Core | In-process skill config version counter for hot-reload polling (re-exported by server). | ✅ |
| creation_protocols.py | Core | SkillWriteBackend protocol and save/delete/write result types. | ✅ |
| credential_checker.py | Core | Optional DX helper for detecting missing skill credentials. | ✅ |
| credential_validator.py | Core | Validates skill credential files without full file_ops validators. | ✅ |
| discovery_protocols.py | Core | SkillDiscoveryBackend protocol and search/install result types. | ✅ |
| env_example_generator.py | Core | Generates .env.example snippets from skill env requirements. | ✅ |
| env_mapper.py | Core | Maps skill env declarations to runtime environment variables. | ✅ |
| factory.py | Core | SkillBackend factory for local, storage, memory, and composite backends. | ✅ |
| forgetting_strategy.py | Core | Curator forgetting strategies (pinned, evolution lock, grace, source-aware). | ✅ |
| instance_templates.py | Core | Predefined skill instance configuration templates. | ✅ |
| local.py | Core | Local filesystem skill backend; filters archived skills via lifecycle stats. | ✅ |
| memory.py | Core | In-memory skill backend for dynamic and MCP-generated skills. | ✅ |
| permission_templates.py | Core | Out-of-the-box permission templates for skill declarations. | ✅ |
| permission_validator.py | Core | Maps skill permissions to tool calls without user identity coupling. | ✅ |
| protocols.py | Core | SkillBackend protocol plus decorator store protocols (state, snapshot, A/B). | ✅ |
| scanning_write_backend.py | Core | Security-scanning wrapper around SkillWriteBackend implementations. | ✅ |
| similarity.py | Core | Protocol for detecting semantically similar skills. | ✅ |
| snapshot.py | Core | SQLite snapshot cache for O(N) skill metadata reads and incremental sync. | ✅ |
| watcher.py | Core | Watchdog-based SKILL.md hot reload with debounced snapshot updates. | ✅ |
| state_manager.py | Core | Skill instance CRUD, state persistence, config_overrides JSON Schema validation. | ✅ |
| stats_collector.py | Core | Skill usage stats and lifecycle_status / pinned persistence. | ✅ |
| storage.py | Core | Storage-backed skill backend (local/MinIO/S3/OSS via StorageBackend). | ✅ |
| types.py | Core | SkillMetadata, SkillTrust, SkillInstance, security scan types, visibility filter. | ✅ |
| versioning.py | Core | Semantic skill version comparison utilities. | ✅ |

| Submodule | Description |
|-----------|-------------|
| decorators/ | Version-aware and quarantine-aware SkillBackend decorators. See [decorators/_ARCH.md](decorators/_ARCH.md). |
| scanning/ | Static/AST/LLM skill content security scanning. See [scanning/_ARCH.md](scanning/_ARCH.md). |

## Key Dependencies

- `toolkits` (storage, shared exceptions)
- `utils` (crypto, db, coercion)
- `agent` (types.py, memory.py, scanning_write_backend.py import agent modules)
