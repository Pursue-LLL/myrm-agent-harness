# core/

## Overview
Agent Skills Evolution Core module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package |   Init   | — |
| engine.py | Core | Skill evolution engine with 4 types (FIX/DERIVED/CAPTURED/OPTIMIZE_DESCRIPTION) + evidence-driven action routing + EvalCase regression gate + Improvement Gate (baseline comparison for DERIVED/evidence paths). | ✅ |
| engine_batch_mixin.py | Core | `evolve_multiple_concurrent` batch mixin | ✅ |
| eval_regression.py | Core | Non-blocking EvalCase regression gate. Runs bound EvalCases against candidate variants before LLM evaluation, applying score penalties for regressions. | ✅ |
| proposal_builder.py | Core | Proposal Builder with edit_summary extraction and updated_eval_cases co-evolution sync. | ✅ |
| types.py | Config | Data types including EvolutionType (4 variants), SkillRecord (with eval_cases), EvolutionProposal (with edit_summary, updated_eval_cases, recommended_form, form_metadata). | ✅ |
