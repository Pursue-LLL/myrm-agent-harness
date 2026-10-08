# core/security/on_demand_masking/

## Overview
On-demand credential materialization, conflict resolution, and multi-encoding secret masking across raw, URL-encoded, Base64, and Hex representations.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public facade exporting MultiEncodingSecretMasker, OnDemandCredentialResolver, and types. | — |
| `types.py` | Types | Domain models for credential fields, materialization, and masked execution results. | ✅ |
| `masker.py` | Core | Multi-encoding redaction engine implementing longest-first variant matching. | ✅ |
| `resolver.py` | Core | Lazy credential provider registry with cross-handle key conflict detection. | ✅ |

## Dependencies
- Standard library: `base64`, `collections.abc`, `dataclasses`, `urllib.parse`
- No internal harness coupling.
