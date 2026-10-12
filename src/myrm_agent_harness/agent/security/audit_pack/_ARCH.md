# audit_pack/

## Overview

Legal-grade audit pack and non-repudiation evidence export suite.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Legal-grade audit pack and non-repudiation evidence export suite | ✅ |
| builder.py | Core | Builder for assembling and cryptographically sealing legal audit dockets — Aggregates the 5 golden evidence elements, computes the canonical root digest, and signs the docket with HMAC-SHA256 non-repudiation signature. | ✅ |
| models.py | Core | Data models for legal-grade audit pack and non-repudiation evidence dockets — Immutable contracts defining triad delegation proofs, cryptographic docket signatures, and atomic legal audit dockets capturing the 5 golden evidence elements. | ✅ |
| verifier.py | Core | Offline verifier for validating authenticity and non-repudiation of legal audit dockets — Provides standalone offline verification of root digest integrity and HMAC-SHA256 signature seals. Can be executed by external auditors, compliance officers, and legal teams without server dependency. | ✅ |
