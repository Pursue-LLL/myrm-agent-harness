# security/

## Overview
Execution security — shell command analysis, blacklists, validators, and C-level PEP 578 sandboxing.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Execution security — shell command analysis, blacklists, and validators. | — |
| archive_sanitizer.py | Core | Archive extraction security hardening. | ✅ |
| ast_parser.py | Core | Lightweight Bash AST semantic parser and capability boundary classifier. | ✅ |
| audit_sandbox.py | Core | PEP 578 Audit Hook. Provides C-level interception of dangerous operations (network, fs, process, memory) to prevent LLM code escapes, readonly_workspace filesystem protection, adaptive socket address resolution, zero-dependency source code generation, and sensitive credential shields. | ✅ |
| blacklist.py | Core | Security blacklists for code execution. | ✅ |
| bff_refactor.py | Core | BFF auto-refactor for client secret leaks: moves raw credentials into sandbox `.env`, generates a server-side proxy route (Next.js / Node.js) and rewrites the client component to call the relative proxy. | ✅ |
| client_secret_scanner.py | Core | Detects hardcoded secrets, API tokens and DB connection strings in browser-facing code (React/Next.js/Vue/HTML/Svelte/JS/TS); yields `SecretFinding`. | ✅ |
| env_isolation.py | Core | Child process environment variable isolation, sensitive token stripping, and safe inheritance SSOT. | ✅ |
| risk_classifier.py | Core | Command risk classifier for shell_exec auto-allow decisions. | ✅ |
| command_explainer/ | Core | Shell pipeline span extraction + per-segment risk levels for approval UI highlighting. | ✅ |
| shell_bleed.py | Core | Shell bleed detection — scan scripts for sensitive environment variable references. | ✅ |
| shell_command_analyzer.py | Core | Shell Command Analyzer — multi-layer security (L1: binary/Unicode, L1.5: ANSI-C/locale quoting evasion BLOCK, L2: injection/dangerous commands, L2.5: SQL statement guard, L3: suspicious patterns & protected instruction file mutation detection via `is_protected_instruction_mutation_command`, L4: recursive shell wrapper analysis for bash -c/sh -c/trap). Character-level state machine for quote-aware preprocessing. | ✅ | Persona-instruction mutations (redirect, `sed -i`/`tee`/`cp`/`mv`/`rm`/`truncate`, interpreter writes) are detected from `core.security.path.rules.PROTECTED_INSTRUCTION_PATTERNS`, so this analyzer and the file tools judge the same paths. Threat category `injection` is reserved for shell-syntax vectors (`$()`, backtick, `${}`, `;`, process substitution) that callers vetting human-authored commands (the hook command gate) may waive; CR/NUL smuggling is category `binary_injection` and is never waivable. Rule tables live in `shell_command_rules.py`. |
| shell_command_rules.py | Core | Pattern catalogue for the shell command analyzer: layer 1 literals (CR/NUL, invisible Unicode), layer 1.5 quoting-evasion regexes, layer 2 injection vectors and dangerous commands (incl. SSH access-file writes), layer 3 suspicious patterns (incl. crontab modification). Pure data, no dependency on analyzer types. | ✅ |
| shell_command_strip.py | Core | Quote-stripping helper for shell command preprocessing | ✅ |
| sql_statement_guard.py | Core | SQL Statement Guard — detect destructive SQL in DB client commands (psql/mysql/sqlite3/sqlcmd/mongosh). Extracts SQL from -c/-e/--eval flags and pipe patterns, triggers ESCALATE for write operations. | ✅ |
| script_armor.py | Core | Script materialization & subprocess invocation armor — protect persistent session against beacon swallowing, exit-statement session deaths, and quote bombs by materializing complex scripts to temporary files executed via subshell. Includes ArmoredCommandString metadata tagging and sweep_stale_materialized_scripts orphan GC. | ✅ |
| validator.py | Core | Unified security validator for code execution. | ✅ |
| destructive_rules.py | Core | 细粒度破坏性命令静态规则分析器（rm/git/dd/mkfs/find/inline-script）与爆炸半径推导 | ✅ |
| destructive_types.py | Core | 破坏性分析类型定义、不可逆常量命令集与爆炸半径数据结构 | ✅ |
| workspace_snapshot.py | Core | 零拷贝原子工作区快照创建（create_workspace_snapshot）与一键撤销回滚（rollback_workspace_snapshot） | ✅ |

| Submodule | Description |
|-----------|-------------|
| safe_command_configs/ | Safe subcommand configurations for flag-level command validation. |
