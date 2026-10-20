# workspace_blueprint/

## Overview
Per-Project Workspace Team Blueprint Auto-Reuse module (Item 36).

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Per-Project Workspace Team Blueprint Auto-Reuse module (Item 36). — Thread-safe WorkspaceBlueprintStore, AutoReusePolicy enum, and WorkspaceBlueprintBinding data structures. | — |
| `binding_store.py` | Core | Thread-safe storage and resolution engine for Project Workspace Team Blueprint Auto-Reuse. — WorkspaceBlueprintStore providing thread-safe workspace binding, auto-reuse policy checks, | ✅ |
| `types.py` | Types | Domain types and contracts for Per-Project Workspace Team Blueprint Auto-Reuse (Item 36). — Strongly-typed domain models for workspace-to-blueprint bindings, reuse resolutions, | ✅ |
