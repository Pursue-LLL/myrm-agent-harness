# Context Virtual File System (CVFS) Architecture

## Overview
This package implements the Context Virtual File System Protocol and Deterministic Exploration Suite (Item 77), benchmarked against ByteDance Volcano Engine OpenViking `viking://` specifications. It resolves black-box vector search hallucinations by providing POSIX directory tree hierarchy, deterministic `ls`/`tree`/`read`/`find` navigation, and three-layer namespace decoupling (`resources/`, `user/`, `artifacts/`).

## Core Modules
- `models.py`: Strongly typed primitives (`VFSNodeType`, `VFSNodeInfo`, `VFSReadResult`, `VFSTreeNode`, `VFSTreeResult`).
- `protocol.py`: `CVFSProtocol` managing `ctx://` canonical URI normalization, directory traversal protection, and namespace validation.
- `store.py`: `CVFSRegistryStore` providing SQLite tree index persistence and WAL connection management.
- `vfs.py`: `ContextVirtualFileSystem` core facade orchestrating directory creation, file reads/writes, ASCII tree rendering, and keyword search.
- `tools.py`: `ContextVFSExploreTools` providing agent-facing meta-tool definitions (`ctx_ls`, `ctx_tree`, `ctx_read`, `ctx_find`, `ctx_write`).
- `__init__.py`: Public package exports conforming to harness conventions.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Package facade for cvfs. | ✅ |
| `models.py` | Types | Types and models for cvfs. | ✅ |
| `protocol.py` | Core | Protocol helper for canonical ctx:// URI parsing and validation. | ✅ |
| `store.py` | Core | SQLite-backed metadata and content registry for Context Virtual File System. | ✅ |
| `tools.py` | Core | Agent meta-tools exposing deterministic exploration across Context Virtual File System. | ✅ |
| `vfs.py` | Core | Unified Context Virtual File System delivering deterministic exploration and asset access. | ✅ |
