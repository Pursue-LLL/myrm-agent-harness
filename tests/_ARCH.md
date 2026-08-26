# tests/

## Overview

Harness test suite: unit, integration, architecture gates, and performance benchmarks. Default execution is serial (`-n0`) with a memory-safe marker filter in `pyproject.toml` `addopts`.

## File & Submodule Index

| Path | Role | Description |
|------|------|-------------|
| `__init__.py` | 核心 | tests 包标记（pytest 收集根） |
| `conftest.py` | 核心 | 全局 pytest 配置：隔离 `MYRM_DATA_DIR`、blocking_io gate、benchmark→performance 标记、浏览器 xdist 串行组、`pytest_collection_finish` warmup/acquire_page 漏标门禁、integration/e2e 路径 `reset_global_browser_pool_for_tests()`；sessionfinish 浏览器进程树 cleanup（`tests/support/browser_process_cleanup`） |
| `fixtures/` | 辅助 | 预留 harness-only 夹具目录 · [fixtures/_ARCH.md](fixtures/_ARCH.md) |
| `examples/` | 辅助 | 非 shipping 参考实现 · [examples/_ARCH.md](examples/_ARCH.md) |
| `mocks/` | 辅助 | 共享 in-memory backend mock · [mocks/_ARCH.md](mocks/_ARCH.md) |
| `support/` | 辅助 | pytest teardown helpers（browser 进程树 cleanup）· [support/_ARCH.md](support/_ARCH.md) |
| `backends/` | 单元 | 存储后端（profiles/secrets/skills）· [backends/_ARCH.md](backends/_ARCH.md) |
| `scripts/` | 单元 | `scripts/` 维护脚本单测（tool registry）· [scripts/_ARCH.md](scripts/_ARCH.md) |
| `features/` | 单元 | Feature Flag 引擎 · [features/_ARCH.md](features/_ARCH.md) |
| `performance/` | 性能 | 子进程 import 热点与 lazy-loading 回归（`performance` marker） |
| `toolkits/` | 单元/集成 | 镜像 `src/.../toolkits/<name>/`；禁止空壳目录 · [toolkits/_ARCH.md](toolkits/_ARCH.md) |
| `architecture/` | 门禁 | 边界与打包一致性检测 — 见 [architecture/_ARCH.md](architecture/_ARCH.md) |
| `eval/` | 单元 | Eval 框架断言/runner/reporter · [eval/_ARCH.md](eval/_ARCH.md) |
| `observability/` | 单元 | 顶层 metrics/diagnostics/tracing · [observability/_ARCH.md](observability/_ARCH.md) |
| `agent/streaming/broadcast/` | 单元 | ToolBroadcastBus / ToolCallBroadcaster · [agent/streaming/broadcast/_ARCH.md](agent/streaming/broadcast/_ARCH.md) |
| `integration/` | 集成 | 跨模块集成（含浏览器 wait-strategies 等） |
| `dev/` | 单元 | vortexai 维护者脚本回归（`test_run_pytest_safe.py`） |
| `agent/skills/curator/test_curator_engine.py` | 单元 | SkillCurator 生命周期与 LRU 驱逐（勿用通用名 `test_engine.py`，会与 `agent/dynamic_workflow/test_engine.py` 触发 collect import mismatch） |
| `agent/skills/` | 单元 | 技能子系统测试树 · [agent/skills/_ARCH.md](agent/skills/_ARCH.md) |
| `agent/_factory/test_mcp_routing_route.py` | 单元 | `route_mcp_servers` direct/PTC/aggregate demotion + compress 边界（mock connection） |
| `agent/_factory/test_builder_compactor.py` | 单元 | `create_skill_agent` 上下文管道辅助压缩模型 `summarizer_llm` 注入装配 |
| `agent/_factory/test_mcp_routing_real_stdio_integration.py` | 集成 | 真实 MCPServer stdio **55 tools** → PTC/Skill 路径（无 mock） |
| `agent/meta_tools/skill_search/test_engine_mcp_index.py` | 单元 | MCP skill BM25 index enrichment（>3 tools） |
| `agent/skills/evolution/` | 单元 | Skill evolution pipeline tests (incl. trace analyzer takeover, variant generator) |

## Test file naming

Duplicate basenames such as `test_engine.py` under different `tests/agent/**` subtrees can trigger pytest `import file mismatch` during collection. Use domain-specific names (e.g. `test_curator_engine.py`).

Real Chromium tests under `tests/toolkits/browser/` must carry `integration` or `e2e` (or `performance`). `pytest_collection_finish` fails collection if a test function calls `.warmup(` or `.acquire_page(` without those markers.

## Test execution (memory-safe)

| Profile | Command | Notes |
|---------|---------|-------|
| Monorepo default | `./myrm test -n0 <path>`（open-perplexity 根） | 禁止 `uv run pytest`；harness gate 自愈 editable |
| Monorepo integration | `./myrm test -m integration <path>` | 默认 addopts 排除 integration |
| Local default (harness-only) | `pytest` (addopts apply filter automatically) | Serial; ~300–500MB typical peak (darwin arm64, 2026-06) |
| Full suite | `pytest -m ""` | All markers including integration/e2e/performance |
| Browser integration | `pytest -m "integration or e2e" --timeout=600` | Real Chromium; run separately |
| CI unit | `.github/workflows/test.yml` job `unit` | `-n 2` with default marker filter; no `--ignore` workarounds |
| CI performance | `.github/workflows/performance.yml` | `tests/performance/ -m performance -n0` |
| CI browser | `.github/workflows/test.yml` job `browser-integration` | `-n0`, Patchright Chromium |

## Browser integration pitfalls（实测经验，2026-08）

1. **pytest-asyncio loop scope 必须 pin 为 module**：`pyproject.toml` 已全局设置
   `asyncio_default_test_loop_scope = "module"` + `asyncio_default_fixture_loop_scope = "module"`。
   Browser 集成测试用 module-scoped async fixture（如 `GlobalBrowserPool.warmup`）持有 patchright
   连接，其 coroutine 绑定 fixture 所在的 event loop；若测试跑在默认 function-scoped loop 上，
   跨 loop await 会永久挂起直到 `--timeout=300` 超时。**禁止**用 `--override-ini=asyncio_default_*_loop_scope=function`
   降级此配置。

2. **`set_content` 会替换 `document.body` 节点但保留 window/document**（`document.write` 语义）。
   在 `new_tab` 阶段已被安装的 MutationObserver 会悄然观察已脱离文档的旧 body，
   `getChanges()` 永远返回空。快照链路通过 `ObserverManager.ensure_active()`
   （`observer_scripts.py` 的 `ensureActive()` 比较 `bodyRef`）在每次 capture 时自愈。
   测试里若发现 observer 失效，先检查 body 引用是否已变（探针：
   `window.__savedBody.isConnected === false` 即被替换）。

3. **本地地址测试注意 SSRF guard 与 domain_filter 叠加**：SSRF guard（`navigation/ssrf_guard.py`）
   会在 `domain_filter` 之前拦截私有网段请求（127.0.0.1 等），返回通用 `ERR_FAILED`。
   验证 domain_filter 的 allow/block 行为时须在 `BrowserSession` 显式传 `allow_private_networks=True`，
   并用本地 `ThreadingHTTPServer` 做真实页面源，避免外部网络依赖。

4. **`run_site_tool` 输出经 `mark_untrusted` 包裹**（BROWSER_SYSTEM.md 统一安全出口）。
   程序化消费必须走 `extract_wrapped_payload()` 解包后再 `json.loads`，不要直接对裸结果解析。

5. **浏览器可用性检测禁止用 `shutil.which("chromium")`**：macOS/Windows 上 patchright 管理的
   Chromium 装在 Playwright 缓存目录（`~/Library/Caches/ms-playwright` 或 `$PLAYWRIGHT_BROWSERS_PATH`），
   不在 PATH，导致 `requires_browser` 误判跳过整个浏览器池测试（曾经 31 个池/并发测试静默未跑）。
   统一走 `tests/toolkits/browser/_browser_available.py::chromium_available()`——
   它通过 patchright registry 解析真实 `executable_path` 并检查文件存在。

6. **导航摘要/Inspector 预览快照禁止污染 diff baseline**：`BrowserSession.navigate` 内部
   `_append_navigate_interactive_summary` 与 `view_update_payload.capture_browser_view_update_data`
   会用 `snapshot(diff=False, compact=True, scope="interactive")` 做只读预览。若这些调用也更新
   `SnapshotDiffEngine` baseline（`get_snapshot` 默认行为），用户导航后首次 `snapshot(diff=True)`
   就会拿到与 interactive/compact 范围对比的无效 diff。预览用途必须显式传
   `update_baseline=False`（`get_snapshot`/`BrowserSession.snapshot` 新增参数，默认 True 保持契约）。

## Key Dependencies

- `pyproject.toml` `[tool.pytest.ini_options]` markers and `addopts`
- `myrm_agent_harness.toolkits.browser.pool.singleton` (GlobalBrowserPool singleton lifecycle)
