# integration_trust/

## Overview

Integration Egress Trust Lifecycle Package.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Integration Egress Trust Lifecycle Package | ✅ |
| disclosure.py | Core | Registry for pre-connect disclosure cards explaining data lifecycle to users — Harness core security registry. Ensures all external integrations provide structured pre-authorization disclosure detailing data types read, actions performed, and purge policies. | ✅ |
| lifecycle.py | Core | Lifecycle engine for integration trust, atomic disconnect purification, and revocation — Harness core security engine. Enforces the single atomic disconnect path across all providers, preventing orphaned memory trees and incomplete OAuth token revocations. A remote revocation is reported only when the caller's `remote_revoke_fn` performed it; a remote-capable provider without a hook is `REVOCATION_FAILED` with the manual revoke URL. | ✅ |
| types.py | Core | Domain types and models for Integration Egress Trust Lifecycle — Harness core domain models ensuring integration authorizations provide full transparency, atomic memory purification upon disconnection, and verifiable account-level token revocation. | ✅ |
