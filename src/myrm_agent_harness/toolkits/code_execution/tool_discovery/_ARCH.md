# tool_discovery/

## Overview
CLI tool auto-discovery module entry point. Provides get_cli_tools_context() one-stop API to detect

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | CLI tool auto-discovery module entry point. Provides get_cli_tools_context() one-stop API to detect | ✅ |
| catalog.py | Core | CLI tool catalog data layer. Maintains the list of CLI tools recognizable by Agent, organized by cat | ✅ |
| detector.py | Core | CLI tool detection engine. Scans tools in TOOL_CATALOG using shutil.which(), process-level cached, < | ✅ |
| types.py | Config | Data type layer for CLI tool discovery. Defines ToolDefinition (catalog entry) | ✅ |
