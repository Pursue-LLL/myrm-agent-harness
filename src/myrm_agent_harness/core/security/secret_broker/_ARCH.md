# secret_broker/

## Overview

Secret broker package providing credential isolation and zero-context replacement. Harness core security subsystem inspired by OpenClaw 2.0 (credentials-vault & secret-broker).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Secret broker package providing credential isolation and zero-context replacement — Harness core security subsystem inspired by OpenClaw 2.0 (credentials-vault & secret-broker). | ✅ |
| atomic_grant.py | Core | One-Shot Atomic Operation Grant Manager with parameter hash binding and change invalidation — Harness core security module inspired by OpenClaw 2.0 (one-shot operation grants). Guarantees sensitive operations (payments, mutations, emails) are authorized for exact payloads once. | ✅ |
| interceptor.py | Core | Outbound Egress Secret Interceptor for zero-context credential replacement — Harness core security module inspired by OpenClaw 2.0 (secret-broker.ts). Intercepts egress HTTP headers/payloads at outbound dispatch, keeping model context 100% credential-free. | ✅ |
| types.py | Core | Type definitions for Mechanical Credential Isolation and Zero-Context Secret Replacement — Harness core security subsystem inspired by OpenClaw 2.0 (Secret Broker & Credentials Vault). Prevents secret keys from ever entering model prompt context and enforces egress-bound proxy injection. | ✅ |
| vault.py | Core | Egress-Bound Secret Vault providing write-only credential storage and host-binding resolution — Harness core security module inspired by OpenClaw 2.0 (credentials-vault.ts). Prevents secret tokens from entering model context and limits resolution strictly to pre-bound destination hosts. | ✅ |
