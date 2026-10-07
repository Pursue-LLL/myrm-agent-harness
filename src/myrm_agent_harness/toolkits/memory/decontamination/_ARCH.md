# Memory Provenance Attestation and Decontamination Architecture

## Overview
This package implements the Memory Provenance Attestation, Active Decontamination Quarantine, and Point-in-time Snapshot Rollback Suite (Item 76). It addresses memory poisoning, prompt injection contamination, and irreversible memory corruption by establishing cryptographic provenance vouchers, heuristic quarantine barriers, and session-scoped rollback capabilities.

## Core Modules
- `models.py`: Strongly typed primitives (`ProvenanceSourceKind`, `DecontaminationStatus`, `MemoryProvenanceAttestation`, `MemorySnapshotRecord`, `DecontaminationReport`, `RollbackReport`).
- `attestation.py`: `ProvenanceAttestationManager` generating tamper-evident SHA-256 origin vouchers and tracking turn evidence.
- `detector.py`: `DecontaminationGuard` scanning injection/destructive patterns and enforcing retrieval quarantine barriers.
- `rollback.py`: `MemorySnapshotRollbackEngine` creating memory checkpoints, rolling back across versions, and purging corrupted sessions.
- `service.py`: `MemoryProvenanceDecontaminationService` unified facade integrating attestation, quarantine, and rollback engines.
- `__init__.py`: Public package exports conforming to harness conventions.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Package facade for decontamination. | ✅ |
| `attestation.py` | Core | Manages generation, signature verification, and indexing of memory provenance attestations. | ✅ |
| `detector.py` | Core | Active detector and quarantine gate preventing poisoned memories from polluting context. | ✅ |
| `models.py` | Types | Types and models for decontamination. | ✅ |
| `rollback.py` | Core | Manages memory snapshots, version time travel, and session-scoped decontamination rollbacks. | ✅ |
| `service.py` | Core | Unified service coordinating memory provenance certification, quarantine, and rollbacks. | ✅ |
