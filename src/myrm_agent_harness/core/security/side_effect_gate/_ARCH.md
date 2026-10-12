# side_effect_gate/

## Overview

Pre-Action Side-Effect Gate and Post-Run Acceptance module. Harness core security subsystem for dual separation of irreversible action authorization and deliverable quality acceptance.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Pre-Action Side-Effect Gate and Post-Run Acceptance module — Harness core security subsystem for dual separation of irreversible action authorization and deliverable quality acceptance. | ✅ |
| acceptance.py | Core | Deterministic post-run acceptance evaluator for Agent deliverables — Harness post-run delivery assurance. Separates completion from acceptance by enforcing purely deterministic, uncheatable assertions (length, structure, non-empty, arithmetic balance) prior to final task handover or customer notification. | ✅ |
| gate.py | Core | Physical interceptor and authorization gate for irreversible external actions — Harness core security gate. Prevents irreversible actions (emails, charges, config mutations) from executing without explicit human pre-action approval. | ✅ |
| idempotency.py | Core | Idempotency key generation and execution receipt caching — Harness security idempotency module. Prevents duplicate external execution during retries or crash recovery by binding immutable keys to receipts. | ✅ |
| types.py | Core | Type definitions for Pre-Action Side-Effect Gate and Post-Run Acceptance — Harness security core. Defines contracts separating pre-action irreversible execution authorization from post-run delivery quality acceptance. | ✅ |
