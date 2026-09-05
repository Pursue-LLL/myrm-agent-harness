# scanning/

## Overview
Skill content security scanning — regex patterns, Python AST analysis, package manifest audit, dependency extraction, offline known-compromised package advisories matching, OSV.dev batch vulnerability intelligence with TTL caching, advisory acknowledgment governance, LLM semantic audit, persistent cache, and secure ZIP extraction.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports scanning APIs for agent and backend consumers. | — |
| ast_analyzer.py | Core | AST-level Python security analysis (eval, subprocess, pickle, etc.). | ✅ |
| archive_security.py | Core | Canonical archive security contract (error code/message), executable signature detection, and structured logs/metrics. | ✅ |
| cache.py | Core | Persistent scan result cache under MYRM data dir (~/.myrm/skill_scans/). | ✅ |
| dependency_extractor.py | Core | Manifest and lockfile dependency extractor for package.json (npm), requirements.txt (PyPI), pyproject.toml (PyPI), uv.lock (PyPI), bun.lock (npm), and package-lock.json (npm). | ✅ |
| llm_auditor.py | Core | LLM-based semantic threat detection beyond regex/AST coverage. Parses the finding object via `parse_llm_json_object` (robust against fences, prose, bare control chars, trailing commas). | ✅ |
| osv_scanner.py | Core | Online OSV.dev batch vulnerability intelligence scanner with query batching and graceful offline fallback. | ✅ |
| package_audit.py | Core | package.json supply-chain audit (install scripts, suspicious deps, in-memory lifecycle script gate, entry point artifact physical reachability & non-empty integrity verification). | ✅ |
| patterns.py | Core | Regex pattern groups for 26 threat categories. | ✅ |
| rescan_engine.py | Core | Installed skill multi-layer rescan orchestrator with AdvisoryAckRegistry governance and auto-quarantine disposition. | ✅ |
| scanner.py | Core | Multi-file skill directory scanner and scan summary aggregation. | ✅ |
| security_advisories.py | Core | Offline known-compromised package advisories catalog for zero-latency, deterministic detection of notorious malware. | ✅ |
| vuln_cache.py | Core | Vulnerability scan result cache with 24-hour TTL and disk persistence. | ✅ |
| zip_extract.py | Core | Secure ZIP extraction (compression ratio / entry-count / total-size limits, symlink/path traversal defense, executable-binary rejection). | ✅ |

## Key Dependencies

- `backends.skills.types` (SecurityScanSummary, SecurityFindingDetail)
