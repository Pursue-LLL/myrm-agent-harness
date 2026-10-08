# delegation/

## Overview

Triad delegation identity and privilege-intersection enforcement: immutable tokens binding the initial requester, the executor agent and the business approver, whose effective scopes are the intersection of the parties' scopes, plus a guard that blocks privilege amplification (a low-privilege requester borrowing a high-privilege agent's service account).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Package marker; callers import from `models` and `guard` explicitly. | ✅ |
| `models.py` | Types | `SubjectType`, `SubjectIdentity` and `TriadDelegationToken` (scope intersection, sub-agent token derivation). | ✅ |
| `guard.py` | Core | `PrivilegeIntersectionGuard` scope assertions and `PrivilegeAmplificationBlockedError`. | ✅ |

## Key Dependencies

- `agent/middlewares/_session_context.py` carries the active token in a `ContextVar` (`set_delegation_token` / `get_delegation_token`).
