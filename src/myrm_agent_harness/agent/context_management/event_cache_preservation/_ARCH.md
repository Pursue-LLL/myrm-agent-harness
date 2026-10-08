# event_cache_preservation/

## Overview
Cache-preserving event envelope and cold-start hydration subsystem (Item 316).

Solves the dual bottleneck of dynamic event-driven agents (Prompt Cache busting cost surges and idle sandbox resource drain) by providing:
1. **Cache-Preserving Event Envelope Protocol**: Strict dual-tier isolation keeping frozen static prefix at byte 0 (100% cache hit on Persona & MCP tool schemas) and appending dynamic payloads as immutable `<event_trigger>` tail frames, keeping projected cache hit ratios at 90%+.
2. **Sandboxed Sleep-Wake Lifecycle Engine**: Detects idle inactivity beyond threshold, freezes execution state into tiny (<10MB) snapshots with near-zero standby cost, and restores context within a 500ms hydration budget upon event arrival.
3. **Event Ephemeral Audit Trail Manager**: Decouples high-frequency background event streams from human-facing chat windows, logging complete traces while selectively surfacing critical notifications.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Public API exports for event cache preservation module. | — |
| event_envelope_types.py | Models | Domain models and contracts (`EventSourceTier`, `HydrationState`, `EventEnvelopePayload`, `CachePartitionedContextBundle`, `DormantSnapshot`, `EventAuditRecord`). | ✅ |
| cache_preserving_event_envelope_protocol.py | Core | Enforces prefix boundary and token estimation, guaranteeing prefix cache preservation across event injections. | ✅ |
| sandboxed_sleep_wake_lifecycle_engine.py | Core | Manages sandbox idle detection, snapshot serialization (<10MB), and sub-500ms instant hydration. | ✅ |
| event_audit_trail_manager.py | Core | Maintains decoupled event audit stream, preventing raw high-frequency payloads from cluttering user UI. | ✅ |
| cache_preserving_event_suite.py | Facade | Comprehensive unified facade coordinating protocol packaging, sleep-wake lifecycle, and audit management. | ✅ |

## Key Dependencies

- `agent.context_management` — Context management and prompt formatting subsystem
