# tests/architecture/

## Overview

CI architecture gates: enforce layer boundaries and release wheel packaging invariants.

## File Index

| File | Role | Description |
|------|------|-------------|
| `test_toolkits_agent_boundary.py` | Gate | AST scan: `toolkits/` must not import `myrm_agent_harness.agent` |
| `test_wheel_browser_assets.py` | Gate | `uv build` wheel must include `toolkits/browser/assets/ad_domains.txt` (≥3500 domains) |

## Running

```bash
pytest tests/architecture/ -m architecture
```
