# universal_mcp_bridge/

## Overview
Universal MCP Memory Bridge & External Client Config Generator: stdio/SSE dual-mode MCP server integration, plug-and-play client configuration generator (Claude Code, Cursor, VSCode/Cline, CodeBuddy, Hermes), unified user_id lease anchor, and instant bidirectional memory convergence.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public facade of the universal mcp bridge subsystem. | ✅ |
| `bridge_runner.py` | Core | Core bridge coordinator providing standard memory tool definitions and execution dispatch for external clients. | ✅ |
| `config_generator.py` | Core | Generates plug-and-play MCP configuration snippets for external AI tools. | ✅ |
| `types.py` | Types | Typed data contracts for the universal mcp bridge subsystem. | ✅ |

## Key Dependencies

- None (self-contained within the package and the standard library)
