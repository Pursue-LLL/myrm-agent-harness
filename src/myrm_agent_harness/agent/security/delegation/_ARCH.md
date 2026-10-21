# delegation/

## Overview
Triad delegation identity package.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Triad delegation identity package. | — |
| `guard.py` | Core | Privilege Intersection Guard for blocking privilege amplification attacks. — PrivilegeAmplificationBlockedError: Raised when an operation is blocked due to lack of effective; PrivilegeIntersectionGuard: Security guard verifying that the triad delegation token satisfies required | ✅ |
| `models.py` | Types | Data models for Triad Delegation Identity and Privilege Context. — SubjectType: Classification of an identity subject in the delegation chain.; SubjectIdentity: Immutable identity representation of an actor in the system.; TriadDelegationToken: Cryptographic-grade immutable token representing the triad delegation contract. | ✅ |
