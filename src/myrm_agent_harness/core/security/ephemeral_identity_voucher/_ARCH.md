# ephemeral_identity_voucher/

## Overview

Strict typing applied: No `Any` types allowed. src/myrm_agent_harness/core/security/ephemeral_identity_voucher/__init__.py [INPUT] facade, types, broker, manager, ledger [OUTPUT] Public API exports for Dynamic Ephemeral Identity & Verifiable Audit Trail Suite Strict typing applied: No `Any` types allowed.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Strict typing applied: No `Any` types allowed — src/myrm_agent_harness/core/security/ephemeral_identity_voucher/__init__.py [INPUT] facade, types, broker, manager, ledger [OUTPUT] Public API exports for Dynamic Ephemeral Identity & Verifiable Audit Trail Suite Strict typing applied: No `Any` types allowed. | ✅ |
| ephemeral_identity_broker.py | Core | Core engine for dynamically issuing, verifying, and terminating short-lived credentials — src/myrm_agent_harness/core/security/ephemeral_identity_voucher/ephemeral_identity_broker.py [INPUT] time, secrets, uuid, types [OUTPUT] DynamicEphemeralIdentityBroker Core engine for dynamically issuing, verifying, and terminating short-lived credentials. Strict typing applied: No `Any` types allowed. | ✅ |
| facade.py | Core | Unified facade aggregating ephemeral identities, merchant vouchers, and Merkle audit ledgers — src/myrm_agent_harness/core/security/ephemeral_identity_voucher/facade.py [INPUT] types, ephemeral_identity_broker, merchant_locked_voucher_manager, merkle_audit_ledger [OUTPUT] EphemeralIdentityAndVoucherFacade Unified facade aggregating ephemeral identities, merchant vouchers, and Merkle audit ledgers. Strict typing applied: No `Any` types allowed. | ✅ |
| merchant_locked_voucher_manager.py | Core | Engine for generating and enforcing domain-locked, single-use, capped monetary vouchers — src/myrm_agent_harness/core/security/ephemeral_identity_voucher/merchant_locked_voucher_manager.py [INPUT] time, secrets, uuid, urllib.parse, types [OUTPUT] MerchantLockedVoucherManager Engine for generating and enforcing domain-locked, single-use, capped monetary vouchers. Strict typing applied: No `Any` types allowed. | ✅ |
| merkle_audit_ledger.py | Core | Cryptographic Merkle-Tree audit ledger providing non-repudiation and tamper-evident logs — src/myrm_agent_harness/core/security/ephemeral_identity_voucher/merkle_audit_ledger.py [INPUT] hashlib, time, uuid, json, types [OUTPUT] MerkleTreeAuditLedger Cryptographic Merkle-Tree audit ledger providing non-repudiation and tamper-evident logs. Strict typing applied: No `Any` types allowed. | ✅ |
| types.py | Core | Domain types for Dynamic Ephemeral Identity & Verifiable Audit Trail Suite — src/myrm_agent_harness/core/security/ephemeral_identity_voucher/types.py [INPUT] dataclasses, enum, typing [OUTPUT] IdentityStatus, VoucherStatus, AuditPhase, EphemeralIdentity, MerchantLockedVoucher, AuditEventRecord, AuditProofBundle, EphemeralIdentityMetrics Domain types for Dynamic Ephemeral Identity & Verifiable Audit Trail Suite. Strict typing applied: No `Any` types allowed. | ✅ |
