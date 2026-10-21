# unattended_reliability/

## Overview
Unattended Reliability Triad Self-Proof Suite.
Measures and visually proves the three essential reliability pillars of 7x24h unattended autonomous agents:
1. **Resume After Restart Rate**: Successful recovery from unexpected sandbox or process crashes without orphan deadlocks.
2. **Zero Duplicate Side-Effects Rate**: Strict idempotency on retries/replays via ReplayAuditor preventing repeated writes, charges, or commits.
3. **Honest Blocker Reporting Rate**: Truthful blocker notification when unrecoverable obstacles arise, strictly forbidding hallucinated successes.

Includes a built-in self-proof benchmark runner producing auditable triad scorecard proofs.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package Facade | Public exports for UnattendedReliabilityEvaluator, records, and triad scores. | ✅ |
| `models.py` | DTO & Enums | Immutable data models for resume status, side effect status, reporting veracity, and triad scores. | ✅ |
| `evaluator.py` | Core Evaluator | Thread-safe in-memory metrics evaluator and self-proof benchmark runner. | ✅ |

## Design Constraints & Principles
1. **Triad Verification**: Explicitly tracks the three dimensions (`resume`, `zero duplicate side-effects`, `honest blocker`) rather than vague single-turn scores.
2. **Hallucination Prevention**: Explicitly penalizes hallucinated successes (`HALLUCINATED_SUCCESS`) in the honest reporting score.
3. **Repeatable Self-Proof**: Evaluator includes `run_self_proof_benchmark()` executing mock failure recovery scenarios for immediate customer verification.
4. **Strict Typing**: Zero `Any` usage across all schemas and evaluator methods.
