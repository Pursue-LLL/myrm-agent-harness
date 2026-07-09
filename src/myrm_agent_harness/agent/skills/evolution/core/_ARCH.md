# core/

## Overview
Agent Skills Evolution Core module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package |   Init   | — |
| engine.py | Core | Skill evolution engine with 4 types (FIX/DERIVED/CAPTURED/OPTIMIZE_DESCRIPTION) + evidence-driven action routing. | ✅ |
| engine_batch_mixin.py | Core | `evolve_multiple_concurrent` batch mixin | ✅ |
| proposal_builder.py | Core | Proposal Builder with edit_summary extraction. | ✅ |
| types.py | Config | Data types including EvolutionType (4 variants), EvolutionProposal (with edit_summary, recommended_form, form_metadata). | ✅ |
