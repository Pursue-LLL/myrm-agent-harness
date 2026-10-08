# hierarchical_rules/

## Overview

Subsystem for hierarchical rules directory decoupling, glob-scoped dynamic rule matching, single-source transclusions (`@path`), and 200-line attention dilution defense. Replaces monolithic `AGENTS.md` by partitioning rules across user global, project shared, and local override tiers, while selectively mounting domain rules based on active workspace file paths.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Hierarchical rules directory and glob-scoped dynamic rule matcher package entry point. | ✅ |
| `attention_dilution_guard.py` | Core | Guardrail enforcing 200-line attention limits with risk scoring and split suggestions. | ✅ |
| `glob_rule_matcher.py` | Core | Frontmatter parser and path glob pattern matching engine for dynamic scoping. | ✅ |
| `hierarchical_rules_suite.py` | Facade | Unified facade managing 3-tier precedence, glob activation, transclusions, and audits. | ✅ |
| `rule_transclusion_engine.py` | Core | Recursive inline `@path` transclusion engine with cycle prevention. | ✅ |
| `rule_types.py` | Types | Domain contracts, rule descriptors, match outcomes, and configuration options. | ✅ |
