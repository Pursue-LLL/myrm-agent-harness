# data_plane_defense/

## Overview

Data Plane Injection Defense and Hardened Data Fencing module. Harness core security subsystem inspired by Anthropic Commerce Agents (fencing.py & QuotedAsData).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Data Plane Injection Defense and Hardened Data Fencing module — Harness core security subsystem inspired by Anthropic Commerce Agents (fencing.py & QuotedAsData). | ✅ |
| hardened_fence.py | Core | Hardened Data Fence neutralizing forged turn markers, control characters, and indirect injections — Harness core security module inspired by Anthropic Commerce Agents (Fence.fence_payload & _strip_forged_turns). | ✅ |
| two_plane_detector.py | Core | Two-Plane Prompt Injection Detector differentiating user-plane from data-plane attacks — Harness core security module inspired by Anthropic Commerce Agents (Split injection into two cases). Detects indirect prompt injection planted in external data payloads. | ✅ |
| types.py | Core | Type definitions for Data Plane Injection Defense and Hardened Data Fencing — Harness core security subsystem inspired by Anthropic Commerce Agents (fencing.py & QuotedAsData). Defends against indirect prompt injections planted in tool results and third-party content. | ✅ |
