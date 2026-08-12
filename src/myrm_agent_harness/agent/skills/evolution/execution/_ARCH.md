# execution/

## Overview
Agent Skills Evolution Execution module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package |   Init   | — |
| dependency.py | Core | Skill dependency management for evolution safety — `parse_skill_dependencies` extracts skill/tool edges from YAML frontmatter `dependencies` and body tool markers (`@tool_use`, `uses:`, `*_tool` / `*_api` / `*_client` names), feeding the persistent `skill_dependencies` graph. | ✅ |
| evaluator.py | Core | Batch Evaluator for Skill Evolution. Description scoring parsed via `parse_llm_json_object` (robust against fences, prose, bare control chars, trailing commas). | ✅ |
| executor_context.py | Core | Executor Context Manager for Evolution System | ✅ |
| sandbox_validator.py | Core | Sandbox validation for evolved skills. Integrates syntax checks and AST static analysis. | ✅ |
| tool_selector.py | Core | Tool Selector for Evolution System | ✅ |
| tool_wrapper.py | Core | Tool Wrapper for Evolution System | ✅ |

## Key Dependencies

- `toolkits`
