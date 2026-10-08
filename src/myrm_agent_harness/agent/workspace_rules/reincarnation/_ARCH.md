# reincarnation/

## Overview
Agent reincarnation namespace and heritage inheritance protocol subsystem (Item 315).

Solves the cold amnesia problem across model generation upgrades and unrecoverable context snowballs by providing:
1. **Standardized REINCARNATION.md Contract**: Four canonical sections (`Soul Lineage`, `Hard Lessons & Taboos`, `Working Habits & Short-Circuits`, `Unfinished Goals`) bounded to 2000 characters.
2. **Heritage Safety & Anti-Hallucination Gate**: Eliminates speculative conjectures, requires user verification or explicit prohibition rules, and enforces budget containment.
3. **Reincarnation Circuit Breaker**: Intercepts catastrophic context degradation (overflow, deadlock timeout, manual model switch) and distills durable generational wisdom.
4. **Instant Heritage Hydrator**: Injects prior-generation wisdom into the first turn of a new session and immediately auto-archives the file to avoid permanent token tax.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Public API exports for reincarnation module. | — |
| reincarnation_types.py | Models | Domain models and contracts (`CrashCause`, `HeritageHydrationResult`, `HeritageTabooLesson`, `ReincarnationDossier`, `ReincarnationEvent`, `SoulLineageRecord`, `UnfinishedGoal`, `WorkingHabitShortcut`). | ✅ |
| heritage_safety_filter_gate.py | Core | Screens inherited memories against speculative hallucination and enforces character budget containment. | ✅ |
| reincarnation_circuit_breaker.py | Core | Intercepts catastrophic context snowball/crashes and crystallizes durable cross-model heritage into `REINCARNATION.md`. | ✅ |
| instant_heritage_hydrator.py | Core | Detects `REINCARNATION.md` on first boot, injects generational wisdom, and immediately archives it. | ✅ |
| reincarnation_protocol_suite.py | Facade | Comprehensive unified facade coordinating crash circuit breaking, safety filtering, and instant hydration. | ✅ |

## Key Dependencies

- `agent.workspace_rules` — Core workspace rules subsystem
