# audit_coverage/

## Overview

Security Audit Explicit Coverage & Replayable Repair Bundle Package.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Security Audit Explicit Coverage & Replayable Repair Bundle Package | ✅ |
| engine.py | Core | Audit Coverage Engine orchestrating explicit coverage disclosure and repair workflows — Harness core security engine. Coordinates application model validation, adversarial challenge reviews, explicit coverage metrics, and replayable repair generation. | ✅ |
| independent_challenge.py | Core | Independent adversarial challenge reviewer for security audit findings — Harness core security engine. Subject findings to independent adversarial re-evaluation to eliminate false positives before final disclosure. | ✅ |
| model_contract.py | Core | Application model contract validation for security audit findings — Harness core security engine. Ensures audit conclusions are strictly supported by declared architectural models rather than speculative assertions. | ✅ |
| repair_bundle.py | Core | Replayable repair bundle engine for verifiable security issue remediation — Harness core security engine. Packages security findings into replayable, reviewable repair bundles with explicit verification tiers (self_reported vs tested). | ✅ |
| types.py | Core | Domain types and models for Security Audit Explicit Coverage & Replayable Repair Bundles — Harness core domain models based on gstack CSO audit paradigms. | ✅ |
