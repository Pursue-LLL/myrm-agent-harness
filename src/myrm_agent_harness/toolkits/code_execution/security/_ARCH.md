# security/

## Overview
Execution security — shell command analysis, blacklists, validators, and C-level PEP 578 sandboxing.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Execution security — shell command analysis, blacklists, and validators. | — |
| archive_sanitizer.py | Core | Archive extraction security hardening. | ✅ |
| ast_parser.py | Core | Lightweight Bash AST semantic parser and capability boundary classifier. Cuts commands where the shell does (`core.security.shell_command_lexer`), reads through the deny-direction prefixes of `core.security.shell_wrapper_peel` (`sudo`, `nohup`, `env`, shell `-c` scripts, `$(...)`/backticks) keeping the outer command distinct while recording the inner ones as `nested_actions`, and names each line of text it cannot parse so an unclosed quote cannot hide the commands after it. | ✅ |
| capability_tables.py | Core | Policy data of the capability gate: read-only and test command sets, git subcommands by effect, always-escalating commands, sensitive redirect targets. `SAFE_READONLY_COMMANDS` describes only what truly reads and nothing else; a prefix like `env` or `command` is deliberately absent so the capability of the line is decided by the inner command. | ✅ |
| audit_sandbox.py | Core | PEP 578 Audit Hook. Provides C-level interception of dangerous operations (network, fs, process, memory) to prevent LLM code escapes, readonly_workspace filesystem protection, adaptive socket address resolution, zero-dependency source code generation, and sensitive credential shields. | ✅ |
| blacklist.py | Core | Security blacklists for code execution. | ✅ |
| bff_refactor.py | Core | BFF auto-refactor for client secret leaks: moves raw credentials into sandbox `.env`, generates a server-side proxy route (Next.js / Node.js) and rewrites the client component to call the relative proxy. | ✅ |
| client_secret_scanner.py | Core | Detects hardcoded secrets, API tokens and DB connection strings in browser-facing code (React/Next.js/Vue/HTML/Svelte/JS/TS); yields `SecretFinding`. | ✅ |
| external_effect_detector.py | Core | Classifies the head command of each shell pipeline segment into external-effect categories a file rollback cannot undo (`database`, `container_cloud`, `network_mutation`, `publish`); quoted text, heredoc bodies and plain arguments are not effects. | ✅ |
| env_isolation.py | Core | Child process environment variable isolation, sensitive token stripping, and safe inheritance SSOT. | ✅ |
| risk_classifier.py | Core | Command risk classifier for approval auto-allow decisions. Judges every command of the line as the shell reads it (`core.security.shell_command_lexer`), looks through `time` / `command` / `timeout`, and refuses read-only tools whose arguments run a program or write a file (`safe_commands.py`). It also judges the command every `$(...)`/backtick substitution runs (`core.security.shell_wrapper_peel.substitution_bodies`), so `echo $(curl ...)` is UNKNOWN because `curl` is; arithmetic `$((...))` runs no command and is not read as one; a substitution tree nested past `DENY_WRAPPER_DEPTH` is UNKNOWN (fail-closed). | ✅ |
| command_explainer/ | Core | Shell pipeline span extraction + per-segment risk levels for approval UI highlighting. | ✅ |
| safe_commands.py | Core | Read-only command allow-list, transparent wrapper unwrapping, and argument guards (`rg --pre`, `sort -o`, `fd -x`, `uniq IN OUT`, version-manager `exec`/`run`). Pure data and functions. `TRANSPARENT_WRAPPERS` / `unwrap_transparent_wrapper` are re-exported from `core.security.shell_wrapper_peel`, the single home of the allow-direction unwrapping table, so this list and the deny-direction peel cannot drift apart. | ✅ |
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
