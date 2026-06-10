# pipeline/

## Overview
Agent Skills Evolution Pipeline module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package |   Init   | — |
| analyzer.py | Core | Lightweight execution analysis for skill evolution decisions. | ✅ |
| frustration_detector.py | Core | Frustration signal detector. Zero-LLM regex detection of user style/format/workflow frustration signals (中英双语). Routes signals to DERIVED skill evolution. | ✅ |
| patch.py | Core | Patch application system for skill evolution. | ✅ |
| screener.py | Core | Evolution screening pipeline. Implements multi-phase checks including static error interception, GUI-First force retry, and LLM confirmation. | ✅ |
| structured_extractor.py | Core | Provides SkillCaptureResult (with form routing: skill/cron_job/skip), StructuredExtractor. | ✅ |
| trace_analyzer.py | Core | Trace Analyzer for Skill Evolution. Provides progressive disclosure analysis. | ✅ |
| evidence_aggregator.py | Core | Aggregates execution analyses by skill into SkillEvidenceGroup objects for evidence-driven evolution. | ✅ |
| variant_generator.py | Core | Variant Generator with modular prompt assembly (editing principles, hard constraints, conservative editing, failure attribution, preference embedding) and trap injection. Supports FIX/DERIVED content variants, preference-driven DERIVED variants, and OPTIMIZE_DESCRIPTION description-only variants. | ✅ |

## Key Dependencies

- `backends`
- `utils`
