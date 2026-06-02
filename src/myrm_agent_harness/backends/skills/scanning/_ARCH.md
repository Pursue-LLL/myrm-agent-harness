# scanning/

## Overview
Skill content security scanning subsystem.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Skill content security scanning subsystem. | — |
| cache.py | Core | Scan result cache layer. Stores scan results in Volume (~/.myrm/skill_scans/) | ✅ |
| llm_auditor.py | Core | Semantic-level threat detection layer. Catches threats that regex patterns | ✅ |
| patterns.py | Core | Skill security scanner pattern definitions. | ✅ |
| scanner.py | Core | Skill content security scanner. Part of the framework's defense-in-depth. | ✅ |
| zip_extract.py | Core | Framework-level ZIP security utility. Business layers call this instead of | ✅ |
