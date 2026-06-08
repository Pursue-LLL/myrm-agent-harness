# decorators/

## Overview
SkillBackend decorator proxies — version routing (A/B tests) and quarantine filtering without mutating filesystem skill sources.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports decorator backends | — |
| version_aware.py | Core | VersionAwareSkillBackend — A/B routing and snapshot serving | — |
| quarantine_aware.py | Core | QuarantineAwareSkillBackend — filters `is_active=False` skills at runtime | — |

## Module Dependencies

- `backends.skills.protocols::SkillBackend`, `ABTestStoreProtocol`, `SnapshotStoreProtocol`, `SkillStateReader`
