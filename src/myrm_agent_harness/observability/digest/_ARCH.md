# observability/digest/

## Overview
Team weekly digest and knowledge compounding newsletter engine. Aggregates multi-source team AI collaboration metrics, evaluates skill health indices, and renders GitHub/Feishu-compatible Markdown digests without LLM token overhead.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Re-exports TeamWeeklyDigest, SkillHealthEvaluator, TeamDigestRenderer, and metric types. | ✅ |
| `types.py` | Core | Foundation type contracts: SkillCompoundingMetrics, SkillHealthScore, TeamWeeklyDigest. | ✅ |
| `health_evaluator.py` | Core | SkillHealthEvaluator scoring the observed success rate weighted by evidence and classifying STAR/HEALTHY/AT_RISK/UNPROVEN/STALE. | ✅ |

## Key Dependencies

- `observability/metrics` (optional metric exposure)
