# proactive_kernel/

## Overview
Proactive agent micro-kernel contract, instinctive heartbeat loops, and low-friction human-machine agreement suite (Item 319).

Solves the critical limitation where conventional agents remain purely reactive conversational puppets by providing:
1. **Proactive Micro-Kernel Contract**: Lightweight Markdown-driven specifications (`HEARTBEAT.md`, `OPPORTUNITY.md`) establishing long-term persona and inspection checklists without 20-menu deep technical debt.
2. **Instinctive Heartbeat & Opportunity Sensing Engine**: Autonomous background loop evaluating workspace drift, upcoming calendar deadlines, stale todos, and security hygiene to discover high-value proactive opportunities.
3. **Zero-Nag Etiquette Discretion Gate**: Three-tier channel classifier (critical urgent alert, non-interrupting opportunity dock in chat footer, silent memory memo) with hourly throttling to completely eliminate notification fatigue.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Public exports for proactive micro-kernel, heartbeat manifests, and zero-nag gates. | — |
| proactive_kernel_types.py | Models | Domain data structures (`ProactivityLevel`, `OpportunityCategory`, `ProactivityDiscretionTier`, `HeartbeatChecklistItem`, `HeartbeatManifest`, `ProactiveOpportunity`, `ProactiveHeartbeatResult`). | ✅ |
| heartbeat_manifest_parser.py | Core | Parser and serializer for Markdown-formatted HEARTBEAT.md specifications (`HeartbeatManifestParser`). | ✅ |
| opportunity_sensing_engine.py | Core | Background opportunity evaluator inspecting environment signals, git drift, and deadlines (`OpportunitySensingEngine`). | ✅ |
| zero_nag_discretion_gate.py | Core | Non-intrusive etiquette arbiter and hourly rate limiter for proactive suggestions (`ZeroNagDiscretionGate`). | ✅ |
| proactive_agent_kernel_suite.py | Facade | Unified high-level facade coordinating manifest loading, heartbeat ticks, dock formatting, and memoizing (`ProactiveAgentKernelSuite`). | ✅ |

## Key Dependencies

- `agent.workspace_rules` — Workspace rule scanner and canonical file conventions
- `agent.cron` — Background asynchronous scheduling primitives
