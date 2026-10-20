# concurrency/

## Overview
Concurrency infrastructure.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Concurrency infrastructure. — StateReducer; ConcurrencyLimiter | — |
| `limiter.py` | Core | Concurrency limiter for parallel execution. — ConcurrencyLimiter: Async semaphore wrapper for limiting concurrent LLM calls. | ✅ |
| `reducer.py` | Core | State reducer for parallel execution. — StateReducer: Thread-safe/Async-safe state reducer for merging parallel execution results. | ✅ |
