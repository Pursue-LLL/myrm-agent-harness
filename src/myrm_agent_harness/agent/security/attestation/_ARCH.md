# attestation/

## Overview

Runtime environment and connection integrity attestation suite.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Runtime environment and connection integrity attestation suite | ✅ |
| engine.py | Core | Engine running all-vector pre-flight security integrity attestation audits — Executes host boundary, mount penetration, binary tampering, and TLS certificate checks. Issues cryptographically timestamped attestation reports and enforces hard-break shutdowns. | ✅ |
| models.py | Core | Data models for runtime environment and connection integrity attestation suite — Immutable contracts defining vector categories, check results, and comprehensive environment attestation reports. | ✅ |
| probes.py | Core | Security vector inspection probes for host isolation, mounts, binaries, and TLS — Low-overhead vector probes evaluating runtime sandbox constraints, file-boundary penetrations, binary SHA-256 integrity, and outbound TLS certificates. | ✅ |
