# skills/

## Overview
Skill backend implementations module. Provides multiple backend implementations and three core protocols for loading skills from various sources.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Skill backend implementations module. Provides multiple backend implementations and three core proto | ✅ |
| _runtime.py | Internal | Skill runtime builder. Constructs runtime metadata from static frontmatter data and runtime-computed | ✅ |
| _utils.py | Internal | Skill backend parsing utilities. Provides SKILL.md frontmatter parsing functionality. | ✅ |
| composite.py | Core | Composite skill backend. Routes requests to different backends based on skill name prefix with defau | ✅ |
| creation_protocols.py | Core | Skill write-backend protocol. Defines unified interface for creating, updating, and deleting skills  | ✅ |
| credential_checker.py | Core | Optional enhancement for developer experience. Not required for core | ✅ |
| credential_validator.py | Core | Dedicated validator for credential files. Simpler than full file_ops validators | ✅ |
| discovery_protocols.py | Core | Skill discovery backend protocol. Defines unified interface for searching and installing external sk | ✅ |
| env_example_generator.py | Core | Developer experience enhancement. Provides clear documentation of required | ✅ |
| env_mapper.py | Core | Lightweight mapper for developer experience. Enables skills to work without | ✅ |
| factory.py | Core | Skill backend factory. Provides convenient factory methods for creating various backends (local, sto | ✅ |
| forgetting_strategy.py | Core | Skill forgetting / curator strategies. CuratorConfig, ForgettingReason (with target_status), DefaultForgettingStrategy (pinned/evolution_locked/grace/source-aware). | ✅ |
| instance_templates.py | Core | Skill instance templates for quick setup. | ✅ |
| local.py | Core | Local skill backend. Loads skills from local paths. Filters archived skills via .stats.json lifecycle_status. | ✅ |
| memory.py | Core | In-memory skill backend. Stores skill metadata in memory without persistence. | ✅ |
| permission_templates.py | Core | Framework-layer permission templates that provide out-of-the-box permission | ✅ |
| permission_validator.py | Core | Framework-layer permission mapping for skills. Does NOT depend on user identity | ✅ |
| protocols.py | Core | Skill backend protocol + decorator dependency protocols (SkillStateReader, SnapshotStoreProtocol, ABTestStoreProtocol). | ✅ |
| scanning_write_backend.py | Core | Framework-level security wrapper for SkillWriteBackend. | ✅ |
| similarity.py | Core | Skill similarity checking protocol. Defines interface for detecting semantically similar skills to prevent entropy. | ✅ |
| snapshot.py | Core | SQLite-based skill snapshot cache with O(N) read and O(1) incremental sync. Provides fast skill metadata loading by avoiding repeated file I/O and frontmatter parsing. Supports WAL mode for better read concurrency. Performance: 1.27x faster than filesystem scan with full parsing at 200 skills scale. | ✅ |
| watcher.py | Core | File system monitoring for automatic skill hot reload. Uses watchdog library to detect SKILL.md creation, modification, and deletion. Automatically triggers incremental snapshot updates with debouncing support to handle rapid consecutive changes. | ✅ |
| state_manager.py | Core | Skill state and instance manager. Handles instance configuration CRUD, automatic state persistence, and lightweight JSON Schema validation for config_overrides. | ✅ |
| stats_collector.py | Core | Skill usage statistics and lifecycle state collector. Reads/writes lifecycle_status + pinned. | ✅ |
| storage.py | Core | Storage skill backend. Loads skills from any StorageBackend implementation (local/MinIO/S3/OSS). | ✅ |
| types.py | Core | Skill system core data types. SkillLifecycleStatus, SkillTrust, SkillUsageStats, SkillMetadata (incl. tool-based conditional activation fields), skill_visible_for_tools() pure filter. | ✅ |
| versioning.py | Core | Skill version comparison utilities. | ✅ |

| Submodule | Description |
|-----------|-------------|
| decorators/ | Skill backend decorators (quarantine-aware, version-aware). See [decorators/_ARCH.md](decorators/_ARCH.md). |
| scanning/ | Skill content security scanning subsystem. |

## Key Dependencies

- `agent`
- `toolkits`
