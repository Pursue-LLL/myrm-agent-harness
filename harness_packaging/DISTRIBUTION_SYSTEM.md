# Distribution System

## Design Goal

Ship `myrm-agent-harness` as an **MIT open-source Python package** that third-party frameworks can import and extend, with an optional Nuitka-compiled core for accelerated hot paths — mirroring Claude Code's npm shell + native binary pattern.

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
| Public API | `src/myrm_agent_harness/api/` | Stable import surface (factory, Protocol, DTO, `hooks`, `skills`) |
| Core manifest | `harness_packaging/core_manifest.yaml` | Modules compiled to native extensions |
| Platform detection | `harness_packaging/platforms.py` | Eight supported platform keys (incl. linux-*-musl) |
| Metadata codegen | `scripts/sync_distribution_metadata.py` | Generate `runtime/install_guard/_generated/core_ip_manifest.py`, `platform.py` + sync compiled-core pins |
| Core build | `scripts/build_core.py` | Nuitka `--module` + static hatch `force-include` wheel + inline artifact verify |
| Release build | `scripts/build_release_wheel.py` | `uv build --wheel` + `finalize_stripped_release_wheel` (strip + verify) |
| Browser data assets | `pyproject.toml` `[tool.hatch.build.targets.wheel.force-include]` | Ships `toolkits/browser/assets/ad_domains.txt` in release wheel (guard: `tests/architecture/test_wheel_browser_assets.py`) |
| Production assemble | `harness_packaging/assemble.py` | Core + release via same finalize helper + optional `--install` |
| Post-install verify | `src/myrm_agent_harness/runtime/install_guard/verify.py` | Console script `verify-harness-distribution` |
| Wheel artifact gate | `harness_packaging/integrity.py` + `release.py::finalize_stripped_release_wheel` | Zip scan: no manifest `.py` / debug maps in release; compiled-only core; inline at all build entrypoints |
| Install guard probe | `src/myrm_agent_harness/runtime/install_guard/probe.py` | `source` vs `compiled` + fail-closed + version + platform key match (rejects unstamped `unknown` key) |
| Platform key SSOT | `harness_packaging/platform_key.py` → codegen `runtime/install_guard/platform.py` | Build + runtime platform key alignment |

## Build Pipeline

```bash
uv sync --group build
.venv/bin/python scripts/assemble_production.py
verify-harness-distribution
```

**Not PyArmor/obfuscation.** The compiled core in `core_manifest.yaml` is compiled with **Nuitka** to native `.so` / `.pyd` for hot-path acceleration; the source itself is open on GitHub and in sdist.

## Consumer Install (PyPI)

`pyproject.toml` defines the `compiled-core` extra (platform markers). After a release wheel containing that extra is on PyPI, consumers install:

```bash
pip install 'myrm-agent-harness[file-parsers,web,...,compiled-core]==0.1.0'
```

Or in `myrm-agent-server` after `uv sync` (PyPI, default for this repo).

Editable dev: `pip install -e /path/to/myrm-agent-harness[...]` when harness source is checked out locally.

## Development Mode

Editable install ships all `.py` source. `runtime.install_guard.probe.get_distribution_mode()` returns `source`.

**Monorepo dev** (sibling `myrm-agent-harness`): `myrm-agent/scripts/dev/setup.sh` delegates to `install_harness.sh`; `myrm dev` / `myrm start` exit 1 when the server venv is not editable (set `MYRM_SKIP_HARNESS_EDITABLE_CHECK=1` for PyPI consumer testing). OSS-only clones still use `uv sync` + PyPI wheels. See `myrm-agent/scripts/_ARCH.md`.

## Docker (Server Runtime)

| File | Audience | Harness source |
|------|----------|----------------|
| `myrm-agent/myrm-agent-server/docker/Dockerfile.official` | Source-built wheels | `assemble_production.py` in-image |
| `myrm-agent/myrm-agent-server/Dockerfile` | PyPI consumers | `uv.lock` + PyPI harness |

```bash
# OSS public image (myrm-agent repo root context)
docker build -f myrm-agent/myrm-agent-server/Dockerfile -t myrm-server .

# Official (open-perplexity / vortexai root: harness + myrm-agent trees)
docker build -f myrm-agent/myrm-agent-server/docker/Dockerfile.official -t myrm/runtime:local .
```

## PyPI Publish

Tag `v*` (e.g. `v0.1.0rc1`, aligned with `project.version`) in **myrm-agent-harness** triggers `.github/workflows/publish-pypi.yml`:

0. `scripts/verify_release_tag.py` asserts `refs/tags/v{version}` matches `project.version` before any wheel build
1. Matrix build eight `myrm-agent-harness-core-*` wheels
2. Build stripped release wheel (`scripts/build_release_wheel.py`: strip manifest `.py` + inline artifact verify)
3. `validate-wheels` job runs `scripts/validate_pypi_wheels.py` on release + all core wheels (count/version + zip artifact scan)
4. `publish-release` job uploads the release wheel (OIDC, `environment: pypi`)
5. `publish-core` matrix (one job per platform) uploads each core wheel — OIDC tokens are project-scoped; batch upload fails with 403
6. `publish-verify` runs `scripts/verify_pypi_publish.py` (release + 6 bootstrapped core wheels mandatory; musl mandatory once indexed; see `bootstrap_pypi_core_upload.sh`)

Alpine/musl deployments: use `compiled-core-musl` extra (or `install.sh` `reinstall_harness_musl_core()` after `uv sync`). PEP 508 cannot distinguish glibc vs musl on Linux; do not install both linux extras on the same host.

`[tool.uv] exclude-dependencies` (uv >= 0.9.8) in `pyproject.toml` lists the eight `myrm-agent-harness-core-*` packages, so `uv lock` / `uv sync` never resolve `compiled-core` or `compiled-core-musl`: their pins name versions that exist on PyPI only after the release is published. The published wheel metadata keeps the pins. A platform added to `harness_packaging/platforms.py` (`PUBLISH_PLATFORMS`) must be added to that list too, otherwise `uv lock` fails on the unsatisfiable pin.

CI build jobs use `uv sync --only-group build --frozen` and `uv run --no-project` so the editable project is not installed before wheels exist on PyPI. CI test jobs (`test.yml`, `performance.yml`) install the project with `uv sync --python 3.13 --locked --extra all` (`test.yml` adds `--group dev` and runs `uv run --no-sync`). `--locked` fails on a stale lock, so run `UV_DEFAULT_INDEX=https://pypi.org/simple uv lock` and commit `uv.lock` after every `pyproject.toml` change, including the `project.version` bump of a release. The index is part of the command because uv records it, and every file URL it receives, in each lock entry: a plain `uv lock` behind a mirror rewrites every registry source and download URL in the lock to that mirror, and `tests/architecture/test_core_dependencies.py::test_uv_lock_resolves_from_pypi` rejects such a lock. The `build` group packages (`nuitka`, `build`, ...) that compile and package the release are whatever `uv.lock` pins: re-locking keeps them, `uv lock --upgrade` moves them, so review those entries in the lock diff or restore them with `--upgrade-package <name>==<version>`.

Each PyPI project needs a GitHub publisher: Owner `Pursue-LLL`, repository `myrm-agent-harness`, workflow `publish-pypi.yml`, environment `pypi`.

One-time bootstrap for new core project names (OIDC cannot create projects): `scripts/bootstrap_pypi_core_upload.sh` with `PYPI_API_TOKEN`, then add Trusted Publisher on PyPI. After musl projects exist, `verify_pypi_publish.py` automatically requires musl wheels for that version.

## CI

| Workflow | Role |
|----------|------|
| `publish-pypi.yml` | Tag release → PyPI (OIDC upload for release + 8 core wheels; verify 6 + indexed musl); matrix from `.github/core-platform-matrix.json` |
| `build-core-wheels.yml` | Dev/matrix core wheel artifacts (same shared matrix; optional `platform` input) |
| `boundary-check.yml` | Architecture + distribution tests (dual-wheel COMPILED e2e, manifest drift gate, wheel artifact zip scan via `validate_pypi_wheels.py`) |
| `test.yml` | Unit suite (`-n 2`) and serial browser integration on push to `main` and PRs; locked source tree (`uv sync --locked`: `[all]` + `dev` group; `compiled-core*` excluded via `[tool.uv]`) |

## References

- [FRAMEWORK_DESIGN_PRINCIPLES.md §5](../FRAMEWORK_DESIGN_PRINCIPLES.md)
