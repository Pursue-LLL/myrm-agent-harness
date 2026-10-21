# core/security/path/

## Overview
Path security domain: the single import surface for every path protection rule in the
harness. Three modules with one responsibility each, so a caller that only needs to
resolve a path safely never pulls protection policy into scope, and a caller that needs
policy never re-implements path parsing.

## File Index

| File | Role | Description | I/O/P |
|---|---|---|---|
| `__init__.py` | Package | Aggregation facade. Re-exports the public API and declares `__all__` so the `agent.security.path_security` shim forwards exactly this set and never widens it. | — |
| `pattern.py` | Core | Path-glob matcher SSOT — `compile_path_pattern` (segment-scoped `*`/`?`, recursive `**`, character classes, cached, consecutive `**/` collapsed), `path_matches_pattern` (relative patterns apply at any depth, absolute patterns anchored, dotfiles reachable; **case ignored by default** so a protected file cannot be reached by respelling it on APFS/NTFS), `first_matching_pattern` (names the rule that fired), `PathPatternMatch` (protected file + covering rule), `iter_matching_files` (bounded sweep: prunes dependency/build dirs, caps inspected files, logs when the cap trips), `normalise_path_pattern`. Its prune list is independent of the search-candidate pruner in `agent/meta_tools/file_search/fallback_discovery.py`. | ✅ |
| `filesystem.py` | Core | Generic path safety, no product policy — dangerous system roots (`DANGEROUS_PATHS`, built at import time from Unix roots, user-sensitive dirs and Windows roots), Windows reserved device names (`BLOCKED_DEVICE_NAMES`), POSIX/Windows special-filesystem prefixes, `is_dangerous_path`, `is_blocked_device_path` (pre-IO static inspection plus `lstat` mode checks), `is_within_boundary` (symlink-escape immune), `safe_join_path` (null-byte, absolute-path, traversal and symlink defence; returns the *virtual* absolute path so bind mounts keep their prefix), `MAX_PATH_LENGTH`, `is_content_not_path` and `coerce_filesystem_path` runtime type guards. | ✅ |
| `rules.py` | Core | Protected-path policy — `SENSITIVE_FILE_PATTERNS` (credentials, env files, cloud credentials, git config, databases, password files), `PROTECTED_INSTRUCTION_PATTERNS` (persona/guardrail instruction files, also matched through the symlink target; directory-scoped rules such as `.cursor/rules` cover the directory and everything under it, so emptying the directory is refused too), `EVIDENCE_READONLY_PATTERNS` (read-only session evidence and user inputs, covering both the directories themselves and their contents so `rm -rf evidence` is refused alongside `rm -rf evidence/report.pdf`), and the three predicates that read them. | ✅ |

## Layering
```
pattern.py      no internal deps
filesystem.py   no internal deps
rules.py        → filesystem.is_content_not_path, pattern.first_matching_pattern
__init__.py     → filesystem, rules
```
One direction only. `pattern` and `filesystem` know nothing about protection policy, so
the rule lists have exactly one home.

## Consumers
- `agent/meta_tools/file_ops/validators/` — `SensitiveFileValidator`, `EvidenceReadOnlyValidator`, `InvariantValidator`
- `agent/meta_tools/bash/_security/path_guard.py` — shell channel, via the predicates
- `agent/goals/invariant_snapshot.py` — post-hoc tamper detection
- `agent/security/path_security.py` — stable `agent.security.*` shim over this package
- `core/security/types.py` (`PathPolicy`), `core/security/privacy/ladder.py`, `core/security/guards/privacy_ladder.py`
- `toolkits/` — `code_execution/`, `storage/`, `filesystem_suggest/`, `wiki/`, `acp/`

Both protection layers resolve patterns through `pattern.py`, so the pre-write guard and
the post-hoc integrity check return the same verdict for the same file. A rule that
matches nothing is logged by `invariant_snapshot.py` instead of being counted as coverage.

Every guard in this package — `is_sensitive_file`, `is_protected_instruction_file`
and `is_evidence_readonly_file` — inherits the matcher's case-insensitive default. That
default is the security invariant, not a convenience: APFS and NTFS resolve `Key.Pem`
and `key.pem` to one file, so a case-sensitive rule would let a protected credential be
reached by changing only its spelling. A caller that genuinely needs case-distinguishing
rules passes `case_sensitive=True`.
