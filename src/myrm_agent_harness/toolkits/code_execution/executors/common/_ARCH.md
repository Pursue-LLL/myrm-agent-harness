# common/

## Overview
Common executor components.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Common executor components. | — |
| command_rewriter.py | Core | Command rewriting service. | ✅ |
| error_handler.py | Core | Execution error handling decorator. | ✅ |
| exit_classify.py | Core | Non-zero exit code semantic classifier. | ✅ |
| execution_helper.py | Core | Execution helper utilities. | ✅ |
| executor_utils.py | Core | Common utility functions for code executors. | ✅ |
| file_scanner.py | Core | Generated files scanner. | ✅ |
| subprocess_guard.py | Core | Single-responsibility guard. Does NOT replace the richer timeout logic | ✅ |
| venv_manager.py | Core | Virtual environment management service. | ✅ |
| wrapper_script.py | Core | Unified execution wrapper script. | ✅ |

## Key Dependencies

- `utils`
