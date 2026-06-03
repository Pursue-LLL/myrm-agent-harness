# Proprietary Distribution System

## Design Goal

Ship `myrm-agent-harness` as a **closed-source Python package** that third-party frameworks can import and extend, while hiding core IP — mirroring Claude Code's npm shell + native binary pattern.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Consumer (myrm-agent-server / third-party framework)       │
│  from myrm_agent_harness.api import create_skill_agent      │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  myrm-agent-harness (release wheel)                           │
│  ├── api/*.py          ← public, readable                   │
│  └── agent/.../*.py    ← stripped for manifest modules      │
└──────────────────────────┬──────────────────────────────────┘
                           │ pip install [compiled-core]
┌──────────────────────────▼──────────────────────────────────┐
│  myrm-agent-harness-core-{platform} (platform wheel)        │
│  └── myrm_agent_harness/**/**.cpython-313-*.so              │
└─────────────────────────────────────────────────────────────┘
```

## Core Components

| Component | Path | Role |
|-----------|------|------|
| Public API | `src/myrm_agent_harness/api/` | Stable import surface (factory, Protocol, DTO) |
| Core manifest | `harness_packaging/core_manifest.yaml` | Modules compiled to native extensions |
| Platform detection | `harness_packaging/platforms.py` | Six supported platform keys |
| Core build | `scripts/build_core.py` | Nuitka `--module` + static hatch `force-include` wheel |
| Release build | `scripts/build_release_wheel.py` | `uv build --wheel` + strip manifest `.py` |
| Production assemble | `scripts/assemble_production.py` | Core + release + optional `--install` |
| Post-install verify | `src/myrm_agent_harness/_verify_distribution.py` | Console script `verify-harness-distribution` |
| Distribution probe | `src/myrm_agent_harness/_distribution.py` | `source` vs `compiled` + fail-closed + core/release version match |

## Build Pipeline

```bash
uv sync --group build
.venv/bin/python scripts/assemble_production.py
verify-harness-distribution
```

**Not PyArmor/obfuscation.** Core IP in `core_manifest.yaml` is compiled with **Nuitka** to native `.so` / `.pyd`.

## Consumer Install (PyPI)

`pyproject.toml` includes the `compiled-core` extra (platform markers). Server and OSS consumers install:

```bash
pip install 'myrm-agent-harness[file-parsers,...,compiled-core]==0.1.0'
```

Or in `myrm-agent-server` after `uv sync` (PyPI, default for this repo).

Editable dev: `pip install -e /path/to/myrm-agent-harness[...]` when harness source is checked out locally.

## Development Mode

Editable install ships all `.py` source. `_distribution.get_distribution_mode()` returns `source`.

## Docker (Server Runtime)

| File | Audience | Harness source |
|------|----------|----------------|
| `myrm-agent-server/docker/Dockerfile.official` | Source-built wheels | `assemble_production.py` in-image |
| `myrm-agent-server/Dockerfile` | PyPI consumers | `read_harness_pypi_spec.py` + `uv pip install` |

```bash
# OSS (server repo root context)
docker build -t myrm-server myrm-agent-server/

# Official (harness + server trees available; build context = agent repo root)
docker build -f myrm-agent-server/docker/Dockerfile.official -t myrm/runtime:local .
```

## PyPI Publish

Tag `v*` (e.g. `v0.1.0rc1`, aligned with `project.version`) in **myrm-agent-harness** triggers `.github/workflows/publish-pypi.yml`:

1. Matrix build six `myrm-agent-harness-core-*` wheels
2. Build stripped release wheel
3. Upload all to PyPI (`skip-existing`)

Release automation verifies PyPI packages exist before refreshing server `uv.lock`.

## CI

| Workflow | Role |
|----------|------|
| `publish-pypi.yml` | Tag release → PyPI (release + 6 core wheels); matrix from `.github/core-platform-matrix.json` |
| `build-core-wheels.yml` | Dev/matrix core wheel artifacts (same shared matrix; optional `platform` input) |
| `boundary-check.yml` | Architecture + distribution tests |

## References

- [FRAMEWORK_DESIGN_PRINCIPLES.md §5](../FRAMEWORK_DESIGN_PRINCIPLES.md)
