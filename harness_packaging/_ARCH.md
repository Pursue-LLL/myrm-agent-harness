# harness_packaging/

## Overview
Build and release tooling for proprietary distribution: core IP manifest, platform detection, Nuitka compilation, and release wheel source stripping.

## File Index

| File | Role | Description |
|------|------|-------------|
| core_manifest.yaml | Core | Core IP directories + explicit modules (SSOT) |
| manifest.py | Core | Manifest loader: explicit modules + directory expansion |
| codegen.py | Core | Codegen `_core_ip_manifest.py` + compiled-core version pins |
| platforms.py | Core | Platform keys + PEP508 markers; runtime detection via `_runtime_platform` |
| pypi_index.py | Core | PyPI JSON probes (package exists, compiled-core extra) |
| release.py | Core | Strip manifest `.py` in-place (PEP 427 compliant) |
| assemble.py | Core | Unified production wheel assembly + venv install + post-install verify |
| integrity.py | Core | Manifest import paths for dev/CI helpers |

## Scripts

| Script | Role |
|--------|------|
| `scripts/sync_distribution_metadata.py` | Regenerate `_core_ip_manifest.py` + pyproject compiled-core pins |
| `scripts/build_core.py` | Nuitka compile + platform core wheel (static force-include) |
| `scripts/build_release_wheel.py` | Release wheel via `uv build` + strip manifest `.py` |
| `scripts/assemble_production.py` | Full production pipeline + optional `--install` |
| `scripts/verify_release_tag.py` | Assert `refs/tags/v*` matches `project.version` before wheel builds |
| `scripts/verify_pypi_publish.py` | Post-upload PyPI index gate (release + 8 core wheels + compiled-core extra) |

## Key Dependencies

- `nuitka` (build group only)
- `PyYAML` (manifest parsing)

## PyPI

Tag `v*` → `.github/workflows/publish-pypi.yml` uploads release + eight platform core wheels.

## System Design

See [DISTRIBUTION_SYSTEM.md](DISTRIBUTION_SYSTEM.md).
