# core/

## Overview
Agent Skills Evolution Core module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package |   Init   | — |
| engine.py | Core | Skill evolution engine with 4 types (FIX/DERIVED/CAPTURED/OPTIMIZE_DESCRIPTION) + evidence-driven action routing + EvalCase regression gate + Improvement Gate (baseline comparison for DERIVED/evidence paths). | ✅ |
| engine_batch_mixin.py | Core | `evolve_multiple_concurrent` batch mixin | ✅ |
| eval_regression.py | Core | Non-blocking EvalCase regression gate. Runs bound EvalCases against candidate variants before LLM evaluation, applying score penalties for regressions. Exports `evaluate_content_assertions` (deterministic zero-LLM static-assertion pass-rate evaluator reused by the change-manifest prediction loop). | ✅ |
| proposal_builder.py | Core | Proposal Builder with edit_summary extraction and updated_eval_cases co-evolution sync. Edit-summary JSON parsed via `parse_llm_json_object` (robust against fences, prose, trailing commas). Also builds the falsifiable `change_manifest` (ChangePredictionManifest dict) at proposal finalization: baseline = static-assertion pass rate of original content, target = pass rate of proposed content; None when no eval_cases or for OPTIMIZE_DESCRIPTION. | ✅ |
| types.py | Config | Data types including EvolutionType (4 variants), EvolutionLayer, FailurePathology, GeneCellKey, GeneEliteRecord, SkillRecord (with eval_cases), EvolutionProposal (with edit_summary, updated_eval_cases, recommended_form, form_metadata, change_manifest). | ✅ |
| gene_bank.py | Core | MAP-Elites Gene Bank Archive maintaining quality-diversity Pareto elites across 2D (Layer x Pathology) grid to prevent evolution collapse. | ✅ |
