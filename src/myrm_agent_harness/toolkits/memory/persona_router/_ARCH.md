# persona_router/

## Overview
On-Demand Persona Skill & Anti-Pollution Context Router: persona-as-a-skill facet decoupling, intent-aware style suppression gate (100% zero-token suppression on technical CLI/code tasks), contextual persona injection for creative/business communication, and explicit /about-me directive handling preventing context attention dilution and token waste.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public facade of the persona router subsystem. | ✅ |
| `gate.py` | Core | Gatekeeper inspecting user turn intent to strictly suppress persona tokens in technical tasks. | ✅ |
| `router.py` | Core | Dynamic context router injecting persona facets strictly on demand and suppressing context pollution. | ✅ |
| `types.py` | Types | Typed data contracts for the persona router subsystem. | ✅ |

## Key Dependencies

- None (self-contained within the package and the standard library)
