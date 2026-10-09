# Myrm Agent Harness — Bugfix Log

> 每次 harness 框架层用户可感知失败/运行时 bug，**必须追加一条**。产品业务 bug 记各产品仓台账（`myrm-agent/myrm-agent-server`）。

### BUG-HARNESS-2026-10-08-006 · Linux 上后台 PTY 任务的输出在子进程退出后被丢弃：主端读取抛 `OSError: [Errno 5]`，尚未被取走的行全部丢失且没有任何提示

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-08 |
| **修复时间** | 2026-10-08 |
| **症状** | Linux 上以 PTY 方式启动的后台任务，子进程退出后对 `process.stdout.readline()` 的读取抛 `OSError: [Errno 5] Input/output error`：任务打印几行就退出时，除消费方已经取走的行之外全部丢失；`agent/meta_tools/bash/_background/consume.py` 把 `OSError` 当作“流结束”吞掉（`except (ConnectionError, OSError, asyncio.CancelledError): return`），所以不会有任何错误提示，只是读到一份被截短的输出。macOS 读到的是 EOF，本地从未复现；由 PR 的 Linux CI 暴露：`test_spawn_full_duplex_communication`、`test_spawn_stderr_capture` 失败 |
| **关联产品** | myrm-agent-harness `toolkits/code_execution/executors/local` · `agent/meta_tools/bash/_background` |
| **根因** | PTY 从端关闭后，Linux 让主端的下一次读取失败并返回 EIO（macOS 返回 EOF）。PTY 后台启动把主端接到普通的 asyncio `StreamReaderProtocol` 上，asyncio 把 EIO 转成 `StreamReader.set_exception()`；此后每次 `readline()` 都先检查该异常再看缓冲区（CPython 3.13：`unix_events._fatal_error → connection_lost(exc)`，`streams.readuntil` 先检查 `_exception`），缓冲区里已经收到的行因此被丢弃 |
| **修复** | `_background_pty_spawn.py` 新增 `_PtyReaderProtocol`：`connection_lost` 收到 EIO 时按干净的流结束处理（先交付缓冲区里的行，随后返回 `b""`），其余读取错误原样透传。CPython 3.13 实测：标准协议在 `connection_lost(EIO)` 之后、缓冲区有 3 行时，首次 `readline()` 即抛 `OSError(5)`；换用新协议后依次读到 line1、line2、line3、`b""` |
| **反复次数** | 第 1 次发现 |
| **踩坑** | PTY 挂断语义在 macOS 与 Linux 上不同，只在 macOS 上开发永远看不到；上层为容错把 `OSError` 一律当作流结束，等于把数据丢失伪装成正常结束，因此只能靠 Linux 上的测试暴露。修复放在协议层把 EIO 归一为 EOF，而不是放宽上层对 `OSError` 的吞掉 |
| **回归** | `tests/toolkits/code_execution/executors/local/test_background_pty_spawn.py`：`test_pty_reader_protocol_keeps_buffered_lines_when_linux_reports_eio`、`test_pty_reader_protocol_still_surfaces_other_read_errors`（协议级，所有平台运行）与 `test_spawned_pty_output_survives_child_exit`（真实 PTY，子进程打印三行后退出，退出后再读取）；相关套件（`executors/local` 与 `agent/meta_tools/bash` 的后台/spawn）207 passed |
| **代码位置** | `toolkits/code_execution/executors/local/_background_pty_spawn.py::_PtyReaderProtocol` |

### BUG-HARNESS-2026-10-08-005 · 干净检出的 `origin/main` 导入 `agent.middlewares` 即抛 `ImportError`：`agent.middlewares` 重新导出了一个从未提交定义的委托令牌访问器，CI 单测与浏览器作业大面积变红

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-08 |
| **修复时间** | 2026-10-08 |
| **症状** | 在 `git archive origin/main src` 解出的纯净源码树上执行 `import myrm_agent_harness.agent.middlewares`，抛 `ImportError: cannot import name 'get_delegation_token' from 'myrm_agent_harness.agent.middlewares._session_context'`，导入该包的模块全部加载失败。`origin/main`（`61c328b7`）的 CI 因此单测作业 629 个失败 + 170 个错误（共 799 条异常行，其中 685 条出自这条导入链），浏览器作业的 116 个收集错误全部出自它；开发者本地树里这些文件存在，本机看不到任何异常 |
| **关联产品** | myrm-agent-harness `agent/middlewares/_session_context.py` · `agent/middlewares/__init__.py` |
| **根因** | `agent/middlewares/__init__.py` 重新导出 `get_delegation_token`，而它的定义（`_session_context.py` 中的 `set_delegation_token`/`get_delegation_token`，以及整个 delegation 包（原位于 `agent/security` 下））只存在于本地树，从未提交。仓库里没有任何一步在“只含已提交文件”的树上导入包，缺失只能由 CI 的干净检出暴露；该包此前也没有任何测试引用（`tests/` 下零处） |
| **修复** | 删除该导出及其定义（`_session_context.py` 的令牌上下文变量与 `set/get_delegation_token`、整个 delegation 包（原位于 `agent/security` 下）及其 `_ARCH.md` 索引行）。依据：全仓库（harness、myrm-agent、control-plane）没有生产代码调用 `set_delegation_token`，唯一消费者 server 的 `app/services/ssh_bridge` 自身也没有任何导入方，该功能链不可达；按“要么接上产品，要么删”处理，而不是补交一个无人使用的包。同一 PR 的单测作业失败数：修复前 `origin/main` 为 629 个失败 + 170 个错误，修复后首轮为 66 个失败，同一分支继续收敛到 4 个失败（`a7d8f69e`；66 到 4 的下降来自同一分支里与平台、测试隔离相关的修复，与本条无关） |
| **反复次数** | 第 1 次发现 |
| **踩坑** | 本地树完整不等于仓库完整：导出点与被导出的定义分属不同提交时，开发机上一切正常，唯一的信号是在只含已提交文件的树上导入包。最便宜的复核：`git archive HEAD src \| tar -x -C <dir>` 后以 `PYTHONPATH=<dir>/src` 导入 `myrm_agent_harness.agent.middlewares` |
| **回归** | `tests/agent/middlewares/test_public_exports.py`：`agent.middlewares.__all__` 中的每个名字都必须能解析，导出与定义分离时在收集或断言阶段失败；`.github/workflows/test.yml` 在干净检出上运行全部单测 |
| **代码位置** | `agent/middlewares/__init__.py` · `agent/middlewares/_session_context.py` |

### BUG-HARNESS-2026-10-07-007 · 安装 `myrm-agent-harness[pdf-ocr]` 依赖无解：核心要求 `PyYAML>=6.0.3`，而 PaddleOCR 链固定 `PyYAML==6.0.2`，与 `retrieval` 同装时又被 numpy 上限卡死

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-07 |
| **修复时间** | 2026-10-07 |
| **症状** | 用修复前 `origin/main`（`7a7a5ecf`）构建的 wheel 解析 `[pdf-ocr]`：`uv pip install --dry-run "myrm_agent_harness-0.1.0rc6-py3-none-any.whl[pdf-ocr]"` 报 `No solution found … myrm-agent-harness==0.1.0rc6 and myrm-agent-harness[pdf-ocr]==0.1.0rc6 are incompatible`；`[pdf-ocr,retrieval]` 同样无解，不含 pdf-ocr 的 `[all]` 可解。扫描 PDF 的 OCR 兜底（`toolkits/file_parsers/ocr.py`）因此无法通过 extra 安装，用户只能得到文本层/页面图的降级结果；仓库内 `uv lock` 也生成不了，CI 只能绕开 `uv.lock` 安装 |
| **关联产品** | myrm-agent-harness `pyproject.toml`（核心依赖与 `pdf-ocr` extra）· `uv.lock` · `.github/workflows/test.yml` |
| **根因** | 三处叠加：（1）核心依赖 `PyYAML>=6.0.3`，而 paddlex 已核查的发布（3.2.0、3.4.3、3.7.2）全部固定 `PyYAML==6.0.2`，任何 `paddleocr>=3.2.0` 都经 paddlex 带入这一引脚；（2）`pdf-ocr` 下限 `paddleocr>=3.7.0` 把解析器逼向 paddlex 3.7.x，其 `numpy<2.4` 与 `retrieval` 的 `numpy>=2.5.2` 冲突；（3）没有任何一步把核心与全部 extras 放进同一次解析：`uv.lock` 因 `compiled-core*` 的平台包（发版后才存在于 PyPI）无法生成，开发与 CI 只能用 `uv pip install`，冲突无人发现 |
| **修复** | 核心 `PyYAML>=6.0.2`；`pdf-ocr` 下限 `paddleocr>=3.2.0`（`ocr.py` 按主版本号选择 API 分支，3.2.0 落在 3.x 分支内）；单装 pdf-ocr 解析为 paddleocr 3.7.0 / paddlex 3.7.2，与 retrieval 同装解析为 paddleocr 3.4.1 / paddlex 3.4.3；`[tool.uv] exclude-dependencies` 把发版后才存在的 8 个平台核心包移出开发锁，`uv.lock` 重新生成并覆盖全部 extras，CI 改为 `uv sync --locked`。同一 wheel 构建流程实测：`[pdf-ocr]`、`[pdf-ocr,retrieval]`、`[all]` 均可解；wheel 元数据的 `Requires-Dist` 相对修复前只有 `pyyaml`、`paddleocr` 两个下限变化，8 个平台核心包引脚不变；未用真实模型做端到端 OCR 复测 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | 核心依赖下限与某个 extra 的传递性精确引脚互相打架，只有把核心和全部 extras 放进同一次解析（`uv lock`）才会暴露；lock 生成不了时大家改用绕开 lock 的安装命令，等于关掉了这道闸门。把 `litellm` 下限抬到 `>=1.104.0`（其基础依赖要求 `pyyaml>=6.0.3` 且 `filelock<4`）会让 `[pdf-ocr]` 重新无解，`uv lock` 会在提交前报错 |
| **回归** | `tests/architecture/test_core_dependencies.py::test_uv_lock_core_matches_pyproject`（`uv.lock` 与 pyproject 核心依赖严格对齐）；`.github/workflows/test.yml` 的 `uv sync --locked`（lock 过期，或核心与任一 extra 不可同时满足时安装步骤失败） |
| **代码位置** | `pyproject.toml`（核心 `PyYAML`、`pdf-ocr`、`[tool.uv] exclude-dependencies`）· `uv.lock` |

### BUG-HARNESS-2026-10-07-004 · GLM XML 工具调用丢一个 `<arg_value>` 标签时参数绑定到错误的键，病态输入下解析耗时二次方

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-07 |
| **修复时间** | 2026-10-07 |
| **症状** | GLM 系列模型偶发丢掉一个 `<arg_value>` 开标签或闭标签时，值被绑定到错误的键且没有任何告警：丢开标签的 `query` 实测解析为 `{"query": 5}`，`limit` 丢失（期望 `{"query": "hello world", "limit": 5}`）；GLM-4.7 把函数名与首个 `<arg_key>` 写在同一行时，函数名吞掉整段标签流（`read_file<arg_key>path</arg_key>...`），工具查找失败；病态输入会阻塞事件循环（实测，单次，多任务负载下数值浮动约 ±30%）：8000 个未闭合的 `<tool_call>` 开标签（104 KB）解析耗时约 2–4 s，8000 个“键后接未闭合值”的键值对（256 KB）约 7.9 s，2 万对（640 KB）超过 40 s |
| **关联产品** | myrm-agent-harness `toolkits/llms/adapters/parsers/glm_xml.py` |
| **根因** | 旧实现分别 `findall` 出 keys 与 values 两个列表再按位置 `zip`，任一侧少一个标签就整体错位；函数名取首行；`<tag>(.*?)</tag>` 惰性正则对每个未闭合开标签都重扫到文本末尾，耗时随输入长度二次方增长 |
| **修复** | 先修复单个丢失的 `<arg_value>` 开/闭标签（形态良好的块逐字节不变），再按文档顺序配对，无值的键与无键的值记录告警而不是错位；函数名取首个 `<arg_key>`/`<arg_value>` 之前的文本；所有扫描改为线性：只向前的标签查找器与 `_scan_elements` 取代两处惰性正则，规整化的窗口查找互不重叠；同样的输入现为 3.9 ms、29.6 ms、74.7 ms（5 次取中位数，耗时随输入线性增长：8000 对→2 万对为 2.5 倍输入、2.5 倍耗时） |
| **反复次数** | 第 1 次发现 |
| **踩坑** | 用位置 `zip` 配对两个独立提取的列表，会把“少一个标签”放大成“所有后续值错位”；惰性正则加“找不到收尾标签”就是二次方，必须用成千上万个悬空标签的病态输入做耗时测试；重写扫描算法时以旧算法逐字复制作参照，在 21 万个随机块上确认等价后再替换 |
| **回归** | `tests/toolkits/llms/adapters/test_glm_xml_parser.py`（文档顺序配对、单个丢失标签的精确还原属性测试、形态良好块逐字节不变、扫描器与被替换正则的随机等价、四种悬空标签病态输入的线性耗时） |
| **代码位置** | `toolkits/llms/adapters/parsers/glm_xml.py::_normalize_arg_tags/_scan_elements/_parse_arg_pairs` |

### BUG-HARNESS-2026-10-07-003 · 工具调用参数被截断或无法解析时，整轮静默结束或把被截断的内容当完整调用执行

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-07 |
| **修复时间** | 2026-10-07 |
| **症状** | 输出在工具调用参数中途被长度上限截断，或参数是无法解析的文本时，真实智能体循环（`create_agent` + `StreamExecutor.execute()` 的脚本化回放）出现两种结果：截断落在字符串值内时，闭合后的前缀可解析，被截断的文件正文被当作完整调用写盘（命令、路径同理）；调用被扣留（不可执行）后整轮没有任何提示地结束，用户看到一个空回合；预期的“重试一次并上报”从未发生 |
| **关联产品** | myrm-agent-harness `agent/streaming` · `toolkits/llms/adapters` · `toolkits/llms/utils` · `agent/errors/diagnostics` |
| **根因** | 三处叠加：（1）被扣留的调用只记录在最终 AIMessage 的 `additional_kwargs["tool_call_recovery"]`，该消息没有 `tool_calls`，LangGraph 据此结束整轮；`process_updates_chunk` 又把“无内容、无 tool_calls”的 AIMessage 当空消息丢弃，恢复处理器永远看不到它，`_try_tool_call_retry` 在真实循环里从未触发；（2）长度截断处理器只在 `finish_reason` 为 `length`/`max_tokens` 时触发且只数 `tool_calls`，空响应处理器同样只数 `tool_calls`，会把扣留消息当空回复叠加恢复并最终抛 `MyrmLLMError`；（3）截断落在字符串值内时 `close_truncated_json` 闭合出的前缀可解析，被当成可安全执行的修复，而路径、命令、文件正文都是“更短但合法”的值；此外 `tool_call_retry` 诊断文案在 5 种语言里缺失，状态事件会泄漏 `[Missing translation: …]` |
| **修复** | 单一谓词 `has_withheld_tool_calls`（`tool_recovery.py`）识别扣留记录；`event_handlers` 保留这类消息；`_handle_length_truncation` 在“长度截断”或“存在扣留调用”任一成立时触发，`_has_tool_calls`（截断与空响应处理器共用）把扣留调用计入工具调用；重试仍最多 1 次、输出预算翻倍（以 `MAX_EPHEMERAL_OUTPUT_TOKENS` 为上限；配置预算已达上限时保持原值，覆盖值不再低于配置预算）、请求前缀只追加一条提示（提示缓存前缀不变），重试失败上报 `tool_call_truncated`（用户可见文案说明该调用未执行，处理建议为重新发送请求，不再提示检查输出文件）；新增 `truncated_json.py::ends_inside_string` 与 `litellm_utils` 的闸门：截断落在字符串值内一律拒绝修复（`truncated_mid_value`，不可执行），数字、字面量、键、容器边界处的截断仍可补全；重试提示改为与成因一致（参数不完整或无效）；补齐 5 种语言的 `tool_call_retry` 文案；流在收到最终元数据块之前断开时，`finish_reason` 记为哨兵 `__stream_dropped__`：用量账本的 finish_reason 桶由空串改为该值，`completion_status` 由 `complete` 改为 `truncated`，并禁止“补全 JSON”式修复；统计截断率的报表需按原始 `finish_reason` 把 `length`/`max_tokens` 与 `__stream_dropped__` 分开，并以 2026-10-07 作为口径分界；上游干净关闭时 LiteLLM 会合成 `stop`，这类流不会落入该哨兵（实测，LiteLLM 1.98.0） |
| **反复次数** | 第 1 次发现 |
| **踩坑** | “不执行”不等于“已处理”：不可执行的调用若不产生下游信号，整轮会静默结束；多个恢复处理器判断“这一轮是否以失败的工具调用结束”必须共用同一个谓词，否则一个放行、另一个把同一条消息当空回复；“过滤空消息”这类清理要检查被过滤对象是否承载恢复所需的元数据；不能只信提供方上报的 `finish_reason`；字符串内部的截断无法靠工具 schema 发现，必须在参数层拒绝；边界处（数字、字面量）的截断在信息上无法与完整值区分，由工具 schema 校验兜底；用户提示要说明后果（“未执行”），而不是内部状态（“参数可能不完整”）；“放大输出预算”的覆盖值必须与配置预算比较，单看上限夹取会把已超过上限的配置预算反而调低 |
| **回归** | `tests/agent/streaming/test_withheld_tool_call_retry.py`（真实智能体循环：成功路径不变、如实长度截断重试一次且预算翻倍、重试请求等于首次请求加一条提示、提供方谎报正常结束、垃圾 JSON、无望场景有界上报、并行调用中一条被扣留；处理器单测与更新流保留规则）· `tests/toolkits/llms/adapters/test_tool_call_argument_recovery.py`（字符串内截断拒绝、边界截断仍补全、谓词与生产者一致）· `tests/toolkits/llms/utils/test_close_truncated_json.py` · `tests/agent/errors/diagnostics/test_error_diagnostics.py`（5 种语言文案齐全）· `tests/toolkits/llms/adapters/test_stream_aggregator.py` 与 `tests/agent/test_completion_status_mapping.py`（断流哨兵进入响应、账本、tracker，并映射为 `truncated`）· `tests/toolkits/llms/adapters/test_stream_aggregator_dsml.py`（标签解析出工具调用后，响应与 tracker 记录 `tool_calls`）· `tests/agent/streaming/test_stream_executor_length_truncation.py`（配置预算低于、等于、高于上限时重试覆盖值从不低于配置预算） |
| **代码位置** | `agent/streaming/event_handlers.py::process_updates_chunk` · `agent/streaming/recovery/stream_recovery_truncation.py::_handle_length_truncation/_has_tool_calls/_try_tool_call_retry` · `agent/streaming/recovery/stream_recovery.py::_handle_empty_response` · `toolkits/llms/adapters/tool_recovery.py::has_withheld_tool_calls` · `toolkits/llms/utils/truncated_json.py` · `toolkits/llms/utils/litellm_utils.py` · `agent/errors/diagnostics/i18n/locales/*.json` · `toolkits/llms/adapters/stream_aggregator.py::finalize_stream` · `agent/types.py::map_to_completion_status` |

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
