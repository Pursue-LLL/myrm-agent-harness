# paths/

Execution path SSOT, context file read tracking and file compression utilities.

| File | Role |
| --- | --- |
| `__init__.py` | Package entrypoint |
| `execution_paths.py` | Persistent/context/memories roots derived from `MYRM_PERSISTENT_ROOT` (default `/persistent`) on every call, session context layout, path sanitizers |
| `archive_paths.py` | Compacted tool-output archive paths: random and content-addressed outputs, metadata/restore-map sidecars, sidecar candidates for the path forms tools see |
| `access_tracking.py` | Records reads of context files for the current session so cleanup keeps files in use |
| `compression.py` | Generic file compression for storage optimization |
