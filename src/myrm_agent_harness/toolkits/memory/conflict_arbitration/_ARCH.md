# conflict_arbitration/

## Overview
Memory Conflict Semantic Arbitration & User-Confirmed Decision Freeze Gate: multi-source factual divergence detection (Merge vs Override vs Contradiction), human arbitration cards, cryptographic immutable freeze locks, and anti-tamper write gates.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public facade of the conflict arbitration subsystem. | ✅ |
| `freeze_gate.py` | Core | Gatekeeper enforcing immutable freeze locks on facts confirmed by human operators. | ✅ |
| `semantic_arbitrator.py` | Core | Semantic arbitrator for memory conflicts and divergence analysis. | ✅ |
| `types.py` | Types | Typed data contracts for the conflict arbitration subsystem. | ✅ |

## Key Dependencies

- None (self-contained within the package and the standard library)
