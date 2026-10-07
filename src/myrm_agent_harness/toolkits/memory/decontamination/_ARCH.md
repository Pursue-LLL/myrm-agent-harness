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
