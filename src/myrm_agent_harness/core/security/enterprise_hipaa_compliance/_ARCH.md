# enterprise_hipaa_compliance/

## Overview

Enterprise BAA/HIPAA Compliance Conduit & Data Sovereignty Fence Suite. src/myrm_agent_harness/core/security/enterprise_hipaa_compliance/__init__.py Enterprise BAA/HIPAA Compliance Conduit & Data Sovereignty Fence Suite. Exports domain types, audit chain engine, PHI fence, and unified facade. Strict typing applied: No `Any` types allowed.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Enterprise BAA/HIPAA Compliance Conduit & Data Sovereignty Fence Suite — src/myrm_agent_harness/core/security/enterprise_hipaa_compliance/__init__.py Enterprise BAA/HIPAA Compliance Conduit & Data Sovereignty Fence Suite. Exports domain types, audit chain engine, PHI fence, and unified facade. Strict typing applied: No `Any` types allowed. | ✅ |
| audit_chain.py | Core | Strict typing applied: No `Any` types allowed — src/myrm_agent_harness/core/security/enterprise_hipaa_compliance/audit_chain.py [INPUT] hashlib, time, uuid, types [OUTPUT] HipaaAuditChainEngine Strict typing applied: No `Any` types allowed. | ✅ |
| facade.py | Core | Strict typing applied: No `Any` types allowed — src/myrm_agent_harness/core/security/enterprise_hipaa_compliance/facade.py [INPUT] types, audit_chain, phi_guard [OUTPUT] EnterpriseHipaaComplianceFacade Strict typing applied: No `Any` types allowed. | ✅ |
| phi_guard.py | Core | Strict typing applied: No `Any` types allowed — src/myrm_agent_harness/core/security/enterprise_hipaa_compliance/phi_guard.py [INPUT] re, types [OUTPUT] PhiDataSovereigntyFence Strict typing applied: No `Any` types allowed. | ✅ |
| types.py | Core | Domain types for Enterprise BAA/HIPAA Compliance Conduit & Data Sovereignty Fence Suite — src/myrm_agent_harness/core/security/enterprise_hipaa_compliance/types.py [INPUT] dataclasses, enum, typing [OUTPUT] ComplianceStandard, ProviderComplianceTier, BYOCompliantProvider, HipaaAuditChainEntry, PhiScreeningResult, ComplianceExportPackage, EnterpriseComplianceMetrics Domain types for Enterprise BAA/HIPAA Compliance Conduit & Data Sovereignty Fence Suite. Strict typing applied: No `Any` types allowed. | ✅ |
