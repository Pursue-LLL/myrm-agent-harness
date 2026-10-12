# dev_sandbox_fence/

## Overview

Zero-Production-Write Dev Sandbox and Synthetic Data Fence Suite.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Zero-Production-Write Dev Sandbox and Synthetic Data Fence Suite | ✅ |
| branch_and_directory_gate.py | Core | Isolated Branch and Directory Whitelist Gate for Dev Sandbox | ✅ |
| fence_engine.py | Core | Dev Sandbox Fence Engine integrating SQL write blocking, synthetic data, and branch gates | ✅ |
| sql_write_interceptor.py | Core | SQL Write Operation Interceptor preventing database mutations in Dev Sandbox | ✅ |
| synthetic_data_fence.py | Core | Approved Synthetic Data Fence redirecting production data requests to masked replicas | ✅ |
| types.py | Core | Data types and schemas for Zero-Production-Write Dev Sandbox and Synthetic Data Fence | ✅ |
