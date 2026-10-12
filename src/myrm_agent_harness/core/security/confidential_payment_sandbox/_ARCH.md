# confidential_payment_sandbox/

## Overview

Confidential VM Hardware Isolation & Single-Use Virtual Card Payment Proxy Suite. src/myrm_agent_harness/core/security/confidential_payment_sandbox/__init__.py Confidential VM Hardware Isolation & Single-Use Virtual Card Payment Proxy Suite. Exports domain types, virtual card proxy, dual sentinel, and unified facade. Strict typing applied: No `Any` types allowed.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Confidential VM Hardware Isolation & Single-Use Virtual Card Payment Proxy Suite — src/myrm_agent_harness/core/security/confidential_payment_sandbox/__init__.py Confidential VM Hardware Isolation & Single-Use Virtual Card Payment Proxy Suite. Exports domain types, virtual card proxy, dual sentinel, and unified facade. Strict typing applied: No `Any` types allowed. | ✅ |
| dual_sentinel.py | Core | Strict typing applied: No `Any` types allowed — src/myrm_agent_harness/core/security/confidential_payment_sandbox/dual_sentinel.py [INPUT] re, types [OUTPUT] DualDirectionSecuritySentinel Strict typing applied: No `Any` types allowed. | ✅ |
| facade.py | Core | Strict typing applied: No `Any` types allowed — src/myrm_agent_harness/core/security/confidential_payment_sandbox/facade.py [INPUT] time, uuid, types, virtual_card_proxy, dual_sentinel [OUTPUT] ConfidentialPaymentSandboxFacade Strict typing applied: No `Any` types allowed. | ✅ |
| types.py | Core | Domain types for Confidential VM Hardware Isolation & Single-Use Virtual Card Payment Proxy Suite — src/myrm_agent_harness/core/security/confidential_payment_sandbox/types.py [INPUT] dataclasses, enum, typing [OUTPUT] EnclaveAttestationStatus, VirtualCardStatus, IngressFenceMode, ConfidentialEnclaveAttestation, SingleUseVirtualCard, VirtualCardPaymentRequest, VirtualCardPaymentReceipt, DualSentinelScanResult, ConfidentialPaymentMetrics Domain types for Confidential VM Hardware Isolation & Single-Use Virtual Card Payment Proxy Suite. Strict typing applied: No `Any` types allowed. | ✅ |
| virtual_card_proxy.py | Core | Strict typing applied: No `Any` types allowed — src/myrm_agent_harness/core/security/confidential_payment_sandbox/virtual_card_proxy.py [INPUT] time, uuid, types [OUTPUT] SingleUseVirtualCardProxy Strict typing applied: No `Any` types allowed. | ✅ |
