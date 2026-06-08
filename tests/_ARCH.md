# tests/

## Overview

Harness test suite: unit, integration, architecture gates, and performance benchmarks. Default execution is serial (`-n0`) with a memory-safe marker filter in `pyproject.toml` `addopts`.

## File & Submodule Index

| Path | Role | Description |
|------|------|-------------|
| `conftest.py` | 核心 | 全局 pytest 配置：隔离 `MYRM_DATA_DIR`、blocking_io gate、benchmark→performance 标记、浏览器 xdist 串行组、`reset_global_browser_pool_for_tests()` 清理 |
| `fixtures/` | 辅助 | 预留 harness-only 夹具目录 |
| `performance/` | 性能 | 子进程 import 热点与 lazy-loading 回归（`performance` marker） |
| `toolkits/browser/` | 集成 | 浏览器单元 + e2e/integration；真实 Chromium 用例带 `integration`/`e2e` |
| `architecture/` | 门禁 | 边界与打包一致性检测 |
| `integration/` | 集成 | 跨模块集成（含浏览器 wait-strategies 等） |
| `agent/skills/curator/test_curator_engine.py` | 单元 | SkillCurator 生命周期与 LRU 驱逐（勿用通用名 `test_engine.py`，会与 `agent/dynamic_workflow/test_engine.py` 触发 collect import mismatch） |

## Test file naming

Duplicate basenames such as `test_engine.py` under different `tests/agent/**` subtrees can trigger pytest `import file mismatch` during collection. Use domain-specific names (e.g. `test_curator_engine.py`).

## Test execution (memory-safe)

| Profile | Command | Notes |
|---------|---------|-------|
| Local default | `pytest` (addopts apply filter automatically) | Serial; ~300–500MB typical peak (darwin arm64, 2026-06) |
| Full suite | `pytest -m ""` | All markers including integration/e2e/performance |
| Browser integration | `pytest -m "integration or e2e" --timeout=600` | Real Chromium; run separately |
| CI unit | `.github/workflows/test.yml` job `unit` | `-n 4` with default marker filter; no `--ignore` workarounds |
| CI browser | `.github/workflows/test.yml` job `browser-integration` | `-n0`, Patchright Chromium |

## Key Dependencies

- `pyproject.toml` `[tool.pytest.ini_options]` markers and `addopts`
- `myrm_agent_harness.toolkits.browser.pool.singleton` (GlobalBrowserPool singleton lifecycle)
