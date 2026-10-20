# utils/

## Overview
Code execution utilities.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Code execution utilities. | — |
| log_distiller.py | Core | High-signal terminal log distiller for long-running build, execution, and deployment tasks (`DistilledLogResult`, `TerminalLogDistiller`) | ✅ |
| port_sniffer.py | Core | Dev-server listening-port sniffer for execution logs (`DiscoveredPort`, `sniff_ports_from_text`) | ✅ |
| stderr_filter.py | Core | Fine-grained line-by-line stderr stream classification and filtering pipeline (`filter_stderr_text`, `classify_stderr_line`) | ✅ |
| workspace_path.py | Core | Workspace path resolver with intelligent auto-detection. | ✅ |
