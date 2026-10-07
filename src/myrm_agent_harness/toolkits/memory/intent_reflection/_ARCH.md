# intent_reflection/

## Overview
Lightweight Reflection Intent Filter & Playbook Activation Probe: tiered intent classification (Tier 0 Fast Path, Tier 1 Code Execution, Tier 2 Knowledge Content, Tier 3 Deep Reasoning), sub-millisecond heuristic bypass gating, sidecar neural probe delegation, and facet-scoped targeted playbook activation preventing context attention dilution and excessive vector retrieval.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public facade of the intent reflection subsystem. | ✅ |
| `classifier.py` | Core | Fast-path tiered intent classifier for procedural memory and reflection gating. | ✅ |
| `probe.py` | Core | Activation probe that selectively awakens relevant playbooks based on intent tier. | ✅ |
| `types.py` | Types | Typed data contracts for the intent reflection subsystem. | ✅ |

## Key Dependencies

- `toolkits.memory`
