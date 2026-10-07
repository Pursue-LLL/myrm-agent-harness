# Memory Tombstone and Outdated Directive Curation Architecture

## 1. Positioning and Boundaries
The `tombstone` module in `myrm-agent-harness` provides proactive memory curation, antithetical contradiction detection, and tombstone lifecycle management.

- **Antithetical Contradiction Detection**: Proactively detects mutual exclusions and polarity conflicts (e.g. "prefer X" vs "avoid X") between new and old directives, adjudicating the older entry as superseded.
- **Tombstone Masking Gate**: Hard recall barrier ensuring tombstoned and evicted entries are strictly filtered out before prompt assembly, preventing LLM cognitive conflict.
- **Revival & Eviction Lifecycle**: Allows users to reverse tombstoning (`revived`) or physically evict (`evicted`) expired entries.
- **Single-Machine Sandbox**: SQLite audit table maintained locally without multi-tenant baggage.

## 2. Component Structure
- `models.py`: Domain models (`TombstoneState`, `ContradictionPair`, `TombstoneCandidateItem`, `TombstoneAuditRecord`, `TombstoneCurationReport`).
- `detector.py`: Heuristic and antithetical matrix contradiction detector with temporal adjudication.
- `service.py`: SQLite-backed orchestration service for curation, filtering, revival, and eviction.
- `tools.py`: Agent-callable meta-tools for proactive curation and memory lifecycle operations.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Package facade for tombstone. | ✅ |
| `detector.py` | Core | Scans memory entries for mutual exclusions, negative polarity reversals, and outdated directives. | ✅ |
| `models.py` | Types | Types and models for tombstone. | ✅ |
| `service.py` | Core | Orchestrates memory contradiction detection, tombstone isolation, revival, and eviction. | ✅ |
| `tools.py` | Core | Agent meta-tools for proactive directive curation, tombstone masking, and memory revival. | ✅ |
