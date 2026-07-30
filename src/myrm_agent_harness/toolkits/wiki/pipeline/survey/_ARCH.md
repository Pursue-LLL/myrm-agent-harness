# survey/

## Overview
Zero-LLM compile structure survey before semantic extraction. Builds folder facets,
chunk sibling groups, and processing order. Fast-path skips survey for small shallow
vaults (≤15 raw files, folder depth ≤1).

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| types.py | DTO | `CompileSurveyContext`, `CompileSessionState`, `FacetSurvey`, fast-path constants | ✅ |
| builder.py | Core | `build_compile_survey()` — pending paths for facets; optional vault scope for fast-path gate | ✅ |
| __init__.py | Package | Public exports | — |

## Key Dependencies

- `core.structure::WikiStructure` (POS: vault filesystem layout)
- Consumed by `pipeline/compiler.py` (session orchestration, facet seed carry-forward)
