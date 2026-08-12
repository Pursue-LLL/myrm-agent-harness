# Myrm Agent Harness — Bugfix Log

> 每次 harness 框架层用户可感知失败/运行时 bug，**必须追加一条**。产品业务 bug 记各产品仓台账（`myrm-agent/myrm-agent-server`）。

### BUG-HARNESS-2026-08-12-001 · browser/wait 超时漏捕与 evaluate 参数误用

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-08-12 |
| **修复时间** | 2026-08-12 |
| **症状** | ① `wait_spa_stable` 每次调用必抛 `TypeError: evaluate() got an unexpected keyword argument 'timeout'`；② 真实 Playwright 超时（`patchright.async_api.TimeoutError`）穿透 `except TimeoutError` 冒泡，导致 SMART/HYBRID 降级逻辑失效 |
| **关联产品** | myrm-agent-harness `toolkits/browser/wait` |
| **根因** | ① `page.evaluate()` 签名不支持 `timeout` kwarg（patchright 实现），旧代码直接传入；② `patchright.async_api.TimeoutError` MRO 为 `[TimeoutError, Error, Exception]`，**不是** `builtins.TimeoutError` 子类，`except TimeoutError` 无法捕获 |
| **修复** | ① `wait_spa_stable` 改用 `asyncio.wait_for(page.evaluate(js_wait), timeout=max_ms / 1000)` 封顶；② 定义 `_TIMEOUT_ERRORS = (TimeoutError, PlaywrightTimeoutError)` 覆盖全部 7 处 `except`；③ `doctor/checks.py::_check_browser_launch`、`browser_launcher.py::_launch_new_browser` 同步用 `is_timeout_error()` 识别超时 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | 捕获异步驱动库的异常时必须验证其 MRO；Playwright/Patchright 的 `TimeoutError` 与 `builtins` 同名但非同一类型。所有对 `page.evaluate()` 的超时控制一律走 `asyncio.wait_for`，不得假设其支持 `timeout` 参数 |
| **回归** | `tests/toolkits/browser/test_wait_timeout_regression.py`（10 项）+ `test_doctor_launch_unit.py` + `test_browser_auto_install.py` + `test_doctor.py` + `test_wait_strategies*.py` 全通过（ruff 0 错误） |
| **代码位置** | `toolkits/browser/wait/_impl.py` · `toolkits/browser/doctor/checks.py` · `toolkits/browser/pool/browser_launcher.py` |

### BUG-HARNESS-2026-08-12-002 · `_ensure_components` 被 MRO 占位声明遮蔽成 no-op

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-08-12 |
| **修复时间** | 2026-08-12 |
| **症状** | `BrowserSession._ensure_components()` 静默 no-op：`_navigator is None` 时既不初始化组件也不报错，`snapshot()` / `interact()` / `extract_text()` / `save_session()` 等依赖组件初始化的入口在 Navigator 未就绪时静默走空逻辑，仅当后续强制使用未初始化组件时才偶发暴露 |
| **关联产品** | myrm-agent-harness `toolkits/browser/session` |
| **根因** | `BrowserSessionPersistenceMixin` 内声明了 `async def _ensure_components(self) -> None: ...` 作为类型检查占位符。MRO 中 PersistenceMixin 排在 LifecycleMixin 之前，占位声明**遮蔽**了 `BrowserSessionLifecycleMixin._ensure_components` 的真实实现，导致真实实现永不执行 |
| **修复** | 删除 PersistenceMixin 中的占位 `_ensure_components`，MRO 正确解析到 LifecycleMixin 实现 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | 多继承 mixin 中**禁止**为"类型自洽"声明同名占位方法；声明即遮蔽，且被遮蔽的实现永远无法通过 `super()` 之外的路径触达。mixin 间方法名必须全局唯一（已用脚本核对无其他重复） |
| **回归** | `tests/toolkits/browser/` 全量 2541 通过（含修复后的 `test_ensure_components_direct_call`）；`test_browser_session_hitl_caller.py`（3 项）+ `test_chrome_discovery.py`（27 项）+ `test_session_persistence.py` + `test_session_vault_comprehensive.py` 通过（ruff 0 错误）。防回归元测试 `test_browser_session_mixin_collision.py` 检查 `BrowserSession.__mro__` 各 mixin 方法名唯一性 |
| **代码位置** | `toolkits/browser/session/browser_session_persistence_mixin.py` |
