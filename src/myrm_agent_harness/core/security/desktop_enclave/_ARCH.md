# desktop_enclave/

## Overview

Computer-Use Safe Enclave and Action Replay Audit Deck module. Harness core security subsystem for Computer-Use safe enclaves.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Computer-Use Safe Enclave and Action Replay Audit Deck module — Harness core security subsystem for Computer-Use safe enclaves. | ✅ |
| audit_deck.py | Core | Desktop Action Audit Deck and Live Intent HUD telemetry ring buffer — Harness core security subsystem for Computer-Use safe enclaves. | ✅ |
| gate.py | Core | Desktop Action Safe Enclave Gate for intercepting critical actions and handling emergency panic — Harness core security gate for Computer-Use agents. | ✅ |
| semantic_matcher.py | Core | High-precision semantic risk matcher for computer-use desktop actions — Harness core security matcher. Detects dangerous GUI button clicks (payment, deletion, messaging, disk formatting) before physical mouse/keyboard events are emitted. | ✅ |
| types.py | Core | Type definitions for Computer-Use Safe Enclave and Action Replay Audit Deck — Harness core security subsystem for computer-use desktop control, enforcing pre-action interception of high-risk clicks/keystrokes and emergency stop. | ✅ |
