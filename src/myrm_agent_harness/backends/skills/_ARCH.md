# skills/

## Overview
Skill backend implementations — read/write/discovery protocols, local/memory/storage backends, lifecycle cache, security scanning integration, and permission helpers.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Public re-exports for skill backends, protocols, permissions, and decorators. | ✅ |
| _runtime.py | Internal | Builds runtime SkillMetadata from frontmatter plus computed fields; `evaluate_requires` is the single dependency verdict (bins/env/config), counting caller-supplied env alongside the process environment, and is re-exported by `__init__.py`. | ✅ |
| _utils.py | Internal | SKILL.md frontmatter parsing and shared parsing utilities. | ✅ |
| composite.py | Core | Routes skill requests across multiple backends. A prefixed key (`/user/x`) goes to its route alone; any other key — the bare names and storage ids that `list_skills` returns — is offered to each backend in listing priority order (later routes first, default last) until one owns it, so every listed skill can be read, with its resources. | ✅ |
| config_version.py | Core | MYRM_DATA_DIR file-backed skill config version for hot-reload polling (re-exported by server). | ✅ |
| creation_protocols.py | Core | SkillWriteBackend protocol and save/delete/write result types. | ✅ |
| credentials/ | Core | Optional DX helpers for validating credentials and detecting missing skill secrets. | ✅ |
| prerequisites/ | Core | Skill runtime prerequisites contract, host system dependency sniffing (OS/binaries/Python), and cross-platform one-click remediation command generators. | ✅ |
| market_protocols.py | Core | SkillMarketBackend protocol and search/install result types. | ✅ |
| curator_config.py | Core | `CuratorConfig`: curator knobs, defaults and construction-time range validation (`ValueError` outside the safe ranges). | ✅ |
| forgetting_strategy.py | Core | Curator forgetting strategies (pinned, evolution lock, prebuilt/system, grace); installed-skill exemption is applied by the engine from the caller's `installed_names`. | ✅ |
| skill_doctor.py | Core | Skill library health report for the curator doctor: `evaluate_skill_health_findings` flags frequently failing skills (needs enough observed run outcomes), idle pinned skills and library bloat. Each finding carries a type code plus `details` parameters that the UI phrases itself; read-only, never changes lifecycle state. | ✅ |
| local.py | Core | Local filesystem skill backend; filters archived skills via lifecycle stats. | ✅ |
| memory.py | Core | In-memory skill backend for dynamic and MCP-generated skills. | ✅ |
| permission_templates.py | Core | Out-of-the-box permission templates for skill declarations. | ✅ |
| permission_validator.py | Core | Maps skill permissions to tool calls without user identity coupling. | ✅ |
| protocols.py | Core | SkillBackend protocol plus decorator store protocols (state, snapshot). | ✅ |
| similarity.py | Core | Protocol for detecting semantically similar skills. | ✅ |
| snapshot.py | Core | SQLite snapshot cache for O(N) skill metadata reads and incremental sync. | ✅ |
| watcher.py | Core | Watchdog-based SKILL.md hot reload with debounced snapshot updates. | ✅ |
| state_manager.py | Core | Skill instance CRUD, state persistence, config_overrides JSON Schema validation. | ✅ |
| stats_collector.py | Core | Skill usage stats (one use per run, outcome observed or unobserved) and lifecycle_status / pinned persistence; `reset_usage` opens a fresh success-rate window while keeping lifecycle/pin; stateless: every change (`record_use`, lifecycle/pin, `archive_merged`, `inherit_usage` for a merge or umbrella skill absorbing its sources) reads the ledger, modifies it and writes it back at once, and `get_stats` always reads from disk, so a ledger changed elsewhere is never overwritten from stale memory; a skill's first observation creates its ledger (anchors `created_at` for the forgetting grace period); atomic `.stats.json` writes, an unparseable ledger is kept as `.stats.json.corrupt`, an unreadable one is never replaced by a blank one. | ✅ |
| usage_recorder.py | Core | Run-scoped skill usage: selections and attributed tool outcomes fold into one `.stats.json` use per skill at run end and are on disk when `commit_skill_run_usage` returns; `set_stats_collector` SSOT with server. | ✅ |
| storage.py | Core | Storage-backed skill backend that loads skills from any StorageProvider. | ✅ |
| types/（子包） | Core | Skill 系统数据类型域。稳定公共入口 `backends.skills.types`（import path 不变，解析到子包门面）。9 个 `types_*` 实现模块聚合于此，`types/__init__.py` 为聚合门面统一 re-export（SkillContract* / enums / SkillMetadata / SkillInstance* / SkillRequires / MCPSkillData / Security* / SkillUsageStats / skill_visible_for_tools / coercion） | ✅ |
| versioning.py | Core | Semantic skill version comparison, bump classification, and downgrade guardrail validation. | ✅ |
| local_skill_id.py | Core | Canonical path-hash local skill ID + install dir resolution. | ✅ |
| credential_checker.py | Core | Credential expiry checker for JWT/OAuth tokens (`ExpiryStatus`, `ExpiryResult`, `CredentialExpiryChecker`). | ✅ |
| credential_validator.py | Core | Credential file validator — workspace boundary checks for skill credentials (`CredentialValidationResult`, `CredentialValidator`). | ✅ |
| workflow_compiler.py | Core | Desktop/multi-app workflow plan data structures and SKILL.md compiler. | ✅ |

| Submodule | Description |
|-----------|-------------|
| decorators/ | Version-aware and quarantine-aware SkillBackend decorators. See [decorators/_ARCH.md](decorators/_ARCH.md). |
| scanning/ | Static/AST/LLM skill content security scanning. See [scanning/_ARCH.md](scanning/_ARCH.md). |

## Key Dependencies

- `toolkits` (storage, shared exceptions)
- `utils` (crypto, db, coercion)
- `infra` (atomic_write for config_version persistence)
- `core` (hooks types for SkillMetadata hook fields)
