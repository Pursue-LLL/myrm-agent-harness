# toolchains/

## Overview
Isolated portable toolchain manager for external CLI agents (Node.js download, npm CLI install) without polluting the host OS environment.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports ToolchainManager | — |
| manager.py | Core | ToolchainManager — download, install, resolve CLI binaries under `~/.myrm-agent/toolchains` | — |

## Module Dependencies

- Pure stdlib + asyncio; used by `toolkits/acp/` runtime backends

## Division vs toolkits/acp/

| Package | Responsibility |
|---------|----------------|
| `toolkits/acp/` | ACP protocol server, runtime, permission, event bus |
| `toolchains/` | Isolated Node/npm environment for CLI-based ACP backends |
