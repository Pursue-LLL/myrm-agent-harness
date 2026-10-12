# secops_audit/

## Overview

Package exports for SecOps Audit and High-Risk Surface Gate. Harness core security package for SecOps CI gating and Skill supply-chain integrity.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Package exports for SecOps Audit and High-Risk Surface Gate — Harness core security package for SecOps CI gating and Skill supply-chain integrity. | ✅ |
| skill_verifier.py | Core | Runtime Skill Integrity Verifier and Static Capability Inspector — Harness core security module. Treats Agent Skills as first-class executable code, preventing prompt injection, supply-chain poisoning, and covert permission escalation. | ✅ |
| surface_scanner.py | Core | Automated High-Risk Surface Path and Diff Scanner — Harness core security module inspired by Mike Julian engineering SecOps governance. Identifies critical attack surfaces (API, Auth, MCP, Migrations, Skills) before merge. | ✅ |
| types.py | Core | Type definitions for High-Risk Surface CI Gate and Skill Change SecOps Audit — Harness core security module inspired by Mike Julian SecOps review practices. Treats Agent Skills and security/API attack surfaces as high-risk surfaces requiring automated tagging and multi-party review gates. | ✅ |
