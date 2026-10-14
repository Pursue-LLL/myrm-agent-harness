# optimization/

## Overview
Skill Optimization Toolkit

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Skill Optimization Toolkit | — |
| ab_test.py | Test | A/B test starter. Creates the RUNNING ABTestResult for a candidate version; collecting samples and deciding the winner is owned by the host application. | ✅ |
| config.py | Config | Skill optimization configuration for A/B testing, LLM call tuning, and security. | ✅ |
| event_adapter.py | Core | EventLog adapter (framework layer). Implements the SkillExecutionProvider protocol for event-driven  | ✅ |
| event_emitter.py | Core | Event system (framework layer). Decouples inter-component notifications via publish-subscribe patter | ✅ |
| observability.py | Core | Lightweight observability support with zero external dependencies. Provides MetricsCollector, Timer, | ✅ |
| optimizer.py | Core | Skill optimizer core engine. Orchestrates the full optimization pipeline: data collection, analysis, | ✅ |
| protocols.py | Core | Storage and execution-provider protocols (framework defines, server implements) | ✅ |
| quality_calculator.py | Core | Quality score calculator. Computes 5-dimension quality scores from raw execution samples. | ✅ |
| result_comparator.py | Core | Shadow test result comparator. Provides accurate result comparison for the observation feedback loop | — |
| security.py | Core | Multi-layer skill security validator. Prevents malicious code in LLM-generated skills. | ✅ |
| types.py | Config | Skill optimization system core type definitions. Provides type-safe data structures and protocol int | ✅ |

## Key Dependencies

- `backends`
- `observability`
- `toolkits`
