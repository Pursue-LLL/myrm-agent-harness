# cloud_edge_relay/

## Overview
Package initialization for Hybrid Cloud-Edge Sandbox Relay & Artifact Sync (Item 58).

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Package initialization for Hybrid Cloud-Edge Sandbox Relay & Artifact Sync (Item 58). — High-level exports for HybridArtifactSyncEngine and CloudEdgeEgressRelayCoordinator. | — |
| `egress_relay.py` | Core | Cloud-Edge Egress Relay Coordinator for Network Partition Crawling (Item 58). — LocalEgressRelayResponse containing sanitized structured data extracted via local egress. | ✅ |
| `sync_engine.py` | Core | Hybrid Artifact Sync Engine supporting bidirectional incremental append (Item 58). — CAS-versioned HybridArtifactState with append-only integrity and full provenance. | ✅ |
| `types.py` | Types | Core types for Hybrid Cloud-Edge Sandbox Relay & Artifact Sync (Item 58). — Strongly-typed models for bidirectional chunk append, CAS versioning, | ✅ |
