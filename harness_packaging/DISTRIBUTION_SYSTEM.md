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
                           │ pip install
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
| Post-install verify | `src/myrm_agent_harness/_verify_distribution.py` | Console script `verify-harness-distribution` (Docker / CI / Tauri) |
| Distribution probe | `src/myrm_agent_harness/_distribution.py` | `source` vs `compiled` + fail-closed + core/release version match |
| Version sync | `harness_packaging/version.py` | Read harness version; core wheel pins `myrm-agent-harness=={version}` |
| Compiled-core metadata | `harness_packaging/compiled_core_extra.py` | Inject `compiled-core` optional-deps into release wheel at build time |

## Build Pipeline

```bash
# Full production (core .so + stripped release wheel)
uv sync --group build
.venv/bin/python scripts/assemble_production.py

# Install into server venv (Tauri sidecar)
.venv/bin/python scripts/assemble_production.py --install ../myrm-agent-server

# Verify production install
verify-harness-distribution
# Editable dev install
python -m myrm_agent_harness._verify_distribution
```

**Not PyArmor/obfuscation.** Core IP in `core_manifest.yaml` is compiled with **Nuitka** to native `.so` / `.pyd`; readable `.py` for those modules is removed from the release wheel.

## Consumer Install

**Source is private; wheels are public on PyPI** (`myrm-agent-harness` + `myrm-agent-harness-core-{platform}`).

OSS server CI, Docker, Tauri sidecar builds, and local production-like installs:

```bash
MYRM_HARNESS_INSTALL_MODE=pypi ./scripts/dev/install_harness_dev.sh
```

Pin version in `myrm-agent-server/pyproject.toml` (includes `compiled-core` extra for platform core package).

Publish from private harness repo: push tag `v*` → `.github/workflows/publish-pypi.yml`.

Local harness development (editable or source build):

```bash
MYRM_HARNESS_INSTALL_MODE=source ./scripts/dev/install_harness_dev.sh
MYRM_HARNESS_EDITABLE=1 ./scripts/dev/install_harness_dev.sh
```

Direct wheel install (after publishing):

```bash
pip install 'myrm-agent-harness[compiled-core]==0.1.0rc1'
```

Server monorepo CI uses **pypi mode** (no private repo clone). Production Docker/Tauri
sidecar builds install from PyPI via `scripts/dev/install_harness_dev.sh` before PyInstaller.

## Development Mode

Editable install (`uv sync`) ships all `.py` source. `_distribution.get_distribution_mode()` returns `source`.

## Docker (Server Runtime)

| File | Audience | Harness source |
|------|----------|----------------|
| `myrm-agent-server/docker/Dockerfile.official` | Private CI | `assemble_production.py` from harness checkout |
| `myrm-agent-server/Dockerfile` | OSS consumers | PyPI (`read_harness_pypi_spec.py` + `uv pip install`) |

OSS builder:

```bash
uv sync --frozen --no-dev --all-extras --no-install-project \
  --no-install-package myrm-agent-harness --no-sources-package myrm-agent-harness
uv pip install "$(python3 docker/read_harness_pypi_spec.py)"
```

Runtime: `verify-harness-distribution --matplotlib-cjk`. CI: `.github/workflows/build-oss-server-docker.yml`.

## OSS / Private Repo Split

| Item | Status |
|------|--------|
| Harness source | Private `Pursue-LLL/myrm-agent-harness` |
| OSS install | `MYRM_HARNESS_INSTALL_MODE=pypi` (default) via `scripts/dev/install_harness_dev.sh` |
| OSS CI | `check_harness_on_pypi.py` — no PAT clone |
| Harness publish | Tag `v*` → `publish-pypi.yml` → PyPI |

Editable dev: `MYRM_HARNESS_EDITABLE=1 ./scripts/dev/install_harness_dev.sh` (local harness clone).

## CI

| Workflow | Role |
|----------|------|
| `myrm-agent-harness/.github/workflows/publish-pypi.yml` | 6-platform Nuitka matrix + tag → validate 7 wheels → PyPI → post-verify |
| `myrm-agent-harness/.github/workflows/boundary-check.yml` | Architecture tests (`-n0`) including `test_repo_hygiene` |
| `myrm-agent-harness/.github/workflows/arm64-build.yml` | ARM64 unit tests + benchmarks |
| `myrm-agent-harness/.github/workflows/performance.yml` | Startup/context-archive/performance regression |
| `myrm-agent-harness/.github/workflows/security.yml` | License, SBOM, CVE (harness only) |
| `myrm-agent-harness/.github/workflows/build-official-runtime.yml` | Official runtime Docker (source build; checks out vortexai) |
| `.github/workflows/build-oss-server-docker.yml` | OSS public Dockerfile smoke (PyPI harness) |

## References

- [FRAMEWORK_DESIGN_PRINCIPLES.md §5](../FRAMEWORK_DESIGN_PRINCIPLES.md)
- Claude Code native binary distribution (Anthropic official docs)
