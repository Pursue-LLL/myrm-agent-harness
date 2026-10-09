# transcript_resilience/

## Overview
Two-tier transcript offloading, single-flight token refresh mutex, delayed slot allocation, and dynamic CLI vault credential engine (Item 333).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package Facade | Public exports for transcript resilience and lifecycle management. | ✅ |
| `resilience_types.py` | Contracts & Types | Strongly-typed models for transcript stubs, token states, delayed slots, and credential specs. | ✅ |
| `two_tier_transcript_offloader.py` | Core Engine | Two-tier transcript offloader maintaining bounded active viewport and restoring stubs on-demand. | ✅ |
| `single_flight_refresh_gate.py` | Core Engine | Single-flight mutex gate queuing concurrent 401 refresh bursts and broadcasting renewed token. | ✅ |
| `delayed_slot_allocator.py` | Core Engine | Delayed concurrency slot manager enforcing lazy allocation on first message and active slot HUD. | ✅ |
| `dynamic_cli_credential_engine.py` | Core Engine | External CLI vault and scripted credential evaluator resolving secrets dynamically into memory. | ✅ |
| `tiered_transcript_resilience_suite.py` | Unified Suite | End-to-end facade integrating offloader, refresh gate, slot allocator, and CLI vault engine. | ✅ |
