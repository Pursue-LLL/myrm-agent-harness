# qdrant/

## Overview
Qdrant Vector Store — built-in implementation.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Qdrant Vector Store — built-in implementation. | — |
| factory.py | Core | Qdrant factory module. Manages singleton instances for embedded mode and AsyncQdrantClient creation  | ✅ |
| filters.py | Core | Qdrant filter builder. Converts generic dict filter syntax to Qdrant SDK Filter objects. | ✅ |
| store.py | Core | Qdrant vector store implementation. Supports embedded and remote deployment modes with built-in retr | ✅ |
