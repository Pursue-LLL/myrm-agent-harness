# privacy_gate/

## Overview
Typed Memory Privacy Boundary & Allowlist Security Gate: static regex secret scanning (API keys, private keys, connection URIs, JWTs), .myrmignore exclusion and allowlist matching, safe semantic redaction, and hard veto enforcement.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public entry point for memory privacy boundary and allowlist gate. | ✅ |
| `gate.py` | Core | Memory privacy boundary gate enforcing exclusion rules, secret detection, and safe redaction. | ✅ |
| `rule_matcher.py` | Core | Path and content rule matcher for memory privacy boundaries. | ✅ |
| `secret_detector.py` | Core | Deterministic pattern-based detector for high-risk secrets and credentials. | ✅ |
| `types.py` | Types | Type definitions and contracts for memory privacy boundary and allowlist gate. | ✅ |

## Key Dependencies

- External libraries: `pydantic`
