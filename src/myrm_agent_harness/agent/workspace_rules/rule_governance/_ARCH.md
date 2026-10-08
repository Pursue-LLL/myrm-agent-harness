# rule_governance/

## Overview

Subsystem providing exception-aware rule parsing, SSOT memory-file conflict arbitration, rule drift audits, and secret scanning.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Entry point exporting rule governance contracts and facade suite. | ✅ |
| `governance_types.py` | Types | Domain models for exception-aware rules, drift auditing, and conflict arbitration. | ✅ |
| `exception_aware_rule_parser.py` | Core | Parser for core directives and explicit exception branches with caller evaluation. | ✅ |
| `memory_file_conflict_arbiter.py` | Core | Arbiter resolving memory-file contradictions and asserting workspace files as SSOT. | ✅ |
| `rule_drift_and_secret_probe.py` | Core | Active probe verifying rule drift against repo state, secret redaction, and shadowed rules. | ✅ |
| `persistent_rule_governance_suite.py` | Core | End-to-end facade orchestrating exception evaluation, secret scrubbing, and drift audits. | ✅ |
