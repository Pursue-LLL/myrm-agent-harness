# queuefs/

## Overview

Asynchronous QueueFS engine managing named semantic tasks across sequential DAG stages.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Package facade for queuefs. | ✅ |
| `engine.py` | Core | Asynchronous QueueFS engine managing named semantic tasks across sequential DAG stages. | ✅ |
| `lock.py` | Core | Raised when lock acquisition fails due to concurrent lease conflicts. | ✅ |
| `models.py` | Types | Types and models for queuefs. | ✅ |
