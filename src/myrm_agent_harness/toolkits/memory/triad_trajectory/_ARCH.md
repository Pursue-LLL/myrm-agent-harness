# triad_trajectory/

## Overview

Task Triad Trajectory and Anti-Loop Execution Blackbox suite inspired by GPT-6 Astra.
Preserves completed milestones, dead-end failed attempts (preventing loop traps), and dynamic in-flight user steerings, providing atomic pre-prompt injection snapshots (<150 tokens) and lossless post-mortem recovery.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Export public interfaces and domain types. | ✅ |
| `types.py` | Types | Strongly-typed schemas for TriadMilestone, TriadFailedAttempt, TriadUserSteering, TaskTriadBlackboxTrajectory, AntiLoopPromptSnapshot. | ✅ |
| `ledger.py` | Core | TriadStateLedger tracking three memory pillars, versioning, and dead-end pattern matching. | ✅ |
| `injector.py` | Core | AntiLoopPromptInjector building high-density, low-token (<150t) snapshots for pre-prompt injection. | ✅ |
| `manager.py` | Core | TaskTriadTrajectoryManager handling multi-task ledgers, file persistence, and handoff import/export. | ✅ |

## Key Dependencies

- Internal: `myrm_agent_harness.toolkits.memory`
- External libraries: `pydantic`, `pathlib`, `json`, `re`
