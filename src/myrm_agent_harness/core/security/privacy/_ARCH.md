# core/security/privacy/

## Overview
Three-level fail-closed privacy ladder validator for cloud sandboxes and persistent workspace state.
Provides path boundaries, credential filtering, session isolation, and transient cache ignore rules.

## File Index

| File | Role | Description | I/O/P |
|---|---|---|---|
| `__init__.py` | Package | Export public symbols | — |
| `ladder.py` | Core | 3-Level fail-closed privacy ladder validator (`PrivacyLadderValidator`, `PrivacyScanVerdict`, `PrivacyLadderLevel`) | ✅ |

## Ladder Levels
1. **Level 1 (File Level)**: Strips credentials, `.env*`, keys, certificates, system roots, and blocked OS devices.
2. **Level 2 (Session Level)**: Enforces session subdirectory isolation, preventing cross-session data exfiltration.
3. **Level 3 (Workspace Level)**: Enforces strict workspace root boundary check, immune to `../` traversal and symlink escapes.
