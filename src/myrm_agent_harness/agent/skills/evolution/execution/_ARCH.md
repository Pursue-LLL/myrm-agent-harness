# execution/

## Overview
Agent Skills Evolution Execution module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package |   Init   | — |
| dependency.py | Core | Skill dependency management for evolution safety. | ✅ |
| evaluator.py | Core | Batch Evaluator for Skill Evolution. | ✅ |
| executor_context.py | Core | Executor Context Manager for Evolution System | ✅ |
| sandbox_validator.py | Core | Sandbox validation for evolved skills. Integrates syntax checks and AST static analysis. | ✅ |
| tool_selector.py | Core | Tool Selector for Evolution System | ✅ |
| tool_wrapper.py | Core | Tool Wrapper for Evolution System | ✅ |

## Key Dependencies

- `toolkits`
