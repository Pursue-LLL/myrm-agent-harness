# integration_purge/

## Overview

Integration retained context purge and provenance revocation package. Exports for connector-scoped context retention auditing, GDPR/Privacy-grade selective purge, and cryptographic provenance invalidation (Topic 01 Item 179).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Integration retained context purge and provenance revocation package — Exports for connector-scoped context retention auditing, GDPR/Privacy-grade selective purge, and cryptographic provenance invalidation (Topic 01 Item 179). | ✅ |
| manager.py | Core | Manager for inspecting and purging integration retained context and revoking provenance — Harness-level engine orchestrating transparent retained memory accounting, connector-scoped deletion cascades, and provenance revocation state tracking. | ✅ |
| tool.py | Core | Agent runtime tool factory for integration retained context governance and purge — Agent runtime surface enabling autonomous inspection and privacy-compliant purging of connector-scoped context when integrations are disconnected or revoked. | ✅ |
| types.py | Core | Types and data contracts for integration retained context purge and provenance revocation — Core contracts for connector-scoped context retention auditing, GDPR/Privacy-grade selective purge, and cryptographic provenance invalidation (Topic 01 Item 179). | ✅ |
