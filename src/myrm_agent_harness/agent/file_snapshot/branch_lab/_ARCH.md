# branch_lab/

## Overview
Sandbox zero-copy branch lab and rollout promotion subsystem. Enables multi-agent parallel exploration from any base snapshot point with copy-on-write sparse overlays, deduplicated content-addressed storage (CAS), zero-cost discarding of failed branches, and atomic promotion of winning branches into main workspace timelines.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Exports all branch lab types, overlay, manager, and suite facade. | ✅ |
| `branch_types.py` | Types | Data types, mutation categories, diff summaries, and immutable receipts. | ✅ |
| `branch_cas_overlay.py` | Storage | Content-addressed deduplicated storage with copy-on-write sparse overlays. | ✅ |
| `zero_copy_branch_manager.py` | Manager | Branch lifecycle management: fork, record mutation, diff, discard, promote. | ✅ |
| `sandbox_branch_lab_suite.py` | Facade | High-level facade for parallel rollout exploration, scoring, and promotion. | ✅ |

## Key Dependencies

- `hashlib`, `time`, `uuid`, `pathlib`, `logging`
- Local sibling modules in `agent/file_snapshot/`

## Key Design Decisions

- **Zero-Copy Branch Forking**: Forking a branch takes O(1) constant time without duplicating workspace directories; initial delta storage is strictly zero.
- **Content-Addressed Storage (CAS)**: File contents across branches are deduplicated by SHA-256 hash, avoiding redundant physical allocations when multiple candidate branches test similar changes.
- **Copy-on-Write (COW) Overlay**: Only modified, added, or deleted files are tracked in per-branch overlays, keeping memory and disk footprints minimal.
- **Zero-Cost Discard**: Discarding a failed branch instantly purges its overlay mutations and reclaims physical delta bytes without polluting the main snapshot timeline.
- **Atomic Promotion**: Promoting a winning branch merges its overlay mutations into the target workspace directory and records an immutable benchmark receipt.
- **Benchmark Receipt Contract**: Conforms to LayerFS-inspired audit contracts, producing deterministic SHA-256 receipt fingerprints with explicit PASS/FAIL/DISCARDED/PROMOTED verdicts and timing data.
