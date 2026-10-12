# agentic_commerce/

## Overview

Exports for Autonomous Agent Commerce Protocol & Zero-Knowledge Financial Vault Suite. src/myrm_agent_harness/core/security/agentic_commerce/__init__.py [INPUT] facade, types, financial_spend_guardrail, zero_knowledge_vault [OUTPUT] Public API exports Exports for Autonomous Agent Commerce Protocol & Zero-Knowledge Financial Vault Suite.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Exports for Autonomous Agent Commerce Protocol & Zero-Knowledge Financial Vault Suite — src/myrm_agent_harness/core/security/agentic_commerce/__init__.py [INPUT] facade, types, financial_spend_guardrail, zero_knowledge_vault [OUTPUT] Public API exports Exports for Autonomous Agent Commerce Protocol & Zero-Knowledge Financial Vault Suite. | ✅ |
| facade.py | Core | Unified facade for Autonomous Agent Commerce Protocol & Zero-Knowledge Financial Vault Suite — src/myrm_agent_harness/core/security/agentic_commerce/facade.py [INPUT] time, uuid, typing [OUTPUT] AgenticCommerceSuite Unified facade for Autonomous Agent Commerce Protocol & Zero-Knowledge Financial Vault Suite. Coordinates structured intent generation, spend guardrail arbitration, zero-knowledge ephemeral token minting, and final ledger settlement. Strict typing applied: No `Any` types allowed. | ✅ |
| financial_spend_guardrail.py | Core | Multi-tier spend watchdog enforcing daily hard budget caps, single-transaction limits, — src/myrm_agent_harness/core/security/agentic_commerce/financial_spend_guardrail.py [INPUT] logging, threading, time, typing [OUTPUT] FinancialSpendGuardrail Multi-tier spend watchdog enforcing daily hard budget caps, single-transaction limits, merchant category allowlists, and human-in-the-loop (HITL) approval gates. Strict typing applied: No `Any` types allowed. | ✅ |
| types.py | Core | Data structures and specifications for Autonomous Agent Commerce Protocol & Zero-Knowledge Financial Vault Suite — src/myrm_agent_harness/core/security/agentic_commerce/types.py [INPUT] dataclasses, enum, typing [OUTPUT] PaymentRailEnum, CommerceTransactionStatus, MerchantSpec, PaymentIntent, EphemeralPaymentToken, FinancialBudgetPolicy, SettlementReceipt, AgenticCommerceMetrics Data structures and specifications for Autonomous Agent Commerce Protocol & Zero-Knowledge Financial Vault Suite. Strict typing applied: No `Any` types allowed. | ✅ |
| zero_knowledge_vault.py | Core | Implements Zero-Knowledge Financial Vault where sensitive primary account numbers (PAN) — src/myrm_agent_harness/core/security/agentic_commerce/zero_knowledge_vault.py [INPUT] secrets, threading, time, uuid, typing [OUTPUT] ZeroKnowledgeFinancialVault Implements Zero-Knowledge Financial Vault where sensitive primary account numbers (PAN) and CVVs are held isolated in secure enclave. Issues single-use ephemeral tokens to sandbox. Strict typing applied: No `Any` types allowed. | ✅ |
