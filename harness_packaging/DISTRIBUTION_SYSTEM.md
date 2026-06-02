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

Two Dockerfiles — same runtime image, different build inputs:

| File | Audience | Harness source |
|------|----------|----------------|
| `myrm-agent-server/docker/Dockerfile.official` | Private CI / monorepo | `assemble_production.py` inside harness-wheels stage |
| `myrm-agent-server/Dockerfile` | Open-source consumers | Pre-built wheels; **build context = server repo root** |

Builder and runtime stages run `verify-harness-distribution` (runtime adds `--matplotlib-cjk`).

Server builder pattern:

```bash
uv sync --frozen --no-dev --all-extras --no-install-project --no-install-package myrm-agent-harness
./docker/install_harness_wheels.sh /wheels/core /wheels/release
```

`install_harness_wheels.sh` maps BuildKit `TARGETPLATFORM` → `linux-x64` / `linux-arm64`, requires exactly one core wheel, installs stripped release wheel, runs `verify-harness-distribution`.

```bash
# Official (monorepo root)
docker build -f myrm-agent-server/docker/Dockerfile.official -t myrm/runtime:local .

# Open-source (requires pre-built harness wheels; context = server repo root)
cd myrm-agent-harness && uv sync --group build && .venv/bin/python scripts/assemble_production.py
# harness-wheels context must contain only the PEP 427 stripped release wheel (dist/)
cd myrm-agent-server
docker build \
  --build-context harness-wheels=../myrm-agent-harness/dist \
  --build-context harness-core-wheels=../myrm-agent-harness/build/core/wheels \
  -t myrm-server .

# Monorepo checkout
docker build -f myrm-agent-server/Dockerfile \
  --build-context harness-wheels=myrm-agent-harness/dist \
  --build-context harness-core-wheels=myrm-agent-harness/build/core/wheels \
  -t myrm-server myrm-agent-server/
```

## P0: OSS / Private Repo Split

| Phase | Action |
|-------|--------|
| R1 | `./scripts/dev/extract_harness_private_repo.sh /tmp/out` → push to **private** `myrm-agent-harness` Git |
| R2 | `./scripts/dev/install_harness_dev.sh` — release wheel install (default) or source/editable dev |
| R3 | `server-ci.yml` installs public GitHub Release wheels; harness CI stays in private repo |
| R4 | Delete `myrm-agent-harness/` from OSS monorepo; replace `[tool.uv.sources]` path with private index |

Editable monorepo dev (transitional): `MYRM_HARNESS_EDITABLE=1 ./scripts/dev/install_harness_dev.sh`

## CI

| Workflow | Role |
|----------|------|
| `myrm-agent-harness/.github/workflows/publish-pypi.yml` | 6-platform Nuitka matrix + tag → PyPI (release + core wheels) |
| `myrm-agent-harness/.github/workflows/boundary-check.yml` | Architecture tests (`-n0`) including `test_repo_hygiene` |
| `.github/workflows/build-oss-server-docker.yml` | OSS public Dockerfile smoke (PyPI harness) |
| `.github/workflows/build-official-runtime.yml` | Official runtime Docker image (linux-amd64) |

## References

- [FRAMEWORK_DESIGN_PRINCIPLES.md §5](../FRAMEWORK_DESIGN_PRINCIPLES.md)
- Claude Code native binary distribution (Anthropic official docs)
