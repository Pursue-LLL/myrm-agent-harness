# paths/

Execution path SSOT, context file read tracking and file compression utilities.

| File | Role |
| --- | --- |
| `__init__.py` | Package entrypoint |
| `execution_paths.py` | Context/archive path constants and the context root in effect at call time |
| `access_tracking.py` | Records reads of context files for the current session so cleanup keeps files in use |
| `compression.py` | Generic file compression for storage optimization |
