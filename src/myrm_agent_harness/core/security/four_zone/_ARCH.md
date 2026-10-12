# four_zone/

## Overview

Four-Zone Workspace Layout and Read-Only Source Protection module. Harness core security subsystem providing 4-zone physical layout scaffolding, absolute read-only protection of customer raw materials, and one-way deliverable promotion.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Four-Zone Workspace Layout and Read-Only Source Protection module — Harness core security subsystem providing 4-zone physical layout scaffolding, absolute read-only protection of customer raw materials, and one-way deliverable promotion. | ✅ |
| guard.py | Core | Protection guard enforcing absolute read-only invariants on Zone 01 original assets — Harness core security guard. Intercepts file operations targeting `01_原始材料/`, raising ReadOnlySourceZoneViolationError on any write/delete/rename attempt. | ✅ |
| pipeline.py | Core | One-way artifact promotion pipeline across four workspace zones — Harness core security pipeline. Guarantees that deliverables in Zone 04 are produced strictly from ratified facts in Zone 03, eliminating stale draft hallucination in final delivery. | ✅ |
| scaffold.py | Core | Four-Zone Workspace Topology and scaffolding generator — Harness core security scaffold. Sets up physical isolation zones separating raw input, intermediate drafts, shared factual blueprints, and client-facing deliverables. | ✅ |
| types.py | Core | Type definitions for Four-Zone Workspace Layout and Read-Only Source Protection — Harness core security contracts for workspace isolation, preventing overwrite of customer original assets and enforcing one-way artifact promotion. | ✅ |
