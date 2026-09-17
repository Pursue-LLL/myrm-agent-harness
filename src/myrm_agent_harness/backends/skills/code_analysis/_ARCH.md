# code_analysis/

## Overview
Static code analysis backend — AST-level symbol dependency extraction and dead-code topology reporting for codebase debloating.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Package exports for the AST dependency analyzer. | ✅ |
| topology.py | Core | Static AST dependency and dead-code topology analyzer (`SymbolDefinition`, `CodebaseTopologyReport`, `PythonAstTopologyScanner`). | ✅ |

## POS
Analysis primitive layer; consumed by its own test suite. Read-only, no runtime agent coupling.
