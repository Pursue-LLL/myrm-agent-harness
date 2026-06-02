# relational/

## Overview
Relational Store — abstract interface and SQLite implementation.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Relational Store — abstract interface and SQLite implementation. | — |
| _converters.py | Internal | Row-to-model converters for SQLiteRelationalStore. | ✅ |
| base.py | Core | Relational store abstraction layer. Defines a backend-agnostic relational storage interface | ✅ |
| exceptions.py | Core | Relational store exceptions. | ✅ |
| sqlite_store.py | Core | Lightweight relational store backed by aiosqlite. WAL mode + connection reuse for | ✅ |
