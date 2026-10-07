# codegraph/

## Overview
CodeGraph Memory Asset & Pre-Modification Impact Analysis Engine: AST symbol topology extraction (classes, methods, functions, inheritance, calls), in-memory & SQLite persistent store with incremental synchronization, multi-hop BFS blast radius evaluation, and agent-facing risk prevention tool.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | CodeGraph memory asset and impact analysis engine package. | ✅ |
| `ast_parser.py` | Core | AST-based code symbol and topology dependency extractor. | ✅ |
| `impact_analyzer.py` | Core | Impact analysis engine evaluating modification blast radius and risk levels. | ✅ |
| `store.py` | Core | CodeGraph memory store maintaining symbol topology and caller inversions. | ✅ |
| `tool.py` | Core | Agent-facing meta tool for evaluating code modification impact. | ✅ |
| `types.py` | Types | Domain models and type definitions for CodeGraph memory assets and impact analysis. | ✅ |

## Key Dependencies

- None (self-contained within the package and the standard library)
