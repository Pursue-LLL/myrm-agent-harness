# Cognitive Memory Box Architecture

## Overview
`cognitive_box` implements a four-layer cognitive context model and strict durable memory intake guard, inspired by Hermes Agent workflow #08.

## Four Cognitive Layers
1. **Identity & Persona (`identity`)**: Core persona, ethical baselines, and inviolable guardrails.
2. **User Profile & Preferences (`user_profile`)**: User working habits, formatting preferences, and coding styles.
3. **Workspace & Environment (`environment`)**: Sandbox host environment, attached devices, toolchain versions.
4. **Distilled Lessons & Rules (`lessons_rules`)**: Lessons learned from past debugging, architectural rules, and project-specific invariants.

## Strict Intake Filter
Candidate statements pass through `StrictMemoryIntakeFilter`:
- Conversational chit-chat and greetings are discarded (`DROP_NOISE`).
- One-off transient debugging queries or procedural commands are discarded (`DROP_TRANSIENT`).
- Valid profile preferences or architectural lessons are admitted (`ADMIT`) or merged (`UPDATE_EXISTING`).

## Storage
- `FourLayerCognitiveMemoryBox` provides partitioned SQLite persistence with WAL mode and B-Tree indexing.
- Prompt injection helper `render_prompt_context()` assembles active layers into high-priority system context blocks.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Package facade for cognitive box. | ✅ |
| `box.py` | Core | Manages segregated persistence and retrieval across the four cognitive layers. | ✅ |
| `intake_filter.py` | Core | Evaluates candidate memories against strict durable admission criteria. | ✅ |
| `models.py` | Types | Types and models for cognitive box. | ✅ |
| `service.py` | Core | Unified service orchestrating intake filtering and partitioned cognitive persistence. | ✅ |
| `tools.py` | Core | Agent-facing meta-tools to inspect cognitive layers and distill durable lessons. | ✅ |
