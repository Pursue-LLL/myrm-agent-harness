# drift_defense/

## Overview
Ground Truth Priority & Code Drift Stale Memory Defense: zero-LLM reference extraction, sub-5ms physical presence & symbol AST validation, prompt-level stale warning decoration, and confidence decay.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public entry point for ground truth priority and code drift stale memory defense. | ✅ |
| `decorator.py` | Core | Prompt decorator and confidence decay applier for stale memories. | ✅ |
| `detector.py` | Core | High-performance pre-injection ground truth drift detector. | ✅ |
| `reference_extractor.py` | Core | Zero-LLM fast regular expression extractor for file paths and code symbols. | ✅ |
| `tool.py` | Agent Tool | Agent-facing LangChain tool for memory drift ground truth defense. | ✅ |
| `types.py` | Types | Type definitions for ground truth priority and memory drift stale defense. | ✅ |

## Key Dependencies

- External libraries: `pydantic`, `langchain_core`
