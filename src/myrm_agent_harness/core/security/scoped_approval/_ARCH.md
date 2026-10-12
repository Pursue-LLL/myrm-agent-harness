# scoped_approval/

## Overview

Scoped Approval Grant and Risk-Tiered Gate Suite. src/myrm_agent_harness/core/security/scoped_approval/__init__.py Scoped Approval Grant and Risk-Tiered Gate Suite. Exports domain types, lease engine, risk gate router, and facade. Strict typing applied: No `Any` types allowed.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Scoped Approval Grant and Risk-Tiered Gate Suite — src/myrm_agent_harness/core/security/scoped_approval/__init__.py Scoped Approval Grant and Risk-Tiered Gate Suite. Exports domain types, lease engine, risk gate router, and facade. Strict typing applied: No `Any` types allowed. | ✅ |
| facade.py | Core | Strict typing applied: No `Any` types allowed — src/myrm_agent_harness/core/security/scoped_approval/facade.py [INPUT] time, types, lease_engine, risk_gate_router [OUTPUT] ScopedApprovalGateFacade Strict typing applied: No `Any` types allowed. | ✅ |
| lease_engine.py | Core | Strict typing applied: No `Any` types allowed — src/myrm_agent_harness/core/security/scoped_approval/lease_engine.py [INPUT] time, uuid, types [OUTPUT] ScopedGrantLeaseEngine Strict typing applied: No `Any` types allowed. | ✅ |
| risk_gate_router.py | Core | Strict typing applied: No `Any` types allowed — src/myrm_agent_harness/core/security/scoped_approval/risk_gate_router.py [INPUT] types [OUTPUT] RiskTieredGateRouter Strict typing applied: No `Any` types allowed. | ✅ |
| types.py | Core | Domain types for Scoped Approval Grant and Risk-Tiered Gate Suite — src/myrm_agent_harness/core/security/scoped_approval/types.py [INPUT] dataclasses, enum, typing [OUTPUT] GrantScope, ActionRiskTier, GateDecision, ApprovalGrantLease, GrantUsageRecord, RiskEvaluationRequest, RiskEvaluationResult, ScopedApprovalMetrics Domain types for Scoped Approval Grant and Risk-Tiered Gate Suite. Strict typing applied: No `Any` types allowed. | ✅ |
