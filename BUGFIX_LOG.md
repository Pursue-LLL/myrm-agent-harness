# Myrm Agent Harness — Bugfix Log

> 每次 harness 框架层用户可感知失败/运行时 bug，**必须追加一条**。产品业务 bug 记各产品仓台账（`myrm-agent/myrm-agent-server`）。

### BUG-HARNESS-2026-10-07-002 · 摘要流式读取把内容块列表当字符串，整段输出被丢弃后重发一次完整调用

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-07 |
| **修复时间** | 2026-10-07 |
| **症状** | 摘要模型以内容块列表（`[{"type": "text", ...}]`）流式输出时，拼接抛 `TypeError`，被 `ainvoke` 回退吞掉：已流式生成的整段摘要被丢弃并重新调用一次模型，成本与时延翻倍，且没有任何错误日志；用测试替身实测为 `astream=1 ainvoke=1`，字符串内容为 `ainvoke=0` |
| **关联产品** | myrm-agent-harness `agent/context_management/strategies/summary` |
| **根因** | `_stream_with_progress` 取 `chunk.content` 后直接追加进 `list[str]`，而 `content` 可以是内容块列表；mypy 对这一行的 `arg-type` 报错长期存在，宽泛的 `except (NotImplementedError, TypeError, AttributeError)` 又把真实缺陷伪装成"提供方不支持流式" |
| **修复** | 改用 `chunk.text`：只拼接文本块，字符串内容原样返回，仅含思考块的 chunk 为空串被跳过 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | 类型检查器的既有报错要当作缺陷线索而不是噪声；回退分支覆盖的异常类型越宽，越需要一个"回退没有被触发"的断言 |
| **回归** | `tests/agent/context_management/test_summary_stream_content.py`（字符串内容、文本块列表、思考块混合三种流，断言结果拼接正确且 `ainvoke` 调用数为 0） |
| **代码位置** | `agent/context_management/strategies/summary/summarizer.py::_stream_with_progress` |

### BUG-HARNESS-2026-10-07-001 · 摘要调用与 grace call 的历史前缀绕过工具配对闸门，头部裁剪后会留下孤儿工具结果

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-06 |
| **修复时间** | 2026-10-07 |
| **症状** | 摘要模型上下文窗口小于主模型时，`_guard_aux_context` 从头部按消息裁剪，会保留工具结果却裁掉发起它的 assistant 工具请求；严格提供方会拒绝孤儿 tool 消息（MiniMax 实测 HTTP 400：`invalid params, tool result's tool id(call_a) not found (2013)`），上下文压缩失败。尚无线上日志复现；回归夹具（10 条消息，含并行工具调用与空结果）的 10 个头部裁剪窗口中 3 个违反配对，修复后为 0 |
| **关联产品** | myrm-agent-harness `agent/context_management/strategies/summary` · `agent/streaming/recovery`（grace call）· `agent/config/llm_safety` |
| **根因** | 主调用链路在发请求前依次做 `sanitize_tool_history` → `repair_dangling_tool_calls`，摘要调用（历史前缀）绕过了它；公开函数 `normalize_messages` 本应承担这一职责，却是与生产链路分叉的另一套手写实现：对没有结果的请求直接删除（生产链路是补齐合成结果），且末尾的“丢弃空消息”过滤会删掉内容为空的合法工具结果，反而制造悬空请求；该函数在 harness 与其他仓库内均无调用方 |
| **修复** | `normalize_messages` 改为生产同款的 `sanitize_tool_history` → `repair_dangling_tool_calls` 组合：健康历史原样返回同一批消息对象（提示缓存前缀不变），异常历史才被修复；摘要请求构造 `_build_summary_invocation_messages` 与 `_grace_call_summary` 统一经由这一个入口 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | 出站消息的每一条重放路径都必须经过同一个配对闸门，而且要放在最后一次裁剪之后；不要为"直连 LLM 的路径"另写一套简化配对逻辑。`normalize_messages` 内的两个导入必须保持惰性：中间件包加载约 3780 个模块，并会经 `context_management` 与摘要器形成循环导入 |
| **回归** | `tests/agent/context_management/test_summary_prefix_pairing.py`（新增：每个头部裁剪窗口严格配对、经 aux 守卫裁剪后的前缀严格配对、健康前缀原样发送、无结果请求被补齐、无前缀时只发提示词）· `tests/agent/config/test_llm_safety.py`（“删除无结果请求”的旧契约改为生产语义，新增空内容工具结果保留、健康历史原样返回）· `tests/integration/test_tool_history_hygiene_integration.py` |
| **代码位置** | `agent/config/llm_safety.py` · `agent/context_management/strategies/summary/summarizer.py::_build_summary_invocation_messages` · `agent/streaming/recovery/stream_recovery.py::_grace_call_summary` · 提交 `57d45c2c` |

### BUG-HARNESS-2026-10-06-001 · 工具参数恢复把合法 JSON 字符串值里的 `None` 静默改写成 `null`

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-06 |
| **修复时间** | 2026-10-06 |
| **症状** | 模型返回的合法工具参数里，字符串值含单词 `None`（要写入的 Python 代码、说明文字）被静默改写成 `null`，并被记为"降级但安全"的修复；文件被写入与模型意图不同的内容 |
| **关联产品** | myrm-agent-harness `toolkits/llms/utils/litellm_utils.py` |
| **根因** | `parse_tool_call_arguments_with_recovery` 在严格解析之前，对整段参数文本无条件做 `\bNone\b → null` 替换，既不区分字符串字面量内外，也不区分参数本身是否已是合法 JSON |
| **修复** | 先做严格 `json.loads`，合法 JSON 逐字节不变；失败后才用线性时间、识别字符串字面量的扫描，只替换字面量之外的裸 `None`，未闭合的字符串尾部原样保留（截断载荷也不再被破坏） |
| **反复次数** | 第 1 次发现 |
| **踩坑** | 文本级"修复"只能在严格解析失败之后介入，并且必须识别字符串字面量边界；对替换用的正则要做病态输入（长转义尾部）的线性耗时测试 |
| **回归** | `tests/toolkits/llms/adapters/test_tool_call_argument_recovery.py`（合法 JSON 透传、混合载荷、转义引号、截断字符串、两条转换流水线、病态转义尾部线性耗时） |
| **代码位置** | `toolkits/llms/utils/litellm_utils.py` · 提交 `f035034c` |

### BUG-HARNESS-2026-10-06-002 · 工具参数的 HTML 实体解码对所有模型生效，改写用户要写入的 HTML 源码

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-06 |
| **修复时间** | 2026-10-06 |
| **症状** | 文件类工具被要求写入 HTML 源码（`&lt;`、`&amp;`）时，内容被静默改写；`&amp;lt;` 这类转义文本会被逐层折叠到 `<` |
| **关联产品** | myrm-agent-harness `toolkits/llms/adapters`（`converters` · `tool_recovery` · `stream_aggregator` · `chat_model/message_mixin` · `parsers/text_utils` · `model_capability`） |
| **根因** | 解码对任何模型无条件执行，而已知会转义工具参数的只有 xAI Grok 家族（含经代理转发的 Grok；`&&` 到达时是 `&amp;&amp;`）；解码器还是 6 次链式 `replace` 且 `&amp;` 在前，导致多层折叠 |
| **修复** | 解码改为显式开关 `decode_html_entities`（默认关），由 `ModelCapabilityDetector.is_xai_model(model id)`（`xai/` 路由或模型 id 中独立的 `grok` 词元，含经代理转发与网关别名的 Grok）在非流式结果装配与 `finalize_stream` 两个编排点决定；解码器改为单遍正则、只解一层 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | 针对单一提供方的兼容补丁必须按模型 id 门控，不能全局生效；其余模型的工具参数是用户数据，必须原样透传 |
| **回归** | `tests/toolkits/llms/adapters/test_html_entity_gating.py`（模型门控、两条流水线、共享流式收尾、单层解码、非 Grok 的 HTML 源码原样透传）及 5 个既有测试文件同步调整 |
| **代码位置** | `toolkits/llms/adapters/model_capability.py` · `converters.py` · `tool_recovery.py` · `stream_aggregator.py` · `chat_model/message_mixin.py` · `parsers/text_utils.py` · 提交 `7740a320` |

### BUG-HARNESS-2026-09-09-001 · device_routes 无线配对接口导入不存在类引发 500 崩溃与 mobile 包收敛

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-09-09 |
| **修复时间** | 2026-09-09 |
| **症状** | 用户在 WebUI 设备管理页面点击“无线配对”或“连接设备”时，后端直接报 `ImportError: cannot import name 'AdbDeviceManager' from 'myrm_agent_harness.toolkits.mobile'` 并向前端返回 500 Internal Server Error，设备配对功能完全瘫痪 |
| **关联产品** | myrm-agent-server `app/api/webui/device_routes.py` · myrm-agent-harness toolkits/mobile 与 `toolkits/mobile_adb` |
| **根因** | 历史代码重构时未清理废弃的 toolkits/mobile/ 包，且 `device_routes.py` 内部硬编码导入了并不存在的 `AdbDeviceManager`（真实类为 `MobileDeviceManager`，且该模块已非官方维护工具包），Server 与 Harness 调用关系未对齐 |
| **修复** | ① `device_routes.py` 移除对废弃包的错误导入，重构为直接调用 Server 现有的生产级单例 `DeviceBridgeService` 与 `get_mobile_device_service()`，增加标准 HTTP 400/500 异常捕获包装；② 确立 `toolkits.mobile_adb` 为官方唯一真机操控 SSOT；toolkits/adb 与 toolkits/mobile 设为向后兼容门面转发至 `mobile_adb`；③ `backends/skills/scanning/` 收敛至 `path_security.py` 单一权威实现 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | 工具包迭代必须严格遵守 `toolkits/_ARCH.md` 基线，禁止遗留同名同质化废弃包；跨仓/跨层静态导入必须有单测拦截保护，禁止使用未定义的虚构类名 |
| **回归** | `tests/toolkits/test_mobile_adb.py`、`test_mobile_adb_toolkit.py` 及 `tests/backends/skills/prerequisites/test_prerequisites_probe.py` 全数通过 |
| **代码位置** | `myrm-agent/myrm-agent-server/app/api/webui/device_routes.py` · `myrm-agent-harness/src/myrm_agent_harness/toolkits/mobile_adb/` |

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

### BUG-FRONTEND-2026-09-03-001 · `handleSubmit` 异步触发间隙导致输入框文本与胶囊未即时卸载引发 E2E 状态漂移

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-09-03 |
| **修复时间** | 2026-09-03 |
| **症状** | 在真实用户 Task Flow E2E 测试中，用户点击发送后，`sendMessage` 异步网络触发和跨组件状态重置存在时序抖动，`setInputMessage('')` 位于网络触发下方，导致输入框文本与 `ComposerInlineContextChipStrip` 在短暂微秒内未能即时清空卸载，触发 E2E wait_for_state 偶发超时失败 |
| **关联产品** | myrm-agent-frontend `useMessageInput.ts` · `ComposerContextChipStrip.tsx` |
| **根因** | `useMessageInput.ts` 在 `handleSubmit` 中直接提交时，清理输入框 `setInputMessage('')` 动作滞后于 `_injectDirtyArtifacts` 和后续处理流程，导致 UI 状态未能在用户发起提交瞬间完成瞬时响应与重置 |
| **修复** | 在 `useMessageInput.ts` 的 `handleSubmit` 直接提交分支最顶层，与 `clearDraft()`、`addInputHistory` 一致，第一时间执行 `setInputMessage('')` 立即清空输入框文本，彻底保证用户点击发送瞬间 UI 状态即时归零 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | 用户提交表单交互必须遵循「乐观即时响应」原则，先置空输入区与依赖状态，再进行异步网络和后续遥测上报，避免极端高频或并发断言产生时序抖动 |
| **回归** | 真实 Chrome 浏览器端到端闭环 `test_composer_context_chip_strip_chrome_e2e.py`（3/3 passed）、前端 Vitest 单元测试 `useComposerContextChips.test.ts` 与 `ComposerContextChipStrip.test.tsx` 100% 满分通过（0 Lint 错误） |
| **代码位置** | `myrm-agent-frontend/src/hooks/message-input/useMessageInput.ts` |

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
