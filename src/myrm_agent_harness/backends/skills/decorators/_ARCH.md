# decorators/

## Overview
SkillBackend decorator proxies — version routing (A/B tests) and quarantine filtering without mutating filesystem skill sources.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports decorator backends | — |
| version_aware.py | Core | VersionAwareSkillBackend — A/B routing and snapshot serving | baseline |
| quarantine_aware.py | Core | QuarantineAwareSkillBackend — filters inactive skills at runtime | baseline |

## Module Dependencies

- `backends.skills.protocols::SkillBackend`, `ABTestStoreProtocol`, `SnapshotStoreProtocol`, `SkillStateReader`
