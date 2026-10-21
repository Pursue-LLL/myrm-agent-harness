# network/

## Overview
Local loopback proxy bypass, probe validation, and Surge/Clash self-healing suite.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Local loopback proxy bypass, probe validation, and Surge/Clash self-healing suite. | — |
| `loopback_probe.py` | Core | Asynchronous loopback connectivity probe and proxy interception detector. | ✅ |
| `loopback_types.py` | Core | Strongly typed data contracts for loopback proxy bypass and self-healing. | ✅ |
| `proxy_environment_guard.py` | Core | Loopback network proxy environment guard and static bypass injector. | ✅ |
| `surge_clash_healer.py` | Core | Surge/Clash self-healing rule generator and transparent HTTP bypass engine. | ✅ |
| `ipc_socket.py` | Core | IPC socket path and permission policy shared by the MCP transport. — default_ipc_socket_path: Per-process socket path inside a private directory.; SOCKET_DIR_MODE / SOCKET_FILE_MODE: Owner-only modes for the dir and socket. | ✅ |
