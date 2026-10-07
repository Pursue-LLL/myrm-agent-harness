# External Agent Memory Bridge & Skill Writer Architecture

## Overview
The `external_bridge` toolkit module provides bi-directional memory integration and safe prompt/skill file management for third-party developer agent environments (including Cursor, Anthropic Claude Code, OpenAI Codex, Hermes, and OpenClaw).

## Architecture & Principles
1. **Isolated Safe Delimiters (`SafeMarkerInjector`)**:
   All auto-injected instructions are encapsulated strictly within delimiters:
   `<!-- MYRM_MEMORY_BRIDGE_START -->` ... `<!-- MYRM_MEMORY_BRIDGE_END -->`.
   Any pre-existing user configurations, project customs, and rules outside the markers are preserved with 100% fidelity.
2. **Deterministic Idempotency**:
   Running installation repeatedly on the same configuration file produces `UNCHANGED` once configured, preventing file bloating or diff churn.
3. **Atomic Uninstallation**:
   Uninstall cleanly strips the delimited block. If the target configuration file only contained the bridge block, the empty file is deleted; otherwise, user configurations are preserved.
4. **Third-Party Memory Conflict Detection**:
   Inspects target instruction files to identify competing memory plugins (e.g., legacy mem0/zep/sqlite rules) to prevent conflicting tool invocations and memory drift.

## Modules
- `models.py`: Strongly-typed dataclasses and enums (`ExternalAgentType`, `SkillInstallConfig`, `SkillInstallResult`, `SkillUninstallResult`, `MemoryConflictReport`).
- `targets.py`: Abstract target base class and concrete target adapters (`CursorBridgeTarget`, `ClaudeCodeBridgeTarget`, etc.).
- `registry.py`: Central target registry supporting dynamic extension.
- `conflict_detector.py`: Heuristic scanner detecting incompatible legacy memory directives.
- `skill_writer.py`: File synchronization and marker-delimited lifecycle manager.
