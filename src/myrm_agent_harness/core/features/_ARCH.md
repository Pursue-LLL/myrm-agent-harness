# features/

## Overview
Feature Flags unified management system.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Feature Flags unified management system. | — |
| feature_set.py | Core | Runtime layer. Created once at startup via from_config(), stored as module singleton. | ✅ |
| registry.py | Core | Core infrastructure. Modules register their features at import/startup time. | ✅ |
| types.py | Config | Foundation layer. All types are frozen and immutable. | ✅ |
