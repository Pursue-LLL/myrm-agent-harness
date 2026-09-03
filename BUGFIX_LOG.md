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

### BUG-HARNESS-2026-08-12-003 · browser/session 从错误模块导入 JSON 解析函数，阻塞整个 browser 包导入

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-08-12 |
| **修复时间** | 2026-08-12 |
| **症状** | `from myrm_agent_harness.toolkits.browser import run_doctor`（以及任何 browser 包入口）抛 `ImportError: cannot import name 'parse_llm_json_list' from 'myrm_agent_harness.utils.chat_utils'`，doctor 测试全部无法收集 |
| **关联产品** | myrm-agent-harness `toolkits/browser/session` |
| **根因** | `structured_extractor.py` 从 `utils.chat_utils` 导入 `parse_llm_json_list`/`parse_llm_json_object`，但两函数实际定义在 `utils.json_parsing`；`chat_utils` 仅提供 `extract_answer_text`。模块自身 docstring（`[POS]` 标注 `utils.json_parsing::`）与实际 import 矛盾，属导入目标写错 |
| **修复** | `structured_extractor.py` 拆分 import：`extract_answer_text` 保留从 `chat_utils`，两个 parse 函数改从 `json_parsing` 导入。全仓核对 wiki/memory/agent 等其余 7 处调用方均正确导入 `json_parsing`，无同类错误 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | 函数实际归属以**定义所在模块**为准，不能凭模块名语义猜测；发现"docstring 标注的模块"与"代码实际导入的模块"矛盾时必有一方错。`tests/toolkits/browser/` 是唯一能拦住此 bug 的收集入口 |
| **回归** | `test_doctor.py`（25 项）+ `test_doctor_launch_unit.py` + `test_browser_auto_install.py` + `runtime/test_doctor.py`（63 项）通过；`tests/toolkits/browser/` 全量 1158 passed + 1 skipped（ruff 0 错误） |
| **代码位置** | `toolkits/browser/session/structured_extractor.py` |

### BUG-HARNESS-2026-08-12-004 · doctor 检查项异常保护不对称，psutil/路径探测失败会崩溃整个诊断

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-08-12 |
| **修复时间** | 2026-08-12 |
| **症状** | 沙箱 `/proc` 受限或 `BROWSER_EXECUTABLE_PATH` 指向无权限路径时，`run_doctor()` 抛 `OSError`/`PermissionError` → server `/health/browser` 接口 500，用户拿不到任何诊断结果。实证复现：mock `psutil.virtual_memory` 抛 `OSError` → `_check_memory` CRASH；mock `Path.exists` 抛 `PermissionError` → `_check_browser_executable` CRASH（对照组 `_check_disk` 同场景正常降级 WARNING） |
| **关联产品** | myrm-agent-harness `toolkits/browser/doctor` |
| **根因** | `_check_memory` 的 `psutil.virtual_memory()`（`checks.py:127`）与 `_check_browser_executable` 的 `Path.exists()`/`os.access()`（`checks.py:78-79`）无 try 保护，与同文件 `_check_disk`（已有 `try/except Exception`）形成不对称；异常穿透 `run_doctor` 直达 server |
| **修复** | ① `_check_memory` psutil 调用包进 `try/except Exception`，失败降级 WARNING；② `_check_browser_executable` 路径探测包进 `try/except Exception`，失败降级 WARNING——与 `_check_disk` 完全对称 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | 诊断工具自身必须永不崩溃（"检查员不能在自己被检查时倒下"）；对系统探测调用（psutil/文件系统）一律降级为 WARNING 而非让异常冒泡。已补异常路径单测：`test_check_memory_psutil_raises`、`test_check_browser_executable_path_raises` |
| **回归** | `test_doctor.py`（25 项，含 2 个新增异常路径测试）通过；`tests/toolkits/browser/` 全量 1158 passed（ruff 0 错误） |
| **代码位置** | `toolkits/browser/doctor/checks.py` · `tests/toolkits/browser/test_doctor.py` |

### BUG-HARNESS-2026-09-03-001 · ToolLayer.HIGH_PRIORITY 语义分层全栈统一与技术债清理

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-09-03 |
| **修复时间** | 2026-09-03 |
| **症状** | 工具分层在多轮迭代中产生命名撕裂，代码与文档混用 `COMMON`、`HIGH_FREQUENCY` 与 `HIGH_PRIORITY`；前端工具面板错误展示为无语义数字（1/2/3/4）或 `common`，破坏国际化体验与分层认知清晰度 |
| **关联产品** | myrm-agent-harness `agent/tool_management` · myrm-agent-server · myrm-agent-frontend |
| **根因** | 重构过程中未能全栈原子同步，导致底层枚举名、确定性排序字典、SSE 传输契约、前端组件及多语言字典之间出现命名不一致与概念滞后 |
| **修复** | ① 全栈统一为 `HIGH_PRIORITY`（值 2），排序字典统一为 `_HIGH_PRIORITY_LAYER_SORT_RANK`；② SSE 事件 `tools_snapshot` 下发语义化 "core" / "high_priority" / "extended" / "external"；③ 前端 `ToolsPanel.tsx` 升级语义徽章并补齐 6 国语言；④ 全量更新相关单测与架构文档 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | 架构核心术语重命名必须做全栈原子式清理，严禁留存过渡别名与旧注释；对用户可见的 UI 徽章严禁透传原始数据库或数字枚举，必须提供多语言语义映射 |
| **回归** | `test_tool_layers.py`（13 项）+ `test_tools_snapshot_layer_integration.py`（真实 LLM E2E）+ `ToolsPanel.test.tsx` 100% 通过；`validate_tool_registry.py` 0 错误 |
| **代码位置** | `agent/tool_management/tool_layers.py` · `agent/tool_management/registry.py` · `DEFAULT_AGENT_TOKEN_INVENTORY.md` · `TOOL_DESIGN_STRATEGY.md` |

### BUG-HARNESS-2026-09-03-002 · `x_search_tool` 解耦后工具目录与文档元数据残留

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-09-03 |
| **修复时间** | 2026-09-03 |
| **症状** | `x_search_tool` 已被重构为 Prebuilt Skill PTC 范式，但 `tool_catalog.py` 的 `_LOAD_CONDITION_OVERRIDES`、`TOOL_DESIGN_STRATEGY.md` 与 `DEFAULT_AGENT_TOKEN_INVENTORY.md` 仍列出 `x_search_tool` 为 External Action Tool，导致工具清单虚高（59 vs 58）且内置智能体 Prompt 产生调用幻觉 |
| **关联产品** | myrm-agent-harness `agent/tool_management` · myrm-agent-server `builtin_specs` |
| **根因** | 业务专有工具解耦为 Skill PTC 时，未同步清理 Harness 层的文档和注册元数据，造成文档与真实代码状态脱节 |
| **修复** | ① 清理 `tool_catalog.py` 中的 `x_search_tool` 覆写项；② 更新 `TOOL_DESIGN_STRATEGY.md` 与 `DEFAULT_AGENT_TOKEN_INVENTORY.md` 修正为 5 个 EXTERNAL 工具并标注 PTC 范式；③ 修正内置智能体 Prompt 为调用 `x-live-search` 技能 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | 将 Action Tool 降级/解耦为 Skill PTC 范式后，必须全库搜索清理所有文档、注册表元数据及内置智能体提示词，避免大模型产生调用已删除工具的幻觉 |
| **回归** | `test_harness_zero_vendor_tools.py` + `test_x_live_search_tool_registration.py`（9 项）+ `validate_tool_registry.py` 100% 通过（58 工具全量一致） |
| **代码位置** | `agent/tool_management/tool_catalog.py` · `DEFAULT_AGENT_TOKEN_INVENTORY.md` · `TOOL_DESIGN_STRATEGY.md` · `server/app/services/agent/builtin_specs/vertical.py` |
