# policy_generator/

## Overview
Natural language → SecurityConfig policy generator. Converts freeform policy descriptions into structured JSON via LLM with validation.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Policy generator public API. | — |
| explainer.py | Core | Human-readable explanation of generated SecurityConfig. | ✅ |
| parser.py | Core | LLM response parser — extracts structured SecurityConfig from raw output. | ✅ |
| prompts.py | Config | Prompt templates for policy generation. | ✅ |
| validator.py | Core | Schema validation for generated SecurityConfig. | ✅ |

## Key Dependencies

- `agent::security` (SecurityConfig types)
