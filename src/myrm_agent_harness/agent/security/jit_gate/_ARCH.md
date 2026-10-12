# jit_gate/

## Overview

JIT Dual Verification Gate package.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | JIT Dual Verification Gate package | ✅ |
| gate.py | Core | JIT Dual Verification Gate enforcing physical asset integrity and policy recency — Executes two-level fast metadata short-circuit and deep SHA-256 comparison immediately prior to tool execution resumption. Prevents TOCTOU asset tampering and stale approval replay across time. | ✅ |
| models.py | Core | Data models for Content Hash Approval Binding and JIT Dual Verification — Immutable fingerprints capturing physical asset state at approval request time, and structured verification results for Just-In-Time execution-instant assertions. | ✅ |
