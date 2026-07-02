# code_execution/

## Overview
Code execution toolkit entry point. Aggregates execution configuration, executor implementations,

Detailed design: [EXECUTION_SYSTEM.md](EXECUTION_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Code execution toolkit entry point. Aggregates execution configuration, executor implementations, | ✅ |
| config.py | Config | Code execution configuration layer. Defines execution modes, network policies, and runtime settings | ✅ |
| code_detector.py | Core | Python vs Bash code type detector. Delegates ``python -c`` extraction to ``python_extractor`` SSOT. | ✅ |
| env_probe.py | Core | Python toolchain probe. Detects python3/pip/PEP-668/uv status; consumed by bash_code_execute_tool.py (tool description) and platform.py (`<environment>` system prompt tag). | ✅ |
| factory.py | Core | Code executor factory. Creates LocalExecutor for in-container code execution based on configuration. | ✅ |
| interceptor.py | Core | ExecutionInterceptor Protocol — hooks before destructive sandbox actions (file write, rm, sed) | ✅ |
| platform.py | Core | Cross-platform runtime detection, shell configuration, and unified `<environment>` system prompt tag (OS + Shell + Python toolchain + VNC visual desktop). | ✅ |
| python_extractor.py | Core | Quote-aware Python extraction from bash commands; SSOT for code_detector, SkillExecutor, PTC verifier. | ✅ |

| Submodule | Description |
|-----------|-------------|
| executors/ | Executors module for Agent-in-Sandbox mode. |
| ptc/ | Programmatic Tool Calling — LLM scripts invoke agent tools via UDS/TCP RPC. |
| sandbox/ | OS-level process sandbox for local/desktop execution. |
| security/ | Execution security — shell command analysis, blacklists, and validators. |
| session/ | Persistent Session Module (with Auto-Tee, OOM & Disk Quota protection) |
| tool_discovery/ | CLI tool auto-discovery module entry point. Provides get_cli_tools_context() one-stop API to detect |
| utils/ | Code execution utilities. |
| workspace/ | Session workspaces rooted at explicit host-provided aggregate directory (`merged_context[\"workspaces_storage_root\"]` consumed by Harness `WorkspaceService`). |
