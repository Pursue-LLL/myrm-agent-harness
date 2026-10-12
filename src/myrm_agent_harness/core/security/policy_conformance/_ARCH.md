# policy_conformance/

## Overview

Agent Policy Conformance Auditor & Message Routing Verification Suite. src/myrm_agent_harness/core/security/policy_conformance/__init__.py Agent Policy Conformance Auditor & Message Routing Verification Suite. Exporting domain types, drift auditor, routing verifier, and unified facade. Strict typing applied: No `Any` types allowed.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Agent Policy Conformance Auditor & Message Routing Verification Suite — src/myrm_agent_harness/core/security/policy_conformance/__init__.py Agent Policy Conformance Auditor & Message Routing Verification Suite. Exporting domain types, drift auditor, routing verifier, and unified facade. Strict typing applied: No `Any` types allowed. | ✅ |
| drift_auditor.py | Core | Strict typing applied: No `Any` types allowed — src/myrm_agent_harness/core/security/policy_conformance/drift_auditor.py [INPUT] types [OUTPUT] DeclarativePolicyDriftAuditor Strict typing applied: No `Any` types allowed. | ✅ |
| facade.py | Core | Strict typing applied: No `Any` types allowed — src/myrm_agent_harness/core/security/policy_conformance/facade.py [INPUT] uuid, types, drift_auditor, routing_verifier [OUTPUT] AgentPolicyConformanceFacade Strict typing applied: No `Any` types allowed. | ✅ |
| routing_verifier.py | Core | Strict typing applied: No `Any` types allowed — src/myrm_agent_harness/core/security/policy_conformance/routing_verifier.py [INPUT] types [OUTPUT] SyntheticMessageRoutingVerifier Strict typing applied: No `Any` types allowed. | ✅ |
| types.py | Core | Domain types for Agent Policy Conformance Auditor & Message Routing Verification Suite — src/myrm_agent_harness/core/security/policy_conformance/types.py [INPUT] dataclasses, enum, typing [OUTPUT] DriftSeverity, PolicyBaseline, AgentRuntimeConfig, ConfigDriftFinding, RoutingRule, RoutingTestCase, RoutingVerificationResult, PolicyConformanceReport, PolicyAuditorMetrics Domain types for Agent Policy Conformance Auditor & Message Routing Verification Suite. Strict typing applied: No `Any` types allowed. | ✅ |
