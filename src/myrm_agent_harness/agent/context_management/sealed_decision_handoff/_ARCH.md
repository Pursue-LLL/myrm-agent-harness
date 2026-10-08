# sealed_decision_handoff/

## Overview
End-to-end cryptographic sealed decision handoff, pre-seal credential masking, decision invalidation graph, and sovereign storage persistence subsystem. Replaces lossy summaries by carrying decisions themselves across agents and models, redacts sensitive API keys and tokens before sealing, maintains active/revoked/superseded decision lineage to prevent reviving dead paths, enforces AES-256-GCM authenticated encryption with SHA-256 dual verification, and anchors contexts with immutable pointer chains.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Package facade exporting sealed decision types, secret masker, invalidation graph, seal packer, storage driver, and facade suite. | — |
| sealed_decision_types.py | Types | Strongly typed data structures for decision nodes, negative invariants, sealed receipts, handoff decision packages, sanity reports, and domain errors. | ✅ |
| secret_masker.py | Security | Pre-seal credential redactor, pattern scanner, and scoped environment variable pruner. | ✅ |
| decision_invalidation_graph.py | Lineage | Decision revision lineage manager, active resolution, negative invariant extractor, and cycle checker. | ✅ |
| decision_seal_packer.py | Crypto | AES-256-GCM AEAD seal packer and in-memory pipe hydrator enforcing key-in-pipe custody and SHA-256 digest checks. | ✅ |
| storage_driver.py | Storage | Sovereign storage driver abstraction and sandbox volume persistence with immutable pointer chains. | ✅ |
| sealed_decision_suite.py | Facade | Unified facade suite coordinating secret masking, decision graph reconciliation, cryptographic packing, and provable first-run loops. | ✅ |

## Key Dependencies

- stdlib: `pathlib`, `json`, `dataclasses`, `datetime`, `hashlib`, `re`, `os`, `typing`
- External: `cryptography.hazmat.primitives.ciphers.aead.AESGCM`
- Internal: `myrm_agent_harness.agent.context_management`
