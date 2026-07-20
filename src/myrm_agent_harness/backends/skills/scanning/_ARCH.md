# scanning/

## Overview
Skill content security scanning — regex patterns, Python AST analysis, package manifest audit, LLM semantic audit, persistent cache, and secure ZIP extraction.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports scanning APIs for agent and backend consumers. | — |
| ast_analyzer.py | Core | AST-level Python security analysis (eval, subprocess, pickle, etc.). | ✅ |
| archive_security.py | Core | Canonical archive security contract (error code/message), executable signature detection, and structured logs/metrics. | ✅ |
| cache.py | Core | Persistent scan result cache under MYRM data dir (~/.myrm/skill_scans/). | ✅ |
| llm_auditor.py | Core | LLM-based semantic threat detection beyond regex/AST coverage. | ✅ |
| package_audit.py | Core | package.json supply-chain audit (install scripts, suspicious deps). | ✅ |
| patterns.py | Core | Regex pattern groups for 26 threat categories. | ✅ |
| scanner.py | Core | Multi-file skill directory scanner and scan summary aggregation. | ✅ |
| zip_extract.py | Core | Secure ZIP extraction (compression ratio / entry-count / total-size limits, symlink/path traversal defense, executable-binary rejection). | ✅ |

## Key Dependencies

- `backends.skills.types` (SecurityScanSummary, SecurityFindingDetail)
