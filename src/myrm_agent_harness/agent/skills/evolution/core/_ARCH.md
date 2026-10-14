# core/

## Overview
Agent Skills Evolution Core module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package |   Init   | — |
| engine.py | Core | Skill evolution engine with 4 types (FIX/DERIVED/CAPTURED/OPTIMIZE_DESCRIPTION) + EvalCase regression gate + Improvement Gate (baseline comparison for the DERIVED path). | ✅ |
| engine_batch_mixin.py | Core | `evolve_multiple_concurrent` batch mixin | ✅ |
| eval_regression.py | Core | Baseline-relative EvalCase regression gate. Guards only the cases the original content passes (a case the original already fails — e.g. a Python AST check on a Markdown SOP — cannot regress), penalises each guarded case a variant drops and hard-filters a variant that drops all of them. | ✅ |
| proposal_builder.py | Core | Proposal Builder with edit_summary extraction, updated_eval_cases co-evolution sync, and integrated security scanning. Edit-summary JSON parsed via `parse_llm_json_object` (robust against fences, prose, trailing commas). Drops variants the security scan rejects and records the scan summary of the rest. | ✅ |
| types.py | Config | Data types including EvolutionType (4 variants), EvolutionLayer, FailurePathology, GeneCellKey, GeneEliteRecord, SkillRecord (with eval_cases), EvolutionProposal (with edit_summary, updated_eval_cases, recommended_form, form_metadata, security_scan_summary). | ✅ |
| budget_governor.py | Core | Count-only capacity governor: pauses new-skill evolution (CAPTURED/DERIVED) once the active skill count reaches `max_skill_count` (default 50); repairs (FIX/OPTIMIZE_DESCRIPTION) are never blocked. Token volume is not capped here — skill bodies load on demand and context compaction budgets what a run actually loads. | ✅ |
| gene_bank.py | Core | MAP-Elites Gene Bank Archive maintaining quality-diversity Pareto elites across 2D (Layer x Pathology) grid to prevent evolution collapse. | ✅ |
