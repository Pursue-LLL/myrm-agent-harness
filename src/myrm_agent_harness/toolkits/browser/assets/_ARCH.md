# browser/assets/

## Overview

Bundled static data files for the browser toolkit. Loaded at runtime via `importlib.resources` (see `ad_domains.py`).

## File Index

| File | Role | Description | Shipped in wheel |
|------|------|-------------|------------------|
| __init__.py | Package | Bundled static assets package marker | — |
| `ad_domains.txt` | Data | Peter Lowe ad/tracker domain blocklist (~3500 lines). Consumed by `domain_filter.py`. | Yes — `[tool.hatch.build.targets.wheel.force-include]` in `pyproject.toml` |

## Packaging

Release wheels must include `ad_domains.txt`. Guard: `tests/architecture/test_wheel_browser_assets.py`.
