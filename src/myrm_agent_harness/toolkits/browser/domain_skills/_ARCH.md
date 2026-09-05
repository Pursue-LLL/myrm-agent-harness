# domain_skills/

## Overview

Domain executable skills — manifest-based Python tool registry for repeated-domain
acceleration. Complements `SiteExperienceStore` (prompt-layer knowledge: traps, flows)
with an executable layer (Python tool scripts).

Navigate injection provides tool signatures (~20 tokens); actual scripts load on demand
via `run_site_tool` action in `browser_manage_tool`.

## Architecture

```
SiteExperience (prompt layer)     DomainSkill (executable layer)
├─ known_traps                    ├─ manifest.json
├─ successful_flows               ├─ tools/*.py
└─ navigate injection (~text)     └─ navigate injection (~signatures)
```

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports DomainSkillStore, DomainSkillManifest, DomainTool | ✅ |
| types.py | Core | DomainSkillManifest, DomainTool frozen dataclasses | ✅ |
| store.py | Core | DomainSkillStore: manifest loading, domain matching, builtin detection, singleton | ✅ |
| social_export.py | Utility | Social media data export helper (Excel .xlsx / UTF-8-SIG CSV) | ✅ |

| Submodule | Description |
|-----------|-------------|
| builtin/ | Bundled domain skill packs shipped with harness (x-com, bilibili, xiaohongshu, douyin). Static assets, not runtime data. |

## Allowed Dependencies

- Standard library only (json, pathlib, threading, importlib)
- No `agent/`, `runtime/`, `backends/` imports
