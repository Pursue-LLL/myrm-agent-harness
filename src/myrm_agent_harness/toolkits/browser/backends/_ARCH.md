# backends/

## Overview
Storage backend abstraction layer for SessionVault. Defines interfaces via Protocol,

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Storage backend abstraction layer for SessionVault. Defines interfaces via Protocol, | ✅ |
| file_backend.py | Core | Local file system backend for SessionVault. Uses URL encoding for bijective | ✅ |
| protocols.py | Core | Defines the storage backend interface for SessionVault. Implements dependency | ✅ |
| storage_backend.py | Core | Cloud-native storage backend for SessionVault. Uses StorageProvider abstraction to support multiple  | ✅ |
