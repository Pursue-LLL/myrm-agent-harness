# sandbox_pause_resume/

## Overview

End-to-end suite orchestrating sandbox session pause, in-place resume, and snapshot branching.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Sandbox session pause, in-place resume, and snapshot branching package. | ✅ |
| `sandbox_pause_resume_engine.py` | Core | State-machine engine executing atomic pause, in-place resume, snapshot creation, and independent branching restoration. | ✅ |
| `sandbox_pause_resume_suite.py` | Core | High-level orchestration facade providing complete lifecycle management, integrity verification, and diagnostic auditing for sandbox sessions. | ✅ |
| `session_pause_types.py` | Types | Strongly typed contracts for sandbox session pause, resume, and snapshot restoration. | ✅ |
