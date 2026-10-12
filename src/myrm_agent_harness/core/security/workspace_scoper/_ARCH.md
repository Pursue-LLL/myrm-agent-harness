# workspace_scoper/

## Overview

Package exports for Workspace Scoper and Cross-Contamination Guard. Harness core security module for per-task workspace sandboxing and leakage auditing.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Package exports for Workspace Scoper and Cross-Contamination Guard — Harness core security module for per-task workspace sandboxing and leakage auditing. | ✅ |
| guard.py | Core | Workspace Contamination Guard enforcing task-level directory confinement and audit logging — Harness core security module inspired by WorkBuddy task directory isolation. Guarantees strict containment for task workspaces, preventing cross-task leaks. | ✅ |
| types.py | Core | Type definitions for Per-Task Workspace Scoping and Cross-Contamination Guard — Harness core security module inspired by WorkBuddy task workspace sandboxing. Isolates file system access on a per-task basis, preventing cross-contamination between sensitive business materials (invoices, contracts, code repositories). | ✅ |
