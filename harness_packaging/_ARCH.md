# harness_packaging/

## Overview
Build and release tooling for proprietary distribution: core IP manifest, platform detection, Nuitka compilation, and release wheel source stripping.

## File Index

| File | Role | Description |
|------|------|-------------|
| core_manifest.yaml | Core | List of core IP modules compiled to `.so` |
| manifest.py | Core | Manifest loader and path validation |
| platforms.py | Core | Platform key detection (six platforms) |
| pypi_index.py | Core | PyPI JSON probes (package exists, compiled-core extra) |
| release.py | Core | Strip manifest `.py` in-place (PEP 427 compliant) |
| assemble.py | Core | Unified production wheel assembly + venv install + post-install verify |
| integrity.py | Core | Manifest import paths for dev/CI helpers |

## Scripts

| Script | Role |
|--------|------|
| `scripts/build_core.py` | Nuitka compile + platform core wheel (static force-include) |
| `scripts/build_release_wheel.py` | Release wheel via `uv build` + strip manifest `.py` |
| `scripts/assemble_production.py` | Full production pipeline + optional `--install` |
| `scripts/verify_release_tag.py` | Assert `refs/tags/v*` matches `project.version` before wheel builds |
| `scripts/verify_pypi_publish.py` | Post-upload PyPI index gate (7 packages + compiled-core extra) |

## Key Dependencies

- `nuitka` (build group only)
- `PyYAML` (manifest parsing)

## PyPI

Tag `v*` → `.github/workflows/publish-pypi.yml` uploads release + six platform core wheels.

## System Design

See [DISTRIBUTION_SYSTEM.md](DISTRIBUTION_SYSTEM.md).
