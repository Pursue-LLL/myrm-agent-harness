# pii_vault/

## Overview

Client-Side PII Auto-Sanitization and Local Vault Reverse Mapping module. Harness core security subsystem for client-side privacy preservation and reversible pseudonymization.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Client-Side PII Auto-Sanitization and Local Vault Reverse Mapping module — Harness core security subsystem for client-side privacy preservation and reversible pseudonymization. | ✅ |
| detector.py | Core | High-precision PII entity detector recognizing identity, financial, and contact identifiers — Harness core security module for client-side privacy preservation (Client-Side PII Sniffer). | ✅ |
| transformer.py | Core | Bidirectional PII pseudonymization and reverse reconstruction transformer — Harness core security module for client-side privacy preservation (Transparent Pseudonymization Transformer). | ✅ |
| types.py | Core | Type definitions for Client-Side PII Auto-Sanitization and Local Mapping Vault — Harness core security subsystem for client-side privacy preservation and reversible pseudonymization. | ✅ |
| vault.py | Core | Local PII mapping vault storing pseudonym-to-real bidirectional mappings in local memory — Harness core security module for client-side privacy preservation (Local Mapping Vault). Never sends mapping dictionaries to external LLMs or remote clouds. | ✅ |
