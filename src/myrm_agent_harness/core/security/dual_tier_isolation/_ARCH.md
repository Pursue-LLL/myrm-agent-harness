# dual_tier_isolation/

## Overview

Dual-Tier Root Admin & User API Key Isolation Suite. Harness core security suite enforcing control-plane / data-plane physical boundary.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Dual-Tier Root Admin & User API Key Isolation Suite — Harness core security suite enforcing control-plane / data-plane physical boundary. | ✅ |
| isolation_gate.py | Core | Dual-Tier Physical Isolation Gate enforcing strict Control/Data plane separation — Harness core security gate preventing administrative data snooping and user privilege escalation. | ✅ |
| key_vault.py | Core | Cryptographic Key Vault and Derivation Engine for Root Admin & User Keys — Harness core security vault maintaining hashed storage and derivation mechanics. | ✅ |
| types.py | Core | Domain types and models for Dual-Tier Root Admin & User API Key Isolation Suite — Harness core security domain models ensuring strict physical separation between control-plane lifecycle operations and tenant data-plane memories. | ✅ |
