# cross_examination/

## Overview
Omni-agent unified single-entry dispatch and split cross-examination subsystem (Item 314).

Solves multi-agent fragmentation, tab-switching fatigue, and manual comparison overhead by providing:
1. **Unified Intent Dispatcher**: Heuristic intent classification routing requests to specialized agents (Coding, Research, Security, Local Fast, Architect).
2. **Split Cross-Examination Engine**: Concurrent multi-agent execution with balanced default and custom role perspectives.
3. **Consensus & Delta Highlighter**: Semantic extraction of common ground facts and contested divergences with signal-rich markdown dashboards.
4. **1-Click Arbitrator**: Seamless adoption of lead, specific, or synthesized consensus outcomes injected directly into workspace context.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Public API exports for cross-examination module. | — |
| cross_exam_types.py | Models | Domain models and contracts (`AgentRoleTarget`, `IntentCategory`, `IntentRoutingDecision`, `AgentExecutionOutput`, `CrossExamConsensus`, `CrossExamDivergence`, `CrossExamArbitrationReport`, `AdoptionChoice`, `AdoptionReceipt`). | ✅ |
| unified_intent_dispatcher.py | Core | Sub-millisecond rule-and-heuristic intent dispatcher classifying requests and recommending split cross-examination. | ✅ |
| consensus_delta_highlighter.py | Core | Analyzes multi-agent outputs, computes common ground, highlights polar deltas, and renders formatted markdown dashboard. | ✅ |
| split_cross_examination_engine.py | Core | Orchestrates execution across 2-3 target agents and generates structured arbitration report. | ✅ |
| one_click_arbitrator.py | Core | Handles 1-click adoption of specific or synthesized outcomes and compiles ready-to-inject workspace memory blocks. | ✅ |
| omni_agent_dispatcher_and_cross_examination_suite.py | Facade | Unified top-level facade coordinating dispatch, cross-examination, and adoption. | ✅ |

## Key Dependencies

- `agent.sub_agents.types` — Subagent types and execution semantics
