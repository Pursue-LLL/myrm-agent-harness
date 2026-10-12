# skill_health_audit/

## Overview

Conversational Skill Health Audit & Stealth Exfiltration Taint Sentinel Suite. src/myrm_agent_harness/core/security/skill_health_audit/__init__.py Conversational Skill Health Audit & Stealth Exfiltration Taint Sentinel Suite. Exports domain types, taint engine, privacy-min threat intel, SARIF exporter, and facade. Strict typing applied: No `Any` types allowed.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Conversational Skill Health Audit & Stealth Exfiltration Taint Sentinel Suite — src/myrm_agent_harness/core/security/skill_health_audit/__init__.py Conversational Skill Health Audit & Stealth Exfiltration Taint Sentinel Suite. Exports domain types, taint engine, privacy-min threat intel, SARIF exporter, and facade. Strict typing applied: No `Any` types allowed. | ✅ |
| ast_taint_engine.py | Core | AST taint sentinel engine identifying undeclared exfiltration flows from sources to network sinks — src/myrm_agent_harness/core/security/skill_health_audit/ast_taint_engine.py [INPUT] ast, typing, types [OUTPUT] SkillTaintSentinelEngine AST taint sentinel engine identifying undeclared exfiltration flows from sources to network sinks. Strict typing applied: No `Any` types allowed. | ✅ |
| facade.py | Core | Unified facade for conversational skill health audit, taint assertion, and SARIF reporting — src/myrm_agent_harness/core/security/skill_health_audit/facade.py [INPUT] hashlib, yaml, typing, types, ast_taint_engine, sarif_exporter, intel_provider [OUTPUT] ConversationalSkillHealthAuditFacade Unified facade for conversational skill health audit, taint assertion, and SARIF reporting. Strict typing applied: No `Any` types allowed. | ✅ |
| intel_provider.py | Core | Zero-code-upload threat intelligence provider with honest degradation ("Unavailable != Safe") — src/myrm_agent_harness/core/security/skill_health_audit/intel_provider.py [INPUT] typing, os, types [OUTPUT] PrivacyMinIntelProvider Zero-code-upload threat intelligence provider with honest degradation ("Unavailable != Safe"). Strict typing applied: No `Any` types allowed. | ✅ |
| sarif_exporter.py | Core | SARIF 2.1.0 (Static Analysis Results Interchange Format) formatter for skill scan findings — src/myrm_agent_harness/core/security/skill_health_audit/sarif_exporter.py [INPUT] typing, types [OUTPUT] Sarif210Exporter SARIF 2.1.0 (Static Analysis Results Interchange Format) formatter for skill scan findings. Strict typing applied: No `Any` types allowed. | ✅ |
| types.py | Core | Domain types for Conversational Skill Health Audit & Stealth Exfiltration Taint Sentinel Suite — src/myrm_agent_harness/core/security/skill_health_audit/types.py [INPUT] dataclasses, enum, typing [OUTPUT] SkillSecurityMetadata, TaintFlowFinding, FourRowHealthCard, SkillHealthAuditVerdict, IntelLookupStatus Domain types for Conversational Skill Health Audit & Stealth Exfiltration Taint Sentinel Suite. Strict typing applied: No `Any` types allowed. | ✅ |
