# directory_trust_remote_memory/

## Overview

Directory trust gate for remote memory access. Harness core security module separating local scope filtering from remote memory egress.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Directory trust gate for remote memory access — Harness core security module separating local scope filtering from remote memory egress. | ✅ |
| resolver.py | Core | Single-point atomic resolver for project memory configurations with directory trust gating — Harness core security module preventing TOCTOU races and unauthorized remote memory exfiltration. | ✅ |
| trust_store.py | Core | Directory trust registry maintaining canonical trusted project roots — Harness core security module preventing untrusted cloned repositories from exfiltrating memories. | ✅ |
| types.py | Core | Type definitions and models for directory trust gating and remote memory resolution — Harness core security module separating local scope filtering from remote memory egress. | ✅ |
