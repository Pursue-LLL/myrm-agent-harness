# zero_lockin_portability/

## Overview
Zero-Lockin universal context portability and cross-platform memory hydration subsystem. Provides open-standard context archive specification, adaptive ingestion and normalization for commercial exports (ChatGPT, Claude Web, Instinct, TypingMind), offline memory profile and entity fact hydration, bilateral sovereignty export, and portability health auditing.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Package facade exporting portability types, engines, and BilateralSovereigntyArchiveHub suite. | — |
| portability_types.py | Types | Strongly typed data structures for universal archive manifests, session trees, memory facts, user profiles, and portability badges. | ✅ |
| universal_archive_spec.py | Core | Canonical serialization, deserialization, and deterministic SHA-256 integrity verification engine for zero-lockin archives. | ✅ |
| cross_platform_transcript_normalizer.py | Core | Adaptive parser and normalizer converting heterogeneous export schemas (ChatGPT, Claude Web, generic) into canonical trees. | ✅ |
| offline_memory_hydration_engine.py | Core | Offline rule-based heuristic and entity extraction engine generating long-term memory facts and structured profiles. | ✅ |
| bilateral_sovereignty_hub.py | Facade | Unified bilateral sovereignty hub providing end-to-end import, export, and portability health auditing. | ✅ |

## Key Dependencies

- stdlib: `time`, `hashlib`, `uuid`, `json`, `datetime`, `re`, `collections`, `dataclasses`, `typing`
- Internal: `myrm_agent_harness.agent.context_management`
