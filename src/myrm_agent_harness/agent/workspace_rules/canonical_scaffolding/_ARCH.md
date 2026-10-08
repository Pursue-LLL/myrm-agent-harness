# canonical_scaffolding/

## Overview
Canonical agent workspace scaffolding, heterogeneous ecosystem sniffer, and sandboxed safe encapsulation subsystem. Provides standard topology validation, zero-friction alien workspace migration (OpenClaw, Meta Muse, Hermes, Cursor/Windsurf), and safe sandbox containment.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Package facade exporting scaffolding types, validator, sniffer, encapsulator, and suite. | — |
| scaffolding_types.py | Types | Strongly typed models for workspace ecosystems, scaffolding manifests, sniffing results, and sandbox encapsulation. | ✅ |
| topology_validator.py | Core | Canonical workspace topology validator enforcing directory layout schemas and calculating health scores. | ✅ |
| heterogeneous_sniffer_and_wizard.py | Core | Fingerprints upstream agent ecosystems and maps heterogeneous files into canonical Myrm manifests. | ✅ |
| sandboxed_safe_encapsulator.py | Security | Scans untrusted workspaces for destructive scripts and prompt injections, encapsulating them into dedicated sandbox volumes. | ✅ |
| canonical_scaffolding_suite.py | Facade | Unified facade suite orchestrating validation, sniffing, handover, and interoperability guidance. | ✅ |

## Key Dependencies

- stdlib: `pathlib`, `re`, `hashlib`, `dataclasses`, `enum`, `typing`
- Internal: `myrm_agent_harness.agent.workspace_rules`
