# marketplace_contract/

## Overview

Marketplace Manifest Source Pinning & Capability Contract Package.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Marketplace Manifest Source Pinning & Capability Contract Package | ✅ |
| gate.py | Core | Marketplace admission gate enforcing organization source allowlists and capability restrictions — Harness core security engine. Gating mechanism enforcing organization-wide source pinning, tier classification, and capability isolation prior to installation. | ✅ |
| types.py | Core | Domain types and models for Marketplace Manifest Source Pinning & Capability Contract — Harness core domain models based on claw/hermes-agent plugin-catalog declarative contracts and Claude Code enterprise admission gating. | ✅ |
| validator.py | Core | Validator for declarative marketplace manifest source pinning and capability contracts — Harness core security engine. Ensures marketplace items declare immutable commit SHAs and explicit capability contracts before admission. | ✅ |
