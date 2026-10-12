# kernel_continuous_enforcement/

## Overview

Kernel Continuous Enforcement, Formal Policy Prover, and Revocation Residue Suite. Continuous kernel/process runtime boundary aligned with NVIDIA OpenShell. Enforces 3D egress policies, proves policy proposals, and audits post-termination residue.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Kernel Continuous Enforcement, Formal Policy Prover, and Revocation Residue Suite — Continuous kernel/process runtime boundary aligned with NVIDIA OpenShell. Enforces 3D egress policies, proves policy proposals, and audits post-termination residue. | ✅ |
| facade.py | Core | Facade for Kernel Continuous Enforcement, Formal Policy Prover, — Main entry point for continuous runtime enforcement suite in harness. Strictly avoids Any types; enforced under 400 lines limit. | ✅ |
| formal_policy_prover.py | Core | Formal policy prover and advisor gate for runtime network policy changes — Advisor gate aligned with OpenShell prover architecture. Analyzes proposals for wildcard binaries, sensitive ports, unconstrained path globs, and unauthorized protocol upgrade permissions before granting policy relaxation. Strictly avoids Any types; enforced under 400 lines limit. | ✅ |
| revocation_residue_verifier.py | Core | Revocation residue verifier for post-termination sandbox and run audits — Verification engine based on John Rood's post-revocation testing methodology: "the fence is the demo; revocation is the product. kill a run, then prove nothing it kept still works: memory files, cached tokens, and stray processes." Strictly avoids Any types; enforced under 400 lines limit. | ✅ |
| three_dim_enforcer.py | Core | Three-dimensional continuous runtime network enforcer — Continuous runtime security layer aligned with NVIDIA OpenShell's 3D policy model. Validates process binaries against endpoints, matches most specific path glob, and strictly blocks unauthorized protocol upgrade headers. Strictly avoids Any types; enforced under 400 lines limit. | ✅ |
| types.py | Core | Type definitions for Kernel Continuous Enforcement, Formal Policy Prover, — Core schema definitions for OpenShell-aligned continuous runtime enforcement. Strictly avoids Any types; enforced under 400 lines limit. | ✅ |
