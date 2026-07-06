# security/

## Overview
Execution security — shell command analysis, blacklists, validators, and C-level PEP 578 sandboxing.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Execution security — shell command analysis, blacklists, and validators. | — |
| archive_sanitizer.py | Core | Archive extraction security hardening. | ✅ |
| audit_sandbox.py | Core | PEP 578 Audit Hook. Provides C-level interception of dangerous operations (network, fs, process, memory) to prevent LLM code escapes. | ✅ |
| blacklist.py | Core | Security blacklists for code execution. | ✅ |
| risk_classifier.py | Core | Command risk classifier for shell_exec auto-allow decisions. | ✅ |
| command_explainer/ | Core | Shell pipeline span extraction + per-segment risk levels for approval UI highlighting. | ✅ |
| shell_bleed.py | Core | Shell bleed detection — scan scripts for sensitive environment variable references. | ✅ |
| shell_command_analyzer.py | Core | Shell Command Analyzer — multi-layer security (L1: binary/Unicode, L1.5: ANSI-C/locale quoting evasion BLOCK, L2: injection/dangerous commands, L2.5: SQL statement guard, L3: suspicious patterns). Character-level state machine for quote-aware preprocessing. | ✅ |
| sql_statement_guard.py | Core | SQL Statement Guard — detect destructive SQL in DB client commands (psql/mysql/sqlite3/sqlcmd/mongosh). Extracts SQL from -c/-e/--eval flags and pipe patterns, triggers ESCALATE for write operations. | ✅ |
| validator.py | Core | Unified security validator for code execution. | ✅ |

| Submodule | Description |
|-----------|-------------|
| safe_command_configs/ | Safe subcommand configurations for flag-level command validation. |
