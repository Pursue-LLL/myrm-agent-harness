# Myrm Agent Harness — Bugfix Log

> 每次 harness 框架层用户可感知失败/运行时 bug，**必须追加一条**。产品业务 bug 记各产品仓台账（`myrm-agent/myrm-agent-server`）。

### BUG-HARNESS-2026-10-15-002 · 体检的向量库探针每次都拿一份临时内存库自检：真实的嵌入式库因数据目录被锁、不可写或磁盘满而退化成纯内存后，体检、运维快照、支持包仍报「向量库健康」，之后写入的记忆重启即丢

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-15（审计默认挂载的记忆栈时，把探针与 `create_embedded_store` 的退化分支对读，两者没有任何联系） |
| **修复时间** | 2026-10-15 |
| **症状** | ① `create_embedded_store` 打不开数据目录时退化成 `:memory:` 库，只记一条 ERROR 日志；② `check_qdrant_health` 固定初始化 `local_path=":memory:"` 的一次性库、从不碰真实目录，所以这种状态下 `VectorDB` 一律返回 pass 与 `Vector database is healthy.`；③ 用户在 `/api/v1/health/doctor`、`/api/v1/ops/snapshot` 与支持包里看到的是「健康」，记忆其实只在内存里，下次启动消失 |
| **关联产品** | myrm-agent-harness `observability/diagnostics`（`vector_probe.py`、`probes.py`）· `toolkits/vector/qdrant`（`factory.py`）；server 三个读取方：`app/api/health/router.py::system_doctor`、`app/services/ops/snapshot_service.py`、`app/services/system/support_bundle_service.py`，均经 `collect_health_snapshot` / `run_all_diagnostics`，无需改动 |
| **根因** | 探针只验证「库能不能初始化」，没有验证「真实的库是不是正在用」；退化状态只存在于工厂的进程内单例表里（键后缀 `:memory_fallback`），没有对外的查询口 |
| **修复** | ① `factory.py` 新增 `embedded_fallback_paths()`（只列退化库的数据目录，显式要求的 `:memory:` 不算退化；后缀提成 `_FALLBACK_KEY_SUFFIX` 常量，读写同源），`qdrant/__init__.py` 导出；② 探针迁到新文件 `vector_probe.py`（`probes.py` 行数预算），先查退化表：有退化库就直接 FAIL，文案面向用户（「新记忆没有被永久保存」+ 退出其他副本、检查可写与磁盘空间、重启应用），`measured` 写退化库个数，原有的一次性库自检保留在后面；③ `probes.py` 仍按原顺序注册同一个函数，对外名字不变 |
| **验证** | `tests/observability/test_probes.py` + `test_probes_extended.py` + `tests/toolkits/vector/test_qdrant_factory.py` 共 89 项通过（2026-10-15）；新增两条：`TestCheckQdrantHealth::test_fallback_store_returns_fail_even_when_the_throwaway_probe_would_pass`（有退化库时 FAIL，且不再创建一次性库）、`test_embedded_fallback_paths_lists_only_fallback_stores`（正常落盘库与显式 `:memory:` 都不列出，evict 后清空） |
| **局限** | ① 只在体检 / 运维快照 / 支持包被请求时才检查，没有主动推送；② 退化表是本进程的，别的进程里的退化看不到；③ 退化记录随进程存在，目录恢复后要重启应用（或宿主调用 `evict_embedded_store`）才会消失，与文案里的「重启应用」一致；④ 远程 Qdrant（`create_remote_store`）仍不被探测，探针对它仍只做库可初始化的自检；⑤ 探针文案是英文，与 server 侧异常信息统一为英文的约定一致，没有走多语言文案表；⑥ 没有在真实被锁目录上做过端到端复现，退化状态由测试里注入的 `QdrantClient` 构造失败模拟 |
| **反复次数** | 第 1 次发现 |
| **代码位置** | `observability/diagnostics/vector_probe.py::check_qdrant_health` · `toolkits/vector/qdrant/factory.py::embedded_fallback_paths/_FALLBACK_KEY_SUFFIX` · 提交 `b13264595e` |

### BUG-HARNESS-2026-10-14-024 · 技能复盘在宿主没有挂 `on_skill_review_ready` 时照样触发：每个满足条件的会话结束都白做一次复盘 LLM 调用，结果在 `if on_skill_review_ready` 处被丢弃

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-14（核对 server 隐身会话的持久化写入点时） |
| **修复时间** | 2026-10-14 |
| **症状** | `SkillAgentReviewMixin._should_trigger_skill_review` 只看轨迹是否值得复盘，不看有没有人消费结果；宿主不传回调（`_on_skill_review_ready is None`）时，`_trigger_background_skill_review` 仍用抽取模型或主模型做一次轨迹复盘，产出只在 `review.py` 的 `if on_skill_review_ready:` 处被消费，没有回调就什么也没发生，LLM 调用白白花掉 |
| **关联产品** | myrm-agent-harness `agent/skill_agent/review.py`；server `BUG-AGENT-2026-10-14-026`（隐身会话不再挂回调） |
| **根因** | 触发条件与「结果有没有去处」是两件事，写触发条件时没有把后者算进去；复盘的唯一输出就是回调，没有回调的复盘没有任何副作用可言 |
| **修复** | `_should_trigger_skill_review` 开头：`_on_skill_review_ready is None` 时直接返回 `False`；docstring 写明原因 |
| **验证** | `tests/agent/skill_agent` 160 通过、2 失败（`test_skill_agent_privacy_context.py` 两例断言 `auto_extract_memories` 被调度，来自他人未跟踪的 `memory_extraction_scheduler.py`，与本条无关）；新增 `test_no_review_consumer_never_triggers`，去掉守卫后失败、还原后通过；既有用例的宿主桩（`FakeSkillAgent`、`_Host`）补上默认回调，避免被新守卫挡掉；本条涉及文件 `ruff` / `pyright` 无问题 |
| **局限** | 只证明了「无回调不触发」；没有统计过其他宿主是否存在未挂回调却依赖复盘日志的用法（代码里复盘只有回调这一个输出） |
| **反复次数** | 第 1 次发现 |

### BUG-HARNESS-2026-10-14-023 · 保存会话保险库的损坏备份键用 `str.replace(".enc", ".corrupted")`：域名里含 `.enc` 时两处都被改写，备份落到别的域名的键上；`safe_purge_fts5_virtual_table` 没有任何生产调用方，却被 server 文件头与文档当成清库里 FTS5 清理的实现

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-14（复审 server `BUG-AGENT-2026-10-14-020` / `-022` 的清库实现时） |
| **修复时间** | 2026-10-14 |
| **症状** | ① `StorageVaultBackend.backup_corrupted("mail.enc.example.com", data)` 写到 `browser/sessions/mail.corrupted.example.com.corrupted`，与域名 `mail.corrupted.example.com` 的备份同键，后写的覆盖先写的；② `utils/db/fts5.py::safe_purge_fts5_virtual_table` 全仓库只有它自己的测试、`api/__init__.py` 的一条门面导出和三处文档引用，没有任何生产调用；清库里的 `delete-all` / `rebuild` / `optimize` 实际在 server `SafeVaultPurgeService` 里逐表发送，server 文件头与 brand、temp-docs 的文档却写成调用了它 |
| **关联产品** | myrm-agent-harness `toolkits/browser/session_vault/backends` · `utils/db` · `api`；server `BUG-AGENT-2026-10-14-025` |
| **根因** | ① 用 `replace` 改后缀，没有限定结尾；本地文件后端用 `with_suffix`，只改最后一个后缀，所以只有云存储后端有这个问题；② 函数先于调用方写出，调用方走了另一条实现，没人回头删，门面导出又让它看起来是对外能力 |
| **修复** | ① `removesuffix(".enc")` 再拼 `.corrupted`；② 删除该函数、只服务于它的 `ConnectionLike` 协议、门面导出、测试，`utils/db/_ARCH.md` 的描述改为查询净化 / 完整性检查 / 重建 / 自愈 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | 改文件后缀要么用 `removesuffix` / `with_suffix`，要么把存储键的编码放到一个函数里按种类生成；门面里的导出不算调用方，删代码前要在整个仓库（含 server、控制平面、文档）搜一遍 |
| **回归** | `tests/toolkits/browser/test_session_vault_storage_backend.py` 新增 `test_backup_corrupted_only_swaps_the_trailing_suffix`（旧实现下失败，修复后通过）；会话保险库三个测试文件共 96 例通过；`tests/utils tests/api` 1 435 例通过，1 例 `test_token_tracker` 失败来自他人在途改动；`boundary_check`、`check_fractal_docs`、`check_import_resolvability` 通过 |
| **代码位置** | `toolkits/browser/session_vault/backends/storage_backend.py` · `utils/db/fts5.py` · `utils/db/_ARCH.md` · `api/__init__.py` |

### BUG-HARNESS-2026-10-14-022 · 判断“值是密钥还是对密钥的引用”时不认 TypeScript 的非空断言：`apiKey: process.env.GROQ_API_KEY!` 被当成密钥；风险闸门又没有一份“前缀本身就能认出密钥”的形状表可读，只能自己存一份并落后 13 种

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-14（复审 server `BUG-AGENT-2026-10-14-019` 的风险闸门时，逐条验证误拦与漏拦） |
| **修复时间** | 2026-10-14 |
| **症状** | `secret_value.is_reference_value` 认属性链（`process.env.GROQ_API_KEY`），但链尾带 `!`（TypeScript 非空断言）时整个值被当成密钥，TS 代码里 `apiKey: process.env.GROQ_API_KEY!,` 被风险闸门拦下；`leak_detector` 的 33 种厂商前缀形状里，只有一部分单凭前缀就能认出密钥，另一部分（`vercel_`、`fal_`、`telegram_bot` 等）会命中普通标识符，调用方没有办法只取前一部分，server 的闸门因此另存一份清单，比表少 13 种 |
| **关联产品** | myrm-agent-harness `core/security/detection/{secret_value,leak_detector}.py`；server 的 `app/services/risk/{patterns,match_checks}.py`（`BUG-AGENT-2026-10-14-024`） |
| **根因** | `_ATTRIBUTE_CHAIN_RE` 只匹配 `a.b.c`，没有为链尾的 `!` 留位置；形状表 `_API_KEY_PATTERNS` 是一个混合了“强前缀”和“弱前缀”的内部表，对掩码是合适的（宁可多遮），对必须拒绝消息的调用方不合适（不能把名字当密钥） |
| **修复** | ① `_NON_NULL_CHAIN_RE`：三段以上的属性链加结尾的 `!` 算引用，两段的 `john.smith!` 不算（`!` 同样可能是密码字符）；② `leak_detector.DISTINCTIVE_KEY_PATTERNS`：由 `_API_KEY_PATTERNS` 减去 `_WEAK_PREFIX_KEY_NAMES`（telegram_bot、discord_bot_token、twilio_key、databricks_token、cloudflare_token、elevenlabs_key、firecrawl_key、vercel_token、fal_key）派生，新增的形状默认公开，除非明确列为弱前缀；掩码仍用完整的表，召回不变；表里每个形状不带标志位与捕获组，调用方把它们拼成一个交替式时含义不变，`test_the_shapes_can_be_joined_into_one_alternation` 守住这个约定 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | ① `vercel_`、`fal_` 在 600 个文件的抽样里看不到对标识符的误命中，用 `rg -P` 扫整个参考语料得到约 3.5 万处，所以归入弱前缀；抽样看不到不等于不存在；② 链中间的 `!`（`entry!.sessionId`、`process.env.X!.trim()`）没有处理：`_CALL_RE` 与链正则都要为它改写，而 `abc_def!(` 这类字符串同样可能是密码，收益不够；③ 弱前缀表是按语料里的误命中手工列的，没有为每个前缀逐一证明；新增形状默认公开，所以新形状若会命中标识符，要靠 server 侧的样本测试之外的审阅发现 |
| **回归** | `tests/core/security/detection/test_secret_value.py` 补 `process.env.GROQ_API_KEY!`、`process.env.INTELLIGENCE_API_KEY!,`、`import.meta.env?.VITE_TOKEN!` 为引用，`john.smith!`、`my.pass1!`、`Zk9#mango42!`、`process.env.GROQ_API_KEY!x` 仍是密钥；新增 `test_distinctive_key_patterns.py`：弱前缀集合是表的子集、公开的表等于全表减弱前缀、`vercel_`、`fal_` 与短形状不公开且不匹配标识符、常见厂商公开、形状可拼成一个交替式（无标志位、无捕获组、无全局内联标志）。`tests/core/security` 1128 例通过（其中 `detection` 477 例），`ruff`、`mypy` 通过；server 一侧的闸门测试对表里 24 种形状各有一例样本 |
| **代码位置** | `core/security/detection/secret_value.py::_NON_NULL_CHAIN_RE/is_reference_value` · `core/security/detection/leak_detector.py::DISTINCTIVE_KEY_PATTERNS/_WEAK_PREFIX_KEY_NAMES` |

### BUG-HARNESS-2026-10-14-021 · 浏览器登录会话的定期清理把“解不开的文件”当成过期直接删除：保险库密钥重新生成或被换掉后，每次浏览器会话关闭和服务端每 6 小时的维护都会删光全部已保存的登录，且不留 `.corrupted` 备份

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-14（核对服务端新增的每 6 小时登录会话清理的删除语义时，对照 `load` 与 `cleanup_expired` 对“解不开的文件”的两种处理发现） |
| **修复时间** | 2026-10-14 |
| **症状** | `SessionVault.load` 遇到解不开或格式错误的文件，先把原文写成 `.corrupted` 再删除；`cleanup_expired` 对同样的文件直接删除，不留任何备份。后者在两处被调用：`BrowserSession.close()` 与服务端每 6 小时的数据库维护（以及设置页的清理按钮）。`load_or_create_key` 在密钥文件长度不是 32 字节时生成新密钥，之前保存的所有 `.enc` 随即全部解不开，下一次清理就把它们全部删除。同时旧条目仍在内存缓存里时，`load` 还会返回已被删文件的内容 |
| **关联产品** | myrm-agent-harness `toolkits/browser/session_vault`；server 的 `app/core/security/browser_vault.py::cleanup_all_vaults`（全局保险库与每个 Agent 的保险库） |
| **根因** | 清理函数把“解不开 / 解析失败”和“已过期”放进同一个 `except Exception` 分支，一律删除，没有复用 `load` 路径的备份语义；过期时的 `delete` 也在这个 `try` 里，删除本身失败会落入异常分支被再删一次 |
| **修复** | `_check_and_remove_if_expired` 把读取失败（`DecryptionError`、`ValueError`、`TypeError`、`AttributeError`）与过期拆开：读取失败走 `_backup_and_delete_corrupted`（失效缓存、写 `.corrupted`、再删原文件），过期仍直接删除；删除失败不再被当成读取失败 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | ① 备份失败时仍会删除原文件：两个后端的 `backup_corrupted` 都吞掉异常只记警告，与 `load` 路径一致，协议未改；② `.corrupted` 没有保留期限，`list_all` 只列 `.enc`，没有任何清理会扫到它；它是旧密钥加密的密文，价值是人工用旧密钥找回，不是自动恢复；③ 没有处理的：密钥文件长度错误时静默重新生成新密钥（本条只保证不再因此丢掉旧文件），以及清理读文件与删文件之间并发 `save` 的竞态（原有）；④ 触发条件只用真实文件保险库加第二把随机密钥验证，没有在真实桌面部署上复现密钥被换掉的场景 |
| **回归** | `tests/toolkits/browser/test_session_vault_cleanup_backup.py` 8 例，全部用真实文件保险库：换密钥后三个会话全部保留为 `.corrupted` 且字节与原文件一致、乱码文件、三种解密后格式错误（非 JSON、JSON 不是对象、过期时间不是数字）、过期会话删除且不留备份、未过期与无期限会话原样保留且仍可加载、缓存里的旧条目在原文件被清走后不再返回。4 个变异（改回直接删除、去掉 `TypeError` 与 `AttributeError`、去掉 `DecryptionError`、让过期也走备份）分别使 6、2、3、1 例失败；同目录保险库与持久化共 114 例通过 |
| **代码位置** | `toolkits/browser/session_vault/__init__.py::SessionVault._check_and_remove_if_expired` |

### BUG-HARNESS-2026-10-14-020 · 录制合成与诊断包里还有两份邮箱正则，对点号连续串是二次方耗时：2 万字符的 `a.a.a.` 串让诊断包的脱敏跑 0.78 秒，录制的参数槽提取跑 0.30 秒；4 万字符分别是 1.55 秒与 1.30 秒

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-14（风控规则统一邮箱正则时，全仓搜索同形正则） |
| **修复时间** | 2026-10-14 |
| **症状** | `toolkits/computer_use/recording/synthesizer.py` 的 `extract_parameter_slots` 与 `observability/diagnostics_bundle/packager.py` 的脱敏用的邮箱正则 `[A-Za-z0-9._%+-]+@…` 对不含 `@` 的点号连续串回溯，耗时随长度平方增长；诊断包脱敏处理的是任意日志文本 |
| **关联产品** | myrm-agent-harness `toolkits/computer_use/recording`、`observability/diagnostics_bundle`；server 台账 `BUG-AGENT-2026-10-14-019`（同批次的风控规则）；同一问题在隐私管线里的修复见 `BUG-HARNESS-2026-10-14-017` |
| **根因** | 两处各写了一份没有长度上限的邮箱正则，没有读隐私检测的单一来源 `core/security/detection/pii_patterns.py::EMAIL_RE`（长度有界） |
| **修复** | 两处都改为导入 `EMAIL_RE`，替换文本仍是 `***@***.***`；`packager.py` 所在的 `diagnostics_bundle/` 目录当时是未提交的新目录，改动只在工作区，没有被本次提交带走 |
| **反复次数** | 同一个正则第 2、3 处（隐私管线为第 1 处） |
| **踩坑** | 实测（同一台机器，`findall` 耗时）：2 万字符点号串旧诊断包正则 784.9 毫秒、旧录制正则 303.2 毫秒、`EMAIL_RE` 2.0 毫秒；4 万字符 1551.1 / 1301.3 / 5.1 毫秒；10 万字符的普通文本（1695 个邮箱）三者都约 1.4 毫秒，结果相同。行为差异：本地部分超过 64 个字符的串（不是合法邮箱）旧正则整段脱敏，`EMAIL_RE` 只脱敏末尾 64 个字符，前面的字符会留下 |
| **回归** | `tests/toolkits/computer_use/test_desktop_skill_recording.py::test_a_long_dotted_value_does_not_stall_slot_extraction`（2 万字符点号串在 0.1 秒内完成且不产生参数槽）；该文件与 `tests/observability/test_diagnostics_bundle.py` 共 11 例通过，`ruff` 通过；回归用例的耗时阈值依赖机器，旧正则在本机是 0.30 秒 |
| **代码位置** | `toolkits/computer_use/recording/synthesizer.py` · `observability/diagnostics_bundle/packager.py`（未提交） |

### BUG-HARNESS-2026-10-14-019 · 指挥中心「无噪声记忆」卡片的“清除记忆”和“提交事实”只改一个进程内字典：界面提示已清除、代次加一、事实列表清零，用户真正的记忆一条没动，提交的事实也没进任何记忆库

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-14（隐私层终极叩问阶段，核对 BUG-HARNESS-2026-10-14-013 修好的记忆写入门到底挡在哪条写入链路前时，发现它所在的套件没有一处写向真实记忆库） |
| **修复时间** | 2026-10-14 |
| **症状** | ① 卡片的“清除记忆（代次 +1）”调 `/api/memory/noise-free/purge`：界面显示代次加一、事实数归零、“已清除”，而向量库与记忆文件里的真实记忆原样保留；② “提交事实”显示“已提交”并出现在“已持久化事实”列表，但没有进入任何记忆库，下一轮对话读不到、进程重启即消失；③ 这套套件的 PII 网关与真实写入链路（`memory_scanner` 的写前扫描）是两套口径，BUG-HARNESS-2026-10-14-013 补齐的正是前者，却从未挡在任何真实写入前；④ 卡片的用户标识写死为 `default_user`，约 29 处文案是硬编码中文 |
| **关联产品** | myrm-agent-harness toolkits/memory/noise_free_extractor 全包（五个顶层导出 `ConversationTurn`、`ExtractedFactCandidate`、`NoiseFreeAsyncMemoryExtractor`、`NoiseFreeConfig`、`PIISafetyGateway`）、`harness_packaging` 的分发清单条目；server 的 `/api/memory/noise-free/*` 六个端点与对应的服务、Schema；前端指挥中心的卡片与服务客户端。套件的事实只存在进程内，没有需要迁移的数据 |
| **根因** | 提取器把“已提交事实”放在进程内字典 `_facts_store`，清除只是清空这个字典并把代次加一，既没有注入真实的记忆存储，也没有任何写入方或读取方把它与真实记忆库连起来；harness 包只被 server 的这一个服务与自身测试导入，服务只被这一组路由调用，路由只被这一张卡片调用，卡片展示的就是这个演示字典。真实的记忆写入走 `write_service` 与 `memory_scanner`，它们已经覆盖注入 / 凭据 / 密码 / PII 假名化 |
| **修复** | 删除整条垂直链路而不是接线：harness 删 noise_free_extractor 包（含 `_ARCH.md`）、两个测试文件、`toolkits/memory/__init__.py` 的五个导出、分发清单条目，以及只给网关用的 `find_card_shaped_spans`；server 删服务、路由与其注册、Schema、测试；前端删卡片与子组件、测试、服务客户端、`services/memory.ts` 的导出、指挥中心的挂载、硬编码文案基线里的两条与 `_ARCH.md` 的两行。路线图 #88 裁决为不值得做并按台账规则退役，完整原文由台账登记的提交取回 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | ① 先逐符号做零引用盘点：全仓除上述 server 服务、自身测试与卡片外，没有任何生产代码导入这五个导出名；② BUG-HARNESS-2026-10-14-013 修的是被删的网关，条目保留“已修复”的历史结论，只把引用到已删路径的两行改成“已删除”（文档路径引用门禁会拦住指向不存在路径的反引号路径）；③ 隐私检测的真实收益保留在 SSOT 里：`card_context.CARD_CONTEXT_RE` 仍被 server 的风险规则引擎使用，IBAN、卡号上下文、身份证校验等检测器没有动；④ 删除前确认前端卡片之外没有组件消费这些服务函数，删除后 `tsc` 只剩一处与本次无关的看板测试类型错误 |
| **回归** | 无新增行为；删除后 `import myrm_agent_harness.toolkits.memory` 正常且不再暴露 `PIISafetyGateway`，harness 的 `tests/toolkits/memory`、`tests/core/security/detection` 全绿，server 的 `tests/api/memory`、`tests/services/risk` 全绿，前端 `features/memory` 90 个测试文件 542 例全绿，`app.api.memory.router` 导入后路由表里不再有 noise-free 路径 |
| **代码位置** | 无保留的位置；保留并仍在使用的共享部分：`core/security/detection/card_context.py::CARD_CONTEXT_RE` |

### BUG-HARNESS-2026-10-14-018 · xAI 额度耗尽 / 没有套餐时的 403 被诊断成「API 密钥认证失败」，恢复按钮指向「更新 API 密钥」，而密钥本身是有效的

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-14（xAI SuperGrok 订阅登录终极叩问阶段，把 Hermes 里记录的 xAI 403 响应体喂给真实的 `LLMErrorDiagnostic.diagnose`，对照它对同一响应体的分类） |
| **修复时间** | 2026-10-14 |
| **症状** | xAI 对额度耗尽或没有套餐的账号返回 403，体为 `{"code": "personal-team-blocked:spending-limit", "error": "You have run out of credits or need a Grok subscription. ..."}`（取自 Hermes `tests/agent/test_codex_xai_oauth_recovery.py:407-437`，Hermes 把它归为 billing）。真实 harness 执行：`error_type=api_key`、`user_message="API key authentication failed"`、恢复按钮「Update API Key」→ `/settings`。用户被引导去更新一个本来有效的密钥或重新登录订阅，而真正的原因是额度 / 套餐 |
| **关联产品** | myrm-agent-harness `agent/errors/diagnostics/engine.py` · `toolkits/llms/errors/classifier.py`；所有走 `LLMErrorDiagnostic` 的前端错误卡与 IM 回复及 failover 冷却策略，Local / 桌面 / 云托管相同；server 产品台账 `BUG-AGENT-2026-10-14-014`（同一批次：xAI 刷新被 403 拦截的分类） |
| **根因** | `billing` 分支的关键词表没有这句话，而 `api_key` 分支把消息里出现的 `401` / `403` 当作兜底，于是任何带 403 的额度类拒绝都落入 `api_key`；failover 分类器 `toolkits/llms/errors/classifier.py::_BILLING_RE` 同样没有这些短语（并且其中「请充值」被写成了乱码 `请充Value`，该短语从未生效）。真实 `classify_failover_reason` 复现：xAI 的 403 额度 / 套餐拒绝判 `auth_permanent`、`is_quota_exhausted` 为假；429「used all available credits」判 `rate_limit`，会按瞬时限流重试而不是按额度耗尽处理 |
| **修复** | 诊断引擎 `billing_keywords` 与 failover `_BILLING_RE` 同步收录三条短语：`run out of credits`、`used all available credits`、`grok subscription`（诊断引擎的 `billing` 分支先于 `api_key` 分支判定；failover 侧三类响应均改判 `billing` 且 `is_quota_exhausted` 为真）；`请充Value` 改回 `请充值`；`classifier.py` 中 `NormalizedError.body` 与 `_extract_error_body` 的裸 `dict` 标注改为 `dict[str, object]`。恢复动作表与构建函数从 `engine.py` 移到 `recovery_actions.py`，`LLMErrorDiagnostic.get_recovery_actions` 签名不变、转调该函数，`engine.py` 回到 500 行以内并移除行数基线项；其余分类、文案、恢复动作不变 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | 只加短语、不放宽 403：同为 xAI 的 `{"code": "unauthenticated:bad-credentials", "error": "The OAuth2 access token could not be validated."}` 仍判 `api_key`（对照用例）；响应体取自 Hermes、OpenClaw 测试夹具里的 xAI 响应（测试中两个过期令牌用例按 Hermes 文档化的信号拼出），不是自行抓到的原始响应；没有 xAI 过期令牌的原始样本，无法排除其 `error` 文本同时含 `Grok subscription`（两个分类器的 24 小时冷却对 auth 与 billing 相同，误判只影响卡片文案与不重试标志）；xAI 改措辞后会退回改前行为；第一版只给诊断引擎加了一条短语，同一份响应在 failover 分类器里仍判认证失败，且 `engine.py` 因此超出行数基线 1 行；`monthly spending limit`、`run out of available resources` 不收录——已知响应体里它们都与已收录短语同句出现，没有需要它们单独命中的响应；`billing` 的文案是「API 账户余额不足」，对订阅用户的「没有套餐」不完全贴切，没有改动（该处文案与恢复动作模板由他人同时在重构） |
| **回归** | `tests/agent/errors/diagnostics/test_provider_entitlement_classification.py`：8 个额度 / 套餐响应（403 无有效订阅、403 需要订阅、403 额度耗尽、403 团队被封、403 花费上限、429 额度用尽、402、中文充值提示）在诊断引擎判 `billing` 且不可重试，在 failover 分类器判 `BILLING` 且 `is_quota_exhausted` 为真；3 个被拒凭证（过期 OAuth 令牌、bad-credentials、401 无效密钥）两侧都不判 billing，诊断仍为 `api_key`；变异检查：在诊断引擎与 failover 各自删掉三条短语之一（6 个）以及把 `请充值` 改回乱码，共 7 个变异体全部变红，恢复动作表 4 个变异体（url、动作条目、语言前缀回退、空 locale 探测）被既有恢复动作测试杀死 |
| **代码位置** | `agent/errors/diagnostics/engine.py` 的 `billing_keywords`（「2. Billing / insufficient balance errors」段，位于 `api_key` 分支之前）· `toolkits/llms/errors/classifier.py::_BILLING_RE` · `agent/errors/diagnostics/recovery_actions.py::build_recovery_actions` |

### BUG-HARNESS-2026-10-14-017 · 隐私检测的邮箱正则对不含 `@` 的长连续字符是二次方耗时：3 万字符的 base64 / 哈希串让 `classify_content` 与 `redact_pii` 各卡 0.7 秒，30 万字符跑满 2 分半钟 CPU 仍不返回

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-14（隐私层终审阶段，测整条检测管线在长文本上的耗时，30 万字符的连续字母数字串卡住不返回；逐条模式计时后定位到邮箱） |
| **修复时间** | 2026-10-14 |
| **症状** | `"AB12CD34EF56" * n` 实测：邮箱模式单独 `finditer` 1.5 / 3 / 6 万字符 154 / 702 / 2681 ms，字符数每翻倍耗时约 ×4；整条管线 3 万字符 `classify_content` 697 ms、`redact_pii` 744 ms；30 万字符的同类文本两个函数合计跑满 2 分 29 秒 CPU 仍未返回，被中止。任何一段不带空格和 `@` 的长文本（base64 图片、哈希清单、压缩过的数据）都会触发，对话输入、工具回执、记忆写入都走这条管线 |
| **关联产品** | myrm-agent-harness `core/security/detection/pii_patterns.py`；分类、脱敏与可逆替换三处共用这一张表，无需各自改调用方 |
| **根因** | `[a-zA-Z0-9._%+\-]+@…` 的本地部分没有上界：一段 n 个地址字符且不含 `@` 的文本，从每个起点都要一路扫到这段字符的末尾才发现没有 `@`，起点数 × 扫描长度 = O(n²)。该模式自初始导入起如此 |
| **修复** | 本地部分限 `{1,64}`、域名限 `{1,255}`（RFC 5321 的上限），每个起点最多扫 64 个字符，耗时随文本长度线性增长；`pii_patterns.py` 的注释写明上界的用途，`detection/_ARCH.md` 补一句口径 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | ① 先试了开头加 `(?<![a-zA-Z0-9._%+\-])` 的负向后顾，同样线性，但两个邮箱用 `.`、`-`、`_` 粘在一起时（`john@acme.com-jane@acme.org.txt`、`a@b.com_c@d.com`）第二个会漏：上一个匹配结束处仍在地址字符之内，不能再作为起点；隐私检测宁可慢也不能漏，弃用；② 有上界版本与原正则只在本地部分超过 64 个字符时不同：匹配只取最后 64 个字符加域名，前面的部分不被遮；用 30 万条随机串（字母表 `ab1._-%+@` 加空格、逗号、中文）和 5903 个含 `@` 的项目文件（1.1 亿字符、1603 处命中）逐处对比，两者的命中区间 0 处不同；③ 修复后（同一台机器、同一批文本）：3 万字符 `classify_content` 697 → 21 ms，`redact_pii` 744 → 21 ms；30 万字符 218 / 211 ms；100 万字符 796 / 714 ms；真实文本（上述 1.1 亿字符）扫描耗时 2.80 → 2.76 s，持平；④ 同形状的邮箱正则在 PII 表之外还有三处，不属于隐私检测管线，本次没改：`observability/diagnostics_bundle/packager.py:38`、`observability/sanitized_debug_dump/redactor.py:42`、`toolkits/computer_use/recording/synthesizer.py:33`，同样的文本 2 万 / 4 万字符 42 / 306 / 43 ms → 170 / 1119 / 172 ms（×4.0 / ×3.7 / ×4.0） |
| **回归** | `tests/agent/security/test_pii_patterns.py::TestEmailPattern` 11 例（常见写法与带标签的地址、用逗号与用 `.`、`-`、`_` 粘连的两个地址都找全、64 位本地部分、不完整的域名不算；5 种形状的 20 万字符连续文本在 3 秒内扫完，改前同形状 4 万字符就要 1 秒以上）· `tests/agent/security`、`tests/core/security` 全绿 |
| **代码位置** | `core/security/detection/pii_patterns.py::EMAIL_RE` |

### BUG-HARNESS-2026-10-14-016 · 删除对话、分叉回滚、Resume 失败恢复、改写首条消息都在清检查点线程，而检查点包装器没有转发 `adelete_thread`：前三者只在日志里留一条警告、检查点原样留在库里，后者直接抛 `ContinuitySyncError`；同一个包装器所在的浏览器检查点链路（13 个模块）从未接上任何数据

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-14（沿「`aget_tuple` 的反序列化兜底只在这个包装器里」追查检查点包装器的全部调用方时，发现包装器里的数据没有一处被读；随后用真实的 `AsyncSqliteSaver` 调 `adelete_thread` 复现） |
| **修复时间** | 2026-10-14 |
| **症状** | ① 包装器只转发了 `aput / aput_writes / aget_tuple / alist`，没有 `adelete_thread`，调用落到 LangGraph 基类，抛 `NotImplementedError`；五个调用点：`runtime/context/session/session_continuity.py::sync_checkpoint_messages`（持久化历史为空时删线程，抛 `ContinuitySyncError`；撤销 / 重试 / 回退把历史清到空时，server 的 `sync_chat_checkpoint_from_db` 把这个错误一路抛给接口）、server 的 `chat_crud`（删除对话）、`conversation_fork_manager`（分叉事务回滚）、`stream_finalize`（Resume 失败后清检查点）都把异常吞成一条警告，检查点留在库里；`vault_purge_service` 只用 `hasattr` 判断就把 `cleared_checkpoints` 记成 1，从未真正删除；② 浏览器检查点包（`toolkits/browser/checkpoint/`，13 个模块 + 迁移脚本）整条链路从未生效：`metadata["browser"]` 没有任何写入方，`context["browser_checkpoint"]` 只在包内写入、没有读取方，旧包装器把存储放在 `_thread_store`、没有 `thread_store` 属性，server 的 `hasattr(checkpointer, "thread_store")` 恒为 False，`mark_thread_*`、浏览器线程清理任务、`warmup_browser_sessions` 都是空操作；③ `BrowserObservability` 的请求结束回调把协程 `Request.response()` 当同步对象读，每个请求都记成 0 字节（该类没有生产调用方，实际字节统计来自 `NetworkLogger`，所以没有用户可感知的症状） |
| **关联产品** | myrm-agent-harness `runtime/checkpointing`、`toolkits/browser`（`__init__`、`observability`、`session`）；server 的 `app/lifecycle`、`app/ai_agents/general_agent`、`app/services/agent/execution_cache`、`BROWSER_AUTO_WARMUP` 配置项（Settings 为 `extra="ignore"`，用户 `.env` 里残留该项无影响）。用户库里已有的 `checkpoint_threads` 表成为孤表，未删 |
| **根因** | ① 包装器是为一个从未接上的存储（`ThreadStore`）写的，转发清单按它的需要而不是按底层 `AsyncSqliteSaver` 实现了哪些方法来定，漏掉的方法静默回落到基类；② 浏览器检查点链路只在包内自洽：写入方、读取方、属性名彼此对不上，没有闭合过，包内的测试只测各模块自身，不会发现没人调用它们；③ 回调函数签名是同步的，驱动里这个调用是协程 |
| **修复** | ① 新增 `runtime/checkpointing/load_fallback.py::LoadFallbackCheckpointer`：只做一件事，反序列化失败（`pickle` / `dill` 异常与缺参数的构造错误）时返回 `None` 让会话重新开始并留一条警告，其余异常原样抛出；转发的恰好是 `AsyncSqliteSaver` 自己实现的异步方法（`aput`、`aput_writes`、`aget_tuple`、`alist`、`adelete_thread`、`get_next_version`），`aget_delta_channel_history` 有意留给基类，走包装器自己的 `aget_tuple`；`factory.py` 用它取代旧包装器，不再建 `checkpoint_threads` 表；② 删除 `toolkits/browser/checkpoint/` 全包与其测试、`toolkits/browser/__init__.py` 的 12 个导出与惰性分组、`observability` 里的 `checkpoint_metrics`；server 删 `checkpoint_helpers.py`、`lifecycle/browser.py` 里三个空操作函数、`warmup.py` 与 `schedulers.py` 的接线、`stream_pipeline` 里的标记块、执行缓存的 `checkpoint_helper / current_thread_id`、`browser_auto_warmup` 配置项；③ 会话 cookie 与 localStorage 的归一化提取到 `session/storage_state.py`（原先在 `session_persistence` 与生命周期混入里各一份），生命周期混入补继承 `SessionHost` 以取得类型契约；④ `observability._on_request_finished` 改为 `async` 并 `await request.response()` |
| **反复次数** | 第 1 次发现 |
| **踩坑** | ① `BUG-HARNESS-2026-10-14-010` 的 ⑥（恢复编排器传 `ContextType.AGENT`）修的是本条删除的死代码，行为没有退化，那一条的结论不变；② `acopy_thread / adelete_for_runs / aprune` 没有转发：`AsyncSqliteSaver`（langgraph-checkpoint-sqlite 3.1.1）没有实现这三个方法，转发只会换一个异常；③ 兜底的识别口径（消息含 `pickle` / `dill`，或回溯帧在 dill / pickle 里，或缺必需位置参数）是启发式，C 实现的 `pickle` 遇到完全随机的字节抛的异常没有这些特征，不会被识别为可兜底，仍会冒泡，没有放宽；④ 浏览器检查点包有 13 个模块，先做逐符号零引用盘点，只在确认包外没有生产引用后才删；`cleanup_expired_browser_sessions`（清浏览器 vault 的过期目录，与检查点无关，目前没有调用方，另议）与 `PickleSerde`（子代理检查点也在用）没动 |
| **回归** | `tests/runtime/checkpointing/test_load_fallback.py` 13 例，用 `create_checkpointer` 建出的真实 SQLite 检查点（往返、挂起写入、`adelete_thread` 真删、`sync_checkpoint_messages(saver, "chat-1", [])` 返回 2 并删掉 `chat-1` 与 `chat_chat-1` 两个线程、损坏的检查点内容返回 `None` 并留警告、无关异常照常抛出、识别口径的三种路径与存储故障不被误判；另有两例由真实的 LangGraph 编译图驱动：多轮对话保留且 `aget_state_history` 走 `alist`、`adelete_thread` 后清空，存储内容无法解码时下一轮在全新会话里继续），去掉 `adelete_thread`、`aput_writes`、`alist` 的转发与让兜底不吞任何异常这四个变异体（备份、改写、跑测试、逐字节复原）各被至少一例打红；`tests/toolkits/browser/session/test_storage_state.py` 13 例；`tests/toolkits/browser/test_observability_bandwidth_integration.py`（真实 Chromium，本地服务返回 5000 字节：改回同步写法该例跑红，现在统计到的字节数 ≥ 5000） |
| **代码位置** | `runtime/checkpointing/load_fallback.py::LoadFallbackCheckpointer` · `runtime/checkpointing/factory.py::_build_sqlite_saver` · `toolkits/browser/session/storage_state.py` · `toolkits/browser/observability.py::_on_request_finished` |

### BUG-HARNESS-2026-10-14-015 · 本地开发模式下上下文清理永远扫描只读的 `/persistent/.context`，文件访问追踪器在同一个只读目录下开库；会话活动规则依赖的线程注册表从没被填充

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-14（沿「每日上下文清理到底扫描哪个目录」追查，本地模式启动后读 `execution_paths.CONTEXT_ROOT` 与各导入方持有的值） |
| **修复时间** | 2026-10-14 |
| **症状** | ① 本地开发模式在启动时重绑 `execution_paths.CONTEXT_ROOT`，但清理、追踪器等模块在导入时按值复制了这个常量：孤儿清理与会话清理扫描 `/persistent/.context`，在本地不存在，等于从不清理；② 文件访问追踪器的数据库路径同样取自复制值，位于只读的 `/persistent` 之下，打不开；追踪器观察者把导入失败吞掉，读取记录无从建立，「近期读过的文件不清理」的规则无从谈起；③ 清理有两套保留依据（会话活动与读取 / 修改时间），其中会话活动依赖的 `ThreadStore` 注册表从未被填充，规则从未保护过任何文件，却让清理多建一个检查点、让文档写成两条规则 |
| **关联产品** | myrm-agent-harness `runtime/context`（`cleanup`、`cleanup_ops`、`file_access_tracker`、`instance_metrics`、`offload`）、`runtime/paths`、`runtime/artifacts`；server 的每日上下文清理任务（`app/lifecycle/schedulers.py`） |
| **根因** | 路径常量按值导入，而启动时的重绑只改了原模块；清理与追踪器在调用时没有再读一遍 |
| **修复** | ① 清理与追踪器一律在调用时通过 `get_context_root()` 读根目录，追踪器的数据库放在现行上下文根之内；② 保留规则只剩一个窗口 `CONTEXT_RETENTION_DAYS`（14 天）：一个文件在窗口内被读过，或修改时间在窗口内，就保留；删除会话活动规则（`runtime/context/session/session_activity.py`）与没有任何消费者的 `runtime/artifacts` 检查点协议包、`CheckpointForkManagerProtocol`；③ `track_context_file_access_if_needed` 移到 `runtime/paths/access_tracking.py`，让 `execution_paths.py` 保持在行数上限之内；④ server 的每日清理任务不再为已删除的规则构建检查点，读取追踪器起不来时记警告（清理改按修改时间判断），不再是一条 debug 日志 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | ① 新增的端到端用例经观察者走完「读文件 → 追踪器记录 → 清理」整条链路：观察者吞掉导入失败，只看清理或追踪器单个环节不会红；② 追踪器观察者吞掉导入失败，是这个问题长期没暴露的原因，没有改它的吞异常行为（观察者不应拖垮工具调用），而是让 server 在追踪器不可用时写警告 |
| **回归** | `tests/runtime/test_context_root_local_dev.py` 5 例（孤儿清理与会话清理扫描重绑后的根目录、未显式传路径的追踪器用重绑后的根目录、共享追踪器的库在根目录之内、读过的文件在同龄下得以保留而没读过的被清）· `test_cleanup_integration.py` 12 例、`test_cleanup_local.py` 7 例、`test_context_metrics.py` 55 例（随单一窗口改写）· server `tests/lifecycle/test_context_cleanup_job.py` 2 例 |
| **代码位置** | `runtime/context/cleanup.py::CONTEXT_RETENTION_DAYS` · `runtime/context/file_access_tracker.py` · `runtime/paths/access_tracking.py::track_context_file_access_if_needed` · `runtime/paths/execution_paths.py::get_context_root` |

### BUG-HARNESS-2026-10-14-014 · 本地模式放行了「只到被显式导航过的私网源」，但解析到环回 / 链路本地地址的主机名没有被判定，指向云元数据地址的主机名也认不出

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-14（沿 `BUG-HARNESS-2026-10-14-010` 的残余边界追查：守卫只看 URL 里的字面 IP） |
| **修复时间** | 2026-10-14 |
| **症状** | 本地模式（`allow_private_networks=True`）的会话只放行它被显式导航到的私网源，经重定向或脚本到别的私网地址仍被拦。但 DNS 返回 `127.0.0.1` 的主机名（`rebind.test`）在重定向与脚本导航中都按公网放行，会话因此到达该环回服务；返回 `169.254.169.254` 的主机名也没有被当作云元数据地址；`web_fetch` 的本地守卫同理 |
| **关联产品** | myrm-agent-harness `core/security/redirect_hop_guard`（`hop_evaluator`、新增 `name_resolution`）、`toolkits/browser`（`navigation/ssrf_guard`、`domain_filter/http_filter`）、`toolkits/web_fetch/fetchers/target_guard` |
| **根因** | `RedirectHopEvaluator` 只对 URL 里的字面 IP 与 `localhost` 一类固定名判定，不解析主机名 |
| **修复** | 新增 `name_resolution.resolve_addresses`（有界、短暂缓存：2 秒超时、15 秒缓存、最多 256 个主机，失败与超时都返回空，从不抛异常）与 `RedirectHopEvaluator.evaluate_hop_resolved`：只对普通主机名、且有放行名单时才解析一次；只有环回、链路本地、未指定与云元数据的结果才算数，RFC 1918、CGNAT 与 `198.18.0.0/15` 不判（假 IP 代理与 VPN 会给公网域名返回这些地址）；解析失败或太慢时什么都不判。浏览器导航守卫、上下文请求过滤器与 `web_fetch` 本地守卫都走它 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | ① 没有把私网各段都拦：代理与 fake-IP 会把公网域名映射到 RFC 1918、CGNAT、`198.18.0.0/15`（`BROWSER_SYSTEM.md` 已写明），全拦会让这类网络下的浏览整体失败，所以只认环回、链路本地、未指定与云元数据；② 同一次导航里守卫会对同一个主机问好几次，不缓存会让每次导航多出几次解析，失败的结果也要缓存，否则 DNS 不应答的环境每次都等满超时（该延迟在 DNS 被丢包的真实网络里未实测）；③ 残余边界：本次查询与 Chromium 自己的查询之间 DNS 仍可能改变答案（DNS rebinding），只有出站网络层才能彻底阻止，已写进 `BROWSER_SYSTEM.md` 的剩余边界 |
| **回归** | `tests/core/security/test_hop_name_resolution.py` 10 例（真实解析 `localhost`、顺序、IPv6 作用域、无法解析、超时被截断、取消不被吞、同一次导航共用一次查询、失败也被记住）· `test_redirect_hop_evaluator.py` 24 例 · `tests/toolkits/web_fetch/test_target_guard.py` 21 例 · 真实 Chromium：`tests/toolkits/browser/test_hostname_resolution_policy_integration.py` 5 例（用 `--host-resolver-rules` 把假域名映射到环回夹具，并替换进程内 `socket.getaddrinfo` 充当攻击者控制的 DNS：重定向被拦且标签页回到 `about:blank`、脚本导航在发出请求前被拦、元数据地址即使显式导航也被拦、显式导航到解析为环回的主机名仍可用、代理 / DNS 给出的其他地址不被判） |
| **代码位置** | `core/security/redirect_hop_guard/name_resolution.py::resolve_addresses` · `core/security/redirect_hop_guard/hop_evaluator.py::evaluate_hop_resolved` · `toolkits/browser/navigation/ssrf_guard.py` · `toolkits/browser/domain_filter/http_filter.py` · `toolkits/web_fetch/fetchers/target_guard.py` |

### BUG-HARNESS-2026-10-14-013 · 记忆写入门（PIISafetyGateway）自带一套与隐私管线不一致的正则：19 位与分组的银联卡、Amex 分组、分组 IBAN、主流厂商密钥、口语里的密码都放行，物流单号被当 IBAN，遮罩模式把没通过 Luhn 的数字也一并遮掉

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-14（隐私层终极叩问阶段，把同一批输入分别喂给隐私管线与记忆写入门，对不上的逐条用真实的 `PIISafetyGateway.inspect` 复现） |
| **修复时间** | 2026-10-14 |
| **症状** | 16 条带预期的语句里旧网关错 14 条：① 放行：19 位银联卡（连写、`6222 0210 1001 1624 507` 分组）、Amex 分组写法 `3782 822463 10005`、关键词引出的 13 位 Visa、关键词引出且打错一位的卡号、分组 IBAN `DE89 3704 …`、Anthropic / Slack / GitHub 细粒度 PAT / JWT / PEM、口语里的密码（`my password is …`、`我的密码是 …`）；② 误拦：物流单号 `SF1234567890123` 被当 IBAN；③ 遮罩模式对一条规则的所有匹配统一替换，没通过 Luhn 的 16 位订单号也变成 `[credit_card_REDACTED]`，物流单号变成 `[iban_REDACTED]`；④ `snippet_masked` 对密码也露出头两位和尾两位（`pa*****************&3`） |
| **关联产品** | myrm-agent-harness toolkits/memory/noise_free_extractor（已删除，见 BUG-HARNESS-2026-10-14-019）；server 的 noise_free_memory_service 与 /api/memory/noise-free/inspect-pii、指挥中心无噪声记忆卡片是消费方（均已删除），规则名、严重级、`[规则_REDACTED]` 遮罩与构造器签名都不变 |
| **根因** | 网关自带 6 条正则和一份自己的 Luhn，没有读隐私管线的检测表；两处各自演进，隐私层补了分组银行卡、IBAN 校验、关键词引出的卡号、厂商密钥与口语密码之后，写入门仍停在最初的口径。`NoiseFreeConfig.blocked_patterns` 与 `luhn_validate` 没有任何调用方 |
| **修复** | ① `pii_gateway.py` 不再带正则与 Luhn，改读隐私管线的检测器：`IBAN_RE`、`CHINA_ID_RE`、`SSN_RE`、`BANK_CARD_RE` + `is_confirmed`、`card_context` 的关键词引出的卡号、`password_heuristic.find_password_spans(strict=False)`（召回口径，与分类器、脱敏器一致）、`leak_detector`；② 写入门是存储硬门，一条语句漏过去会永久入库、被拒只损失一条事实，所以比隐私管线多三处更严的口径，保住旧网关本来拦得住的：15 或 16 位数字通过 Luhn 即视为银行卡（不论哪个网络）、身份证与 IBAN 只看形状不要求校验位（写错一位仍是证件号）、裸 `secret:` / `secret=` 后的值视为凭据（隐私管线只认 `api secret` / `secret key`，因为单独的 secret 是日常用词）；③ 按文本区间命中，按 IBAN → 身份证 → SSN → 银行卡 → 凭据的顺序认领字符，重叠处前者胜、同一规则内起点靠前者胜（起点相同取更长的区间），已接受的命中保持有序且互不重叠，新区间只和左右两个邻居比较，遮罩只替换命中的字符；④ 密钥判定走 `scan_for_leaks`、遮罩走 `redact_leaks`（与记忆写入链路 `content_scan` 同口径：长令牌保留前 6 后 4，形如 `[REDACTED:<名>]`），一条语句只报一条 `secret_token_key`；密码与密钥的 `snippet_masked` 一律为 `***`；⑤ `card_context` 新增 `find_card_shaped_spans`（只给卡号的形状，不含关键词），由网关再加 Luhn；同一串分组数字从每个后续分组起也各给一个区间（允许重叠），`in 2026 5018 5260 1815 9080` 里的卡号是后四组，只取最左的四组会把它压在年份后面；⑥ 删除没有调用方的 `luhn_validate` 与 `NoiseFreeConfig.blocked_patterns` |
| **反复次数** | 第 1 次发现 |
| **踩坑** | ① 第一版想完全委托给隐私管线、不留任何自有口径，用 3505 条语句（公开的卡号多种写法、IBAN、身份证、密钥、密码、良性语句，加 3000 条随机数字）新旧对比，发现两处回归：前缀表不认 Maestro / Mir / RuPay / Troy 的裸号（旧网关靠通用 Luhn 拦得住）、`secret: abcdef1234`；所以保留上面三处更严的口径，没有照搬；② 身份证与 IBAN 一开始也要求校验位，后来改为只看形状；形状的误报实测：约 2.7 万个项目文件、2.47 亿字符里 IBAN 形状 64 处、59 处有效，其余 5 处全是测试里故意写错校验位的用例；③ 第一版把通用 Luhn 放宽到 13–19 位，随机数字在 17–19 位的误拦率升到约 10%，13 位毫秒时间戳也被拦；改回 15 / 16 位，随机 15 / 16 位数字的误拦率 10.07% / 9.62% 与旧网关完全一致，17–19 位只剩隐私管线前缀表本来就判为银行卡的约 2.5%（2.56% / 2.42% / 2.51%），13、14 位为 0；④ 旧遮罩把整个密钥换成标签，现在沿用 SSOT 的 `redact_leaks` 会留下令牌的前 6 后 4 位，原来断言 `[secret_token_key_REDACTED]` 的用例改为断言原密钥不在输出里、出现 `[REDACTED:`；⑤ 性能（中位数，每组 7 × 2000 次）：每次 `inspect` 24 字 4.9 → 40.9 µs、120 字 16.9 → 97.5 µs、卡号语句 11.8 → 74.9 µs、2000 字 115 → 1170 µs，是旧网关的 5.8–10.2 倍，开销主要来自 `scan_for_leaks` 的 40 多条模式与熵扫描，仍在毫秒以内，且每条候选事实入库前只调一次；⑥ 新旧最终对比：3505 条里 3213 条判定相同、291 条新网关多拦（卡号的分组与长度写法、分组 IBAN、厂商密钥、口语密码，另有 16 条随机 17–18 位数字被前缀表判为银行卡）、1 条旧网关拦而新网关放行（物流单号，即被修掉的误报）；⑦ 有意缩窄一处：旧正则的卡号分组允许任意空白（含换行、制表符）作分隔，新口径只认空格与连字符，与隐私管线一致；⑧ 顺带看到、不在本次范围：`extractor.py::commit_extracted_fact` 在 `mask_pii_instead_of_reject=True` 时仍先按 `is_clean` 拒绝，“遮罩后入库”的分支走不到（server 配置为 False，不受影响）；⑨ 第一版认领字符时把每个新区间与已接受的全部命中逐个比较，命中数 n 时是 O(n²)，而 `/api/memory/noise-free/inspect-pii` 的 `statement` 没有长度上限：`"card 4111 1111 1111 1111 ok. " * n` 实测 n=1000（2.9 万字）、5000（14.5 万字）、20000（58 万字）旧网关 6–7 / 29–36 / 121–157 ms，新网关 70 / 1209 / 17506 ms；改为按起点有序保存、用 `bisect` 只看左右邻居后为 31 / 264 / 681 ms，随文本长度线性增长（慢于旧网关 4–7 倍，cProfile 显示耗时在每处卡号的 Luhn 与 `inside_iban` 上），3505 条新旧对比的判定与改前逐条一致；⑩ 审查时用 3 万条随机拼接语句（15 种敏感片段与良性句子混排）复核，召回无遗漏，但遮罩模式下 `581-24-4361 4220 4244 7320 5290` 的卡号没被遮掉：`find_card_shaped_spans` 只给最左的匹配，卡号前有一组四位数字时真正的卡号被压住。专测未列入前缀表的网络（5018 / 6759 / 9792 / 2200 / 6304 开头）的 2000 条分组卡号，前面带 `in 2026 `、`room 1204 ` 等四位数字：旧网关漏 1794 条，改前的新网关漏 897 条，每个后续分组都给区间后漏 0 条；代价是 5 / 6 / 8 组随机四位分组数字的误拦从 10.02% / 9.86% / 18.87% 升到 18.86% / 27.12% / 40.63%（4 组不变，9.90%），这种写法（5 组以上、每组恰好 4 位）在记忆语句里罕见，误拦只损失一条事实，按存储硬门的取舍接受 |
| **回归** | `tests/toolkits/memory/test_pii_gateway.py` 85 例（公开卡号与未列入前缀表的网络裸号、分组写法、卡号前紧挨另一组四位数字、关键词引出的异常长度与打错一位的卡号、不是卡的数字、卡号紧挨 IBAN、IBAN 内的数字不算卡、IBAN 各种写法与校验位写错仍拦、物流单号不是 IBAN、身份证与 SSN、8 种厂商密钥与私钥块、口语与赋值写法的密码与不算密码的句子、遮罩只替换命中字符、审计字段、与分类器同判、关掉隐私开关仍拦、2 万处卡号的 58 万字符长语句在 8 秒内查完并逐处遮罩，改前实测 17.5 秒）；旧网关跑前 80 例有 32 例红；`test_noise_free_extractor.py` 4 例（遮罩断言按新口径修改）· `tests/agent/security`、`tests/core/security`、`tests/toolkits/memory` 全绿 |
| **代码位置** | 网关与 `find_card_shaped_spans` 均已删除，见 BUG-HARNESS-2026-10-14-019 |

### BUG-HARNESS-2026-10-14-012 · 隐私层不认 IBAN：连写的 IBAN 整串送进模型，分组书写的被当成“可见信用卡”打码成 `DE89 **** **** **** 0130 [PII:credit_card] 00`；另有约 3.6% 的分组数字 IBAN 因数字恰好通过 Luhn 被判成银行卡（S3）

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-14（隐私层终极叩问阶段，沿"哪些真实用户会贴的账号类数据没被检测"追查；用真实的 `classify_content` / `redact_pii` 复现，并把模式表里的 IBAN 项摘掉得到改动前的行为） |
| **修复时间** | 2026-10-14 |
| **症状** | ① 连写的 `DE89370400440532013000`：分类 S1、脱敏计数 0，原样发给模型；② 分组书写的 `DE89 3704 0044 0532 0130 00`：只有中间 16 位数字被 `credit_card_visible` 命中，输出 `DE89 **** **** **** 0130 [PII:credit_card] 00`——标签错成信用卡，国家码、校验位与尾部两位仍明文；③ 用 3.56 万个随机数字账号部分的有效 IBAN（89 国）实测，连写的 0.65%、分组的 3.60% 会被银行卡模式命中并通过 Luhn，判成 S3：同一种数据，默认策略下被当银行卡打码、配了本地模型时被强制走本地，策略为 S3=block 时被拦，而其余 96% 只是 S2 |
| **关联产品** | myrm-agent-harness `core/security/detection`（`iban`、`pii_patterns`、`pii_classifier`、`pseudonymizer`）、`agent/security/detection/pii_redactor`；分类、脱敏与可逆替换三处共用同一张模式表，无需各自改调用方 |
| **根因** | 模式表里没有 IBAN；IBAN 不是只靠正则能识别的类型（任何 `[A-Z]{2}\d{2}[A-Z0-9]{11,30}` 形状都可能是别的东西），需要国家长度与 mod-97 校验才可信；银行卡模式不知道自己匹配的数字可能是账号的一段，`is_confirmed` 只看值、不看这串数字在文本里的位置 |
| **修复** | ① 新增 `core/security/detection/iban.py`：`IBAN_LENGTHS`（SWIFT 注册表 89 国的总长度）、`IBAN_RE`（按长度分支构造：国家码 + 2 位校验位 + 账号部分，连写或 4 位一组、最后一组 1–3 位，大小写均可，两侧不得紧贴字母数字）、`iban_valid`（国家已知、长度恰好、mod-97 余数为 1）、`inside_iban`（某段文本是否落在有效 IBAN 之内，只看它之前可能起始 IBAN 的一小段窗口，成本不随文本长度增长）；② `S2_PATTERNS` 新增 `iban`（S2：能收款但不能凭它付款，与可见卡号同级），排在 `credit_card_visible` 之前，脱敏流水线同序，`DE89 3704 … 00` 一次命中，输出 `DE** **** **** 3000 [PII:iban]`（保留国家码与末 4 位，同银行卡的末 4 位口径）；③ `is_confirmed(name, value)` 改为 `is_confirmed(name, match)`：IBAN 要过 mod-97，银行卡除 Luhn 外还要“不在有效 IBAN 之内”；分类器的 S2 路径也经过它（此前只有 S3 路径校验），脱敏器的银行卡掩码同源；④ 可逆替换新增类型 `<IBAN_n>`，并丢弃落在另一项之内的项（分组 IBAN 内的 4-4-4-4 数字同时是“可见卡号”，二者各得一个伪名会往存储里多写一条从没发出去的映射、计数也多算一次）；⑤ 校验位逻辑与国家长度表独立于被测代码复核：长度取自 python-stdnum 的 SWIFT 注册表衍生数据与维基百科的注册表摘要，89 国逐项一致 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | ① 第一版正则把尾部写成“最后一组 1–3 位可选”，长度是 4 的倍数的国家（奥地利 20、比利时 16、西班牙 24）后面紧跟 1–3 个字母的单词（`… 3201 und`、`… 1332 and`）时，会把单词吞进匹配，校验失败后整串丢失；改为按每个长度各写一支、只读恰好那么多字符，并用这些国家加跟随单词的用例锁住；② 起初想给银行卡模式加“前面不是国家码+校验位”的后行断言，但分组 IBAN 的第二、三个 4 位窗口前面是数字而不是国家码，断言挡不住，改为按 `inside_iban` 看文本位置；③ 性能先用“先测无 IBAN、再测有 IBAN”的非交替 A/B，得到 +2.2…+12.0%，换成每次交替、各 60 次取中位数、分阶段计时后，两轮里 classify 的变化 −0.39…+0.77 ms、redact −1.72…+1.35 ms（2 万–3.9 万字符，基线 17–42 ms），classify+redact 合计变化在 −3.0% 到 +4.2% 之间（噪声量级）；单独一次 IBAN 正则扫描 0.6–1.0 ms；④ 想过用全局 `IGNORECASE` 之外的写法提速，对三个负载实测一个快一个慢，没有收益，保留更简单的写法；⑤ 对约 2.7 万个文件、2.465 亿字符的项目文本（harness / server / frontend / 文档 / 本地化文件）扫描，IBAN 形状的 53 处里 49 处有效，全部是本次的模块、用例与一处既有测试夹具（`test_noise_free_extractor.py`），真实代码与文档里 0 处误报；⑥ `tests/architecture` + `tests/scripts` 共 14 例红（分形头缺失、分发清单、行数基线、tool_registry、`_ARCH.md` 清单、wheel 资产、临时文档链接），逐条看报错，指向的都是他人在途改动的文件（two_stage_search_extract、skill_agent、skills/curator、已被删除的 `agent/security/audit_pack` 与 `delegation` 等），没有一条提到 `iban.py` 或 `core/security/detection`（该目录的清单检查通过，行数门里也没有本次改动的文件） |
| **回归** | `tests/agent/security/test_pii_iban.py` 172 例（14 个注册表公布的 IBAN 的两种写法、89 国逐一构造的有效 IBAN 的两种写法整串匹配、小写、跟随单词不被吞、校验位错 / 差一位 / 多一位 / 未知国家 / 紧贴字母 / 连字符 / 双空格 / UUID / SHA-1 等反例、遮罩格式、分组 IBAN 只算一次且不再是信用卡、二次脱敏不变、按级别只遮自己那一级、“数字恰通过 Luhn 的 IBAN”不再是银行卡但真卡紧挨着 IBAN 仍是卡、`inside_iban` 的边界与窗口、可逆替换往返与同一 IBAN 同一伪名、S3 轮不动它）· `test_pii_patterns.py` 15 例（`is_confirmed` 新签名、IBAN 校验、卡号在 IBAN 内不算卡）· `tests/agent/security`、`tests/core/security/detection` 3261 例全绿 |
| **代码位置** | `core/security/detection/iban.py::IBAN_RE/iban_valid/inside_iban` · `core/security/detection/pii_patterns.py::S2_PATTERNS/is_confirmed` · `core/security/detection/pii_classifier.py::_built_in_s2` · `core/security/detection/pseudonymizer.py::_drop_contained` · `agent/security/detection/pii_redactor.py::_redact_iban/_redact_bank_card` |

### BUG-HARNESS-2026-10-14-011 · 隐私层的"按级别生效"不成立、银行卡与手机号漏检：一条消息同时含 S3 与 S2 内容时，S3 的脱敏把 S2 一并抹掉（S2=warn 形同虚设），S2=block 时没有 S2 内容也被拦；万事达 2 系 / JCB / Discover / Amex 分组写法、带有效期的卡号、美国本地写法的手机号、万事达 Maestro / Mir / RuPay / Troy 与带笔误的卡号都漏进模型

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-14（隐私层终审阶段，沿"用户在设置里选的每级动作到底作用在哪段文本上"追查；每条都用真实的 `classify_content` / `redact_pii` / `apply_pii_actions` / `pseudonymize_text` 调用复现，先在改动前的源码副本上看红，再改，再量） |
| **修复时间** | 2026-10-14 |
| **症状** | ① 默认策略（S2=warn、S3=redact）下，含身份证与手机号 / 邮箱的消息，手机号与邮箱也被打码（日志 `Redacted 3 s3 items`），S2=warn 的"只记录不改动"没有兑现；反过来 S2=redact 时，同一条消息里的 S3 内容（卡号、密码）也被 S2 这一步抹掉；② 策略 S2=block、消息只含 S3 内容时，也被当作含 S2 内容而拦截，拦截提示写成 `s3-level`；③ 万事达 2 系（2221–2720）、JCB、Discover、Amex 的 4-6-5 分组写法不被识别；`card 4532 0151 1283 0366 12/28` 把有效期的 `12` 吞进第五组，Luhn 校验失败，整张卡只算 S2 的"可见卡号"；④ 美国本地写法 `(415) 555-2671` / `415-555-2671` 不是敏感信息；⑤ Maestro / Mir / RuPay / Troy 号段与带笔误的卡号即使写着"card number is"也原样送进模型；⑥ 脱敏返回的计数把"校验不过、没有改动"的匹配也算进去（对已脱敏文本再脱敏一次，计数仍不为 0）；⑦ 设置页预览在 S2=block 且消息同时含卡号与手机号时显示"S3 · 拦截"，而真实一轮的提示是 `s2-level`，徽标与动作对不上；⑧ `contains_level` 对已关闭的策略返回 True（`classify_content` 返回 S1），公开函数两处口径不一；⑨ 校验器 `luhn_valid` / `china_id_valid` 用 `isdigit()` 判断，`²` 这类“数字但不是十进制”的字符会让 `int()` 抛 `ValueError`（现有模式只匹配十进制数字，生产路径不可达，但函数已是公开名） |
| **关联产品** | myrm-agent-harness `core/security/detection`（`pii_classifier`、`pii_patterns`、`card_context`、`pseudonymizer`）、`agent/security/detection/pii_redactor`、`agent/middlewares/security`（`pii_actions`、`user_input_guard`、`privacy_preview`）、`agent/middlewares/tooling/_tool_helpers`；server 设置页的隐私预览（`POST /config/privacy-preview`）随同一函数得到修正，server 代码未改 |
| **根因** | ① `redact_pii` 不分级别，一次把 S3 与 S2 的规则全跑完；`apply_pii_actions` 逐级调用时，每一级的动作都作用在两级的全部内容上；② `levels_to_process` 对检出 S3 的文本一律追加 S2，不看文本里有没有 S2 内容；③ 银行卡号段只收 `62|4\d|5[1-5]|3[47]`，第五组写成 `\d{1,3}` 会吞掉有效期；④ 美国手机号只有带 `+1` 的国际写法；⑤ 号段表是封闭集合，Luhn 通不过就丢弃，没有"文本自己说这是卡号"这条证据；⑥ 流水线对匹配计数，不看校验器是否把它原样放回 |
| **修复** | ① `redact_pii(content, custom, levels)` 只跑所给级别的规则（默认两级，行为不变），`apply_pii_actions` 逐级只传该级；② `levels_to_process(content, level, policy)` 仅当 S2 的动作不是 warn 且文本里确有 S2 内容（新增 `contains_level`）才追加 S2；拦截提示取动作为 block 的那一级，预览同理；③ 号段改为 Visa 4、万事达 51–55 与 2221–2720、银联 62、Amex 34/37、JCB 3528–3589、Discover 6011/644–649/65，整段 15–19 位或同一分隔符分组（4-4-4-4；银联第五组恰好 3 位，先于 16 位分支尝试；Amex 4-6-5），有效期不再并入；④ 新增 `us_phone`（区号与交换码不以 0/1 开头，可带 `1-` 前缀；`+<国家码>` 之后留给国际号码规则，同一个号码不会被两条规则各找一次）；⑤ 新增 `card_context.find_card_number_spans`：卡关键词（`银行卡/信用卡/储蓄卡/借记卡/卡号/bank card/credit card/debit card/card number/card no`，裸 `card` 不算）后 16 个非数字字符以内的卡号形状（13–19 位连写、4-4-4-4、4-6-5/4-6-4），分类器记为 S3 `bank_card_context`，脱敏与可逆替换共用同一函数；⑥ `_apply_redactions` 对校验器不改动的匹配既不替换也不计数；⑦ 模式表与校验器搬到 `pii_patterns.py`（公开名，`pii_classifier.py` 461 → 302 行），模式与表逐项比对一致；⑧ 新增 `pii_actions.blocking_level`，输入守卫与预览共用，预览在拦截时报告拦下文本的那一级；⑨ `contains_level` 先看策略是否启用；⑩ 校验器改用 `isdecimal()`；分类器与可逆替换原先各写一遍的“按名字找校验器”收为 `pii_patterns.is_confirmed`，银行卡去分隔符再 Luhn 收为 `bank_card_valid`，脱敏器去掉重复的掩码拼接与跨度替换循环 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | ① 起初想给 `PrivacyPolicy` 加 `action_at` 方法，被只带 `s3_action/s2_action` 属性的 MagicMock 策略的现有用例拦下，改成 `pii_actions.action_at` 模块函数；② 原型把卡片关键词后的数字写成 `\d(?:[ -]?\d){11,18}`，会把有效期 `12` 吞进卡号、还会把 12 位会员卡当成卡，改为按形状匹配；③ 带有效期的卡号漏检不是号段问题：实测 `card 4532 0151 1283 0366 12/28` 对 Visa 也只得 S2，才与号段一起改正则；④ 新模式一度让 2 万字符无 PII 文本的 classify+redact 慢约 10–13%（26.6–27.5 ms 对 24.2–24.4 ms），拆开量：银行卡正则 0.91 ms、关键词扫描 0.74 ms，分别加"先看是不是数字"与"先看有没有 卡/card"两道廉价前置，spans 逐项一致，回到噪声以内（24.7–25.4 ms）；⑤ 机器负载均值 60+ 时 `TestLinearTime` 与计时类用例会随机红，与本改动无关（`scan_for_leaks` / `redact_leaks` 不经过这些模块）；⑥ 自写的用例会自证：号段表是对着自己写的卡号调的，所以另加一组支付服务商文档公布的测试卡号（27 个 Luhn 有效，号段表召回 23，漏的 4 个是 13 位 Visa 与 3 个 Diners，均为文档写明的已知边界，带关键词时由 `card_context` 找到）；⑦ 召回的代价用 40 万个随机 16 位数实测：被判为 S3 的比例由 1.76% 升到 2.46%（新增的万事达 2 系 / JCB / Discover 号段再乘 Luhn 的 1/10），对真实代码与文档语料（约 110 MB、15,820 个文件）的扫描则没有任何一处真误报；⑧ 数字密集的工具结果略慢：3.9 万字符的纯数字表 22.6 → 24.1 ms（+7%，`us_phone` 约占其中 0.9 ms），2 万字符普通文本 classify+redact 23.4–23.7 → 24.4–25.5 ms，短消息在噪声以内，混合内容与 S2≠warn 的组合因不再重复脱敏反而更快（4.7 万字符数字 JSON，S2=redact：57.8–63.0 → 35.0–35.4 ms） |
| **回归** | `tests/agent/middlewares/test_security_pii_level_scope.py` 22 例（按级别脱敏、S2 存在性检查、拦截提示与预览、`blocking_level`、关键词卡号走默认策略与可逆替换）· `tests/agent/security/test_pii_card_brands.py` 71 例（每个网络与号段边界、越界与 Luhn 失败的反例、有效期不被吞、二次脱敏不变、替换后可还原、支付服务商公布的测试卡号；初版 46 例在改动前 27 红 19 绿）· `test_pii_patterns.py` 12 例（校验器、非十进制数字不抛错、`is_confirmed`）· `test_pii_classifier.py::TestContainsLevel` 4 例 · `test_pii_us_phone.py` 61 例（写法、`+1`/其他国家码的去重、非号码反例；初版 55 例在改动前 28 红 27 绿）· `test_pii_card_context.py` 59 例（其他网络与笔误卡号、中英关键词、反例含裸 `card`/`discard number`/12 位/20 位/换行/过远；改动前 37 红 22 绿）· 周边套件 `tests/agent/security`、`tests/agent/middlewares`、`tests/core/security`、`tests/agent/event_log`、`tests/agent/context_management` 7051 例全绿，server 隐私相关 96 例全绿（针对本地 harness）；其余红的两例 `test_skill_agent_privacy_context.py::TestCleanupSessionPrivacy::test_auto_extract_*` 在改动前的源码上同样红 |
| **代码位置** | `agent/security/detection/pii_redactor.py::redact_pii`（`levels`）、`::_apply_redactions` · `agent/middlewares/security/pii_actions.py::action_at/blocking_level/levels_to_process` · `agent/middlewares/security/privacy_preview.py::preview_privacy_policy` · `core/security/detection/pii_classifier.py::contains_level/_classification_at` · `core/security/detection/pii_patterns.py::BANK_CARD_RE/US_PHONE_RE/is_confirmed/bank_card_valid` · `core/security/detection/card_context.py::find_card_number_spans` |

### BUG-HARNESS-2026-10-14-010 · 公网跳转器能把云托管浏览器带到环回 / 内网页并读出内容：文档注入路由在驱动里吞掉重定向、地址栏仍是公网 URL；本地模式没有任何私网与元数据防护；web_fetch 的 SSRF 拦截被降级到下一层绕过

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-14（终审阶段，沿「重定向防护在真实浏览器里到底看见了什么」追查；每条都用真实 Chromium 加多服务器环回重定向链，统计服务端按 `(方法, 路径)` 收到的请求，先在改动前的源码副本上看红，再改，再量） |
| **修复时间** | 2026-10-14 |
| **症状** | ① 云托管默认策略（`allow_private_networks=False`）下，公网跳转器 `httpbin.org/redirect-to?url=http://127.0.0.1:<端口>/secret` 把会话带到环回服务：改动前 `session.navigate` 正常返回，标签页 URL 仍是 httpbin 的地址，`body` 文本读出 `INTERNAL-ADMIN-PANEL`，环回服务收到 1 次 GET；改动后抛 `BrowserNavigationBlockedError`，标签页回到 `about:blank`，读不到内容（环回服务仍收到 1 次盲 GET，见踩坑 ⑤）；② 根因在每个池化上下文都装的文档注入路由：`route.fetch()` 默认在驱动内跟随最多 20 次重定向，页面被 `fulfill` 成最终响应，所以页面 URL 停在跳转前的地址、`request.redirected_from` 为空（加载后的逐跳复验无链可走）、各跳不经过任何路由过滤器；同一路由对无法改写的响应（非 HTML、附件、POST 的应答）调用 `route.fallback()` 让浏览器再请求一次，于是非 HTML 文档服务端收到 2 次、表单 POST 提交 2 次（实测 `/plain`、`/json` 各 2 次降为 1 次）；③ 本地模式（`allow_private_networks=True`）：`goto_with_ssrf_guard` 直接 `page.goto`，不做任何检查；006 之后上下文过滤器在标志为真时整段跳过私网与元数据校验，公网页面可以用 30x 或 meta refresh 把会话带到云元数据端点或任意局域网地址；④ 导航守卫：路由中止使 `goto` 抛错时，调用方拿到的是通用 `net::ERR_FAILED` 而不是策略原因；被拒绝的 URL 让标签页停在 Chromium 的错误页；加载后才判出违规的文档仍留在标签页里可读；⑤ web_fetch：`HttpFetcher` 遇到被拦的跳转直接 `return None`，路由器把它当成这一层失败，降到浏览器层与隐身层（`StealthFetcher` 没有任何 SSRF 检查，也不看最终落地的 URL），被拦的地址换一层就取到了；本地模式下 HTTP 层连用户显式请求的 `localhost` 也拦；`2130706433`、`0x7f.1`、`0177.0.0.1` 这类旧式数字写法在字面分类与实际连接上口径不同；上一跳的固定 `Host` 头会带进下一跳的请求（下一跳不需要固定时也不清除）；⑥ 崩溃恢复：`ParallelRecoveryOrchestrator.recover_all` 把字符串 `"AGENT"` 当 `context_type` 传给 `BrowserSession`，新上下文键必经 `pool/browser_pool.py:318` 的 `context_type.value`，按代码走向应抛 `AttributeError`（改动前的红测只证明传入的是字符串，没有一路跑到池里）；更早一步还有第二处缺陷：`find_incomplete_tasks` 用 `checkpoint.get("ts", 0) / 1000` 构造 `RecoveryContext`，真实 LangGraph 检查点的 `ts` 是 ISO-8601 字符串，`str / int` 抛 `TypeError`，被逐线程的 `except Exception` 吞掉只记一条 ERROR，扫描返回 0 个上下文，恢复走不到 `ContextType` 那一步（该行自初始导入 `00efa9a1d` 起存在；用真实 `AsyncSqliteSaver` + `IncrementalSessionCheckpointer` + `ThreadStore` 实测 `find_incomplete_tasks -> 0 context(s)`）；原有 `test_e2e_recovery.py` 把 `ts` 造成整数 `1000000`，恰是错误代码假设的形状，9 处夹具一直绿；该路径由 `browser_auto_warmup` 开关门控（默认 False，`myrm-agent-server/app/config/settings.py:638`），线上只有开了开关的部署受影响 |
| **关联产品** | myrm-agent-harness `toolkits/browser`（`enhancers`、`navigation`、`domain_filter`、`utils`、`checkpoint`）、`toolkits/web_fetch`（`fetchers`、`engine`）、`core/security/redirect_hop_guard`、`utils/url_syntax.py`；server 本地模式在 `app/ai_agents/general_agent/tool_setup.py:885` 仍传 `allow_private_networks=is_local_mode()`，未改 server 与前端。受影响面：所有允许智能体浏览公网的云托管部署（①②④⑤），本地 / 桌面模式（③）；真实 Patchright Chromium（macOS）实测，Linux、Windows、Camoufox 未实测 |
| **根因** | ① patchright 不对文档重定向的每一跳触发路由（实测），所以重定向链只能在加载后经 `request.redirected_from` 判；注入路由在驱动里把链吞掉，等于把这唯一的一道检查关掉；② 本地模式的「放行私网」是一个布尔值而不是「放行哪个源」，要么全查要么全不查；③ web_fetch 把拦截结果当成「这一层失败」而不是「这个 URL 被禁」，没有终止语义 |
| **修复** | ① `enhancers/inject_route.py`：`route.fetch(max_redirects=0)`，只有 HTML 响应才改写，其余原样 `route.fulfill(response=response)`，不再 `fallback` 重发；30x 原样交还浏览器、由浏览器自己跟随，页面 URL 随之更新，每一跳只发一次；② 浏览器侧两套策略共用 `redirect_hop_guard`：云托管（无授权集）仍由 `async_pin_url` 解析后要求所有地址为公网；本地模式（有授权集）只对字面主机分类、不做 DNS，`PrivateOriginGrants`（按 `BrowserContext` 登记，`toolkits/browser/utils/private_origins.py`）记下会话显式导航过的私网源，仅这些源放行，跳到别的私网源仍拦，云元数据端点永远拦；`http_filter` 在标志为真时只复验 document，子资源不拦，名单与资源规则对被路由的请求照常生效；③ `goto_with_ssrf_guard`：先检查请求 URL 再 `goto`（被拒时标签页保持原页），`goto` 因中止而抛错时抛出已记录的策略原因，加载后才判出违规时先把标签页重置为 `about:blank` 再抛；④ web_fetch 新增 `fetchers/target_guard.py::FetchTargetGuard`：云托管为 DNS 固定，本地模式为字面分类加「显式请求的源」授权加旧式数字 IPv4 规范化，两种策略都叠加 `MYRM_ALLOWED_INTERNAL_HOSTS` 与技能 DLP 名单；`SSRFSecurityError` 在 HTTP、隐身、浏览器三层都向上抛，由 `FetchEngine._handle_fetch_error` 单点接住（写失败缓存、返回 None、不降级）；`StealthFetcher` 在起浏览器前与对落地 URL 各判一次；每一跳先清掉上一跳的 `Host`；URL 语法检查（scheme 白名单、parser-confusing 字符）抽到 `utils/url_syntax.py::parse_outbound_hostname`，本地与云托管两条路径共用；⑤ 删除无人调用的 `redirect_hop_guard` facade、route_interceptor、审计与配置，`_ARCH` 与 `BROWSER_SYSTEM.md` 同步；⑥ 恢复编排器传 `ContextType.AGENT`；`find_incomplete_tasks` 用 `datetime.fromisoformat(checkpoint["ts"]).timestamp()` 读检查点时间，同一函数里两次读取的 `messages` 合并为一次；为不超行数护栏把结果统计折叠成 `failed_threads` 计数，`isinstance(result, BaseException)` 同时接住 `gather` 返回的取消异常，`orchestrator.py` 由 509 行降到 505 行，基线同步收紧；该文件原有的 4 条 mypy 错误（两处 `BaseCheckpointSaver` 缺类型参数、`RunnableConfig` 实参类型、`browser` 元数据类型）一并清零；`browser_fetcher.py` 顺手删掉一条 mypy 报告为多余的 `type: ignore` |
| **反复次数** | 第 1 次发现；对应 topic_03 #151 ⑤⑥ 的后续（⑤ 在 006 落地时只把标志传到了过滤器，没有验证重定向链在浏览器里是否真被看见） |
| **踩坑** | ① 只看浏览器侧结果区分不了「被拦」与「没发出」，注入路由在驱动里跟随的各跳也不经过任何过滤器，只有服务端按 `(方法, 路径)` 的计数看得见，所以断言都落在服务端收到几次；② 整套集成第一遍跑出 13 例红：它们直接 `page.goto`，绕过会话守卫，不会登记「显式导航」，被收窄后的上下文过滤器拦下，属于夹具缺口而非产品回归（`grep '\.goto('` 在源码里只剩 `about:blank` 与守卫内部，生产导航都经 `Navigator.goto`），夹具改为按 `goto_with_ssrf_guard` 的做法登记授权；③ 浏览器层的授权不能挂在池化上下文上：CRAWL 上下文比一次抓取活得久，上一次抓取的授权会留给下一次，所以 `BrowserFetcher` 每次抓取新建授权集；④ 评估过但不做：服务端 Fetch-Metadata 规则、OpenClaw 默认拒绝配置、只校验首跳 `Location`（首跳之后的链仍由驱动或浏览器自行跟随，等于没验）；⑤ 残余边界（有意保留）：Chromium 在加载后判定之前，会对未授权的内部地址发出一次盲 GET（探针里环回服务仍收到 1 次）。patchright 不路由文档重定向，浏览器内无法在发出之前拦下；只有出站网络层（出口代理或防火墙，即 #151 ⑥ 的方向）能做；该请求是不带自定义头的 GET，响应内容读不到；⑥ 另两条残余边界（审查时用真实 Chromium 与 `FetchTargetGuard` 实测，改动前后都存在，不是回归，已写进 `BROWSER_SYSTEM.md` 与 `domain_filter/_ARCH.md`，未修）：a) 域名黑名单与白名单只作用于被路由的请求，不作用于文档重定向的后续各跳：环回服务用 `127.0.0.1` 与 `localhost` 两个主机名，黑名单写 `localhost`、白名单只写 `127.0.0.1`，入口页 302 到 `localhost`，改动前页面停在入口 URL 却装着被拦主机的内容，改动后页面落到被拦主机，两种情况下被拦主机的服务端都收到了请求；b) 本地模式只按字面主机分类、不做 DNS（有意，兼容代理与 fake-IP 解析），字面形式 `127.0.0.1`、`::1`、`::ffff:127.0.0.1`、`0.0.0.0`、`LOCALHOST`、`localhost.`、IMDS 的 v4 与 v6 地址、`metadata.google.internal` 全部被拦，但解析到环回地址的公网域名（`127.0.0.1.nip.io`、`localtest.me`）放行；⑦ 整套集成里 `test_browser_launch_ownership_stamp` 在前两次整套运行中失败（找不到浏览器子进程），单独运行、在改动前的源码副本上同序跑前 53 例、以及最后一次整套运行都通过，未查明根因，按机器负载下的时序问题处理；3 例访问 `https://example.com` 的活网用例在某一次整套运行里超时，单独重跑全过；`test_interactor_performance` 的 1 ms 阈值用例在某次单元套件里测得 1.0178 ms，单独重跑 3 次全过；⑧ 我自己写的 `ContextType` 回归用例同样用了替身池与替身 `recover_session`，没有任何一条测试把真实检查点喂进恢复链路，`ts` 缺陷因此漏过了我的验证；事后用真实链路探测（真实 `InMemorySaver` + `IncrementalSessionCheckpointer` + `ThreadStore` + 真实 `GlobalBrowserPool` + `https://example.com`）才发现，修复后 `recover_all` 返回 success 1 / total 1（首次尝试因目标站 15 s 无应答重试了一次，耗时受网络影响，不作性能结论，该探测依赖外网，不进 CI）；⑨ 同一探测顺带看到 `recover_one` 构造 `BrowserSession` 时没有转发 `allow_private_networks`，恢复到环回 / 内网 URL 会被云托管策略拦下，属失败关闭、不是安全问题，也不在本批范围，未改 |
| **回归** | 真实 Chromium（macOS）集成：`tests/toolkits/browser/test_document_redirect_integration.py` 11 例（在改动前的注入路由上 8 例红、3 例对照绿）· `test_local_mode_navigation_policy_integration.py` 10 例 · `test_private_network_policy_integration.py` 5 例 · `tests/toolkits/web_fetch/test_fetch_ssrf_terminal.py::TestStealthTier` 4 例；单元：`test_inject_route.py` 21、`test_navigation_ssrf_guard.py` 15、`test_navigation_ssrf_guard_teardown.py` 3、`test_navigation_ssrf_guard_policy.py` 15、`test_target_guard.py` 50、`test_fetch_ssrf_terminal.py` 14、`tests/core/security/test_redirect_hop_evaluator.py` 43（替换已删除的 `tests/unit/test_redirect_hop_guard_suite.py`）、`tests/utils/test_url_syntax.py` 13、`checkpoint/test_orchestrator.py` 新增 2、`checkpoint/test_orchestrator_real_checkpoint.py` 1（真实检查点写入器到 `RecoveryContext`，在 `ts` 改回 `/ 1000` 的 `/tmp` 副本上该例与 `test_e2e_recovery.py` 的 2 例共 3 例红，`test_e2e_recovery.py` 的 `ts` 夹具改为 ISO 字符串）。变异验证（在 `/tmp` 的源码副本上，未动仓库）：HTTP 层吞掉被拒跳转 7 例失败；旧式数字 IPv4 不规范化 10 例；引擎把 SSRF 异常当意外错误 6 例；隐身层不判落地 URL 2 例；本地策略跳过技能 DLP 名单 1 例；请求源不授权 11 例；浏览器层不把策略拦截转成 `SSRFSecurityError` 1 例；浏览器层改用上下文级授权 1 例；本地策略去掉元数据名单 2 例（IP 形式的元数据地址仍被私网段拦下，是两层防线）；`Host` 头不清除 1 例；注入路由改回改动前版本 8 例。全量：`tests/toolkits/web_fetch`、`tests/core/security` 与 url 相关单元 1743 例通过；`tests/toolkits/browser` 单元 3128 例通过、1 例跳过、1 例为上述 1 ms 阈值用例（单独重跑通过）；真实 Chromium 集成（`tests/toolkits/browser` 加 `TestStealthTier`）241 例，最后一次整套 238 例通过，另 3 例为活网超时（单独重跑通过）；`ruff check`、`ruff format --check`、行数护栏与 `_ARCH` 清单对本批文件均 OK。度量（`/tmp` 脚本，同一台负载很高的开发机，3 跳重定向 × 15 次）：服务端请求数改动前后都是 60（每次 4 个），页面最终 URL 由停在 `/h3` 变为 `/final`，非 HTML 文档请求数 2 次降为 1 次；延迟中位数两轮互相冲突（改动前 58.5 与 103.7 ms，改动后 49.4 与 143.9 ms），不据此宣称更快或更慢。端到端探针（不进 CI，`httpbin.org` 跳到环回服务）见症状 ① |
| **代码位置** | `toolkits/browser/enhancers/inject_route.py::_inject_handler`（`:83-97`，`route.fetch(max_redirects=0)` 在 `:89`）· `toolkits/browser/navigation/ssrf_guard.py::goto_with_ssrf_guard`（`:126`）· `toolkits/browser/utils/private_origins.py::private_origin_grants`（`:30`）· `core/security/redirect_hop_guard/{origin_grants,hop_evaluator}.py` · `toolkits/browser/domain_filter/http_filter.py:111,126` · `toolkits/web_fetch/fetchers/target_guard.py::FetchTargetGuard`（`:59`）· `fetchers/http_fetcher.py:244-260`、`stealth_fetcher.py:58-86`、`browser_fetcher.py:138-140` · `engine/cache_mixin.py:101` · `utils/url_syntax.py` · `toolkits/browser/checkpoint/orchestrator.py:202,450-455` |

### BUG-HARNESS-2026-10-14-009 · 已创建的模型实例没有任何续期入口：订阅登录的短寿命访问令牌到期后，实例仍带旧密钥发请求；原生 xAI 端点的请求不带会话路由头

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-14（xAI SuperGrok 订阅登录加固：读 `async_mixin.py` 的请求路径与服务端令牌流时发现；没有真实 SuperGrok 账号，以读代码、单元测试与探针确认，授权流程与上游行为没有端到端验证） |
| **修复时间** | 2026-10-14 |
| **症状** | ① `ChatLiteLLM` 的异步生成与流式路径每次请求都取实例上的 api key，harness 没有任何续期入口；订阅登录的访问令牌是短寿命的，实例比令牌活得久时（长对话中途令牌到期、常驻的模型实例），之后的请求仍带着旧令牌，只能由提供商拒绝；② 原生 xAI 端点的请求不带会话路由头 `x-grok-conv-id`（OpenAI 的 `prompt_cache_key` 与 OpenCode 中继的 `x-opencode-session` 已有，xAI 没有），同一会话的多次请求不保证落到同一台缓存服务器 |
| **关联产品** | server `app/services/agent/provider_oauth_tokens.py::freshen_api_key`（`app/server/lifespan.py` 启动期经 `api.hooks.set_api_key_refresher` 登记）；产品台账 `BUG-AGENT-2026-10-14-008`。只有登记了 refresher 的宿主与原生 xAI 端点受影响，其他提供商与未登记的宿主行为不变；Local / 桌面 / 云托管相同 |
| **根因** | 实例级 api key 在构造后没有刷新通道，harness 与凭据层之间没有契约；路由键注入只覆盖 OpenAI 与 OpenCode 两类端点 |
| **修复** | ① `api_key_refresher.py`（新）：进程级登记一个 `ApiKeyRefresher`（当前密钥进，新密钥或 `None` 出），`renew_api_key` 供适配器询问；refresher 抛错只记 warning 并沿用当前密钥，不阻塞请求；登记表不含凭据策略、不导入宿主。② `async_mixin.py::_renew_api_key` 在非流式与流式两条异步路径上、每次请求取密钥快照之前调用；同步路径不续期。③ `api/hooks.py` 导出 `set_api_key_refresher`，宿主经公开门面登记（server 的深层导入棘轮只认已登记路径），`tests/api/test_integration_surface.py` 钉住 `__all__`。④ `session_affinity.py`（新，从 `model.py` 拆出端点识别与 `_inject_prompt_routing_key`）：原生 xAI 端点按端点主机匹配（`x.ai` 或 `*.x.ai`；未设 `api_base` 时按 `xai` 提供商或 `xai/` 前缀），把路由键作为 `x-grok-conv-id` 发出，调用方已设同名头时不覆盖。⑤ `payload_debug.py`（新，从 `async_mixin.py` 拆出失败载荷的配对日志）：`model.py` 与 `async_mixin.py` 回到行数上限内（基线 552→514、579→553） |
| **反复次数** | 第 1 次发现 |
| **踩坑** | ① server 对 harness 的深层导入会被 `test_server_harness_imports.py` 棘轮拦下，登记入口只能经 `api.hooks`；② xAI 端点必须按主机名匹配：子串匹配会误中 `notx.ai`、`x.ai.evil.example` 与路径段里的 `api.x.ai`，三者都写成了对照用例；③ 已知局限：`x-grok-conv-id` 只验证了注入条件，没有在真实接口上量化缓存命中的变化；refresher 登记是进程级单例，一个进程只能登记一个；同步路径不续期 |
| **回归** | `tests/toolkits/llms/adapters/test_api_key_refresher.py`（18 例：无登记不续期、续期被采用并在下一次请求以新密钥再问、`None` / 空串 / 同值保持原密钥、缺失的密钥不进 refresher、抛错保持原密钥并记日志且请求不失败、取消不被吞、登记 `None` 即移除、经公开门面登记读到同一份登记、只持有 `openai_api_key` 的实例同样续期、流式请求与流式 `_agenerate` 只问一次）· `test_prompt_routing_key.py`（33 例，含 `notx.ai`、`x.ai.evil.example`、路径段对照与调用方已设头不覆盖）· `tests/api/test_integration_surface.py`（8 例）· `test_chat_model_stream_edges.py`（20 例）。变异验证：路由头 3 个、续期登记 5 个，全部杀死。提交树在临时导出里运行：上述 4 个文件共 79 例通过，`tests/toolkits/llms` 加 `tests/api` 共 2630 例通过、2 例跳过；`ruff`、`mypy`（6 个源文件）通过；行数护栏与分形文档检查对本批文件无违规（其余失败项出在 `agent_runtime`、`summarize_processor`、`delegate_task_tool` 与 `memory` 等未触及的文件） |
| **代码位置** | `toolkits/llms/adapters/chat_model/api_key_refresher.py::set_api_key_refresher`（`:33`）、`renew_api_key`（`:39`）· `async_mixin.py::_renew_api_key`（`:93`，调用点 `:142`、`:335`）· `session_affinity.py::_inject_prompt_routing_key`（`:29`）、`_is_xai_native_endpoint`（`:72`）· `api/hooks.py::set_api_key_refresher`（导入 `:100`、`__all__` `:192`） |

### BUG-HARNESS-2026-10-14-008 · 隐私检测只认「连写」：带空格或连字符的银行卡号默认只告警、分组书写的手机号不被识别、多词自定义关键词被换行或不间断空格隔开就漏掉；带 +86 的手机号遮罩成 `861****8000`

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-14（终极叩问阶段，用真实代码对「人实际会怎么写」的输入逐条对照；每条都带对照组，先量改动前，再改，再量） |
| **修复时间** | 2026-10-14 |
| **症状** | ① 只打开隐私开关、其余用默认（`PrivacyPolicy` 默认 s2=警告、s3=遮罩，`privacy_settings.py:44-60`）时，Luhn 有效的 `4532 0151 1283 0366` / `4532-0151-1283-0366` 只被 `credit_card_visible`（S2）认出，动作是警告，完整卡号照常发给模型；连写的同一张卡是 S3，被遮成 `**** **** **** 0366`；② `138 0013 8000`、`138-0013-8000`（无国家码）手机号规则整条不命中（带 `+86` 时由国际号码规则兜住）；③ 自定义关键词 `Project Atlas` 里的空格只匹配一个空格字符：邮件或网页复制常见的换行、不间断空格、双空格、制表符隔开后不遮罩；④ 直接构造 `CustomRules(keywords=(" ",))` 的空白关键词会匹配文本里每一个空格（产品路径 `custom_rules()` 已剔除空白，只有直接构造能触发）；⑤ `_redact_china_phone` 对带 `+86` 的号码取前三位时取到国家码，结果 `861****8000` |
| **关联产品** | myrm-agent-harness `core/security/detection`（`pii_classifier`、`custom_rules`、`pseudonymizer`）与 `agent/security/detection/pii_redactor`；守卫中间件、记忆写入假名化、出站守卫与 `POST /config/privacy-preview` 共用这张表，Local / 桌面 / 云托管三种部署相同；没有改前端、提示词与 server 代码。影响面：隐私开关打开的用户；银行卡与手机号的真实书写占比没有线上数据，只有语料扫描（见回归） |
| **根因** | 内置检测表只写了「连续数字」一种形态，自定义关键词用 `regex.escape(keyword)` 字面匹配，用户键入的一个空格只能匹配一个空格字符；检测、遮罩、假名化三处共用同一张表，所以三处一起漏 |
| **修复** | `pii_classifier.py`：`_BANK_CARD_RE` 在连写之外接受「同一种分隔符（连字符或空格）连接的每组四位」，可带银联 19 位的末组一至三位，仍然经过原有 Luhn 校验（三处下游都只去掉连字符和空格再校验，所以分隔符只收这两种，不收不间断空格）；Luhn 无效的分组数字仍落在 `credit_card_visible`（S2）。`_CHINA_PHONE_RE` 在连写之外接受 3-4-4 分组（两处分隔符各为连字符或空格），写成共用前三位的一条正则 `1[3-9]\d(?:\d{8}|(?<![A-Za-z]1[3-9]\d)[- ]\d{4}[- ]\d{4})`，分组形态不能紧跟字母，避免把 UUID 尾段（`dd75f159-9266-4208`）当手机号；连写形态的行为不变。`custom_rules.py::_keyword_regex`：关键词按正则 `\s+` 切词（与匹配时认的空白同一定义）、词间用 `\s+` 连接，首尾词的边界规则不变，已去掉首尾空白的单词关键词其正则与改前相同（产品路径的 `custom_rules()` 本来就 strip；直接构造的关键词，首尾空白现在也被忽略）；空白关键词返回 `None`，`_raw_spans` 跳过（与 `_pattern_regex` 同形）。`pii_redactor.py::_redact_china_phone`：取号码末 11 位再遮罩，去掉不可达的回退分支。`pii_classifier.py` 414 → 418 行（含注释），其余文件行数无超限。评估过但不做（没有出现频率证据，或收益低于维护成本）：不间断空格作卡号分隔符（要同步改三处 Luhn 前处理）、Amex 4-6-5 分组、混用分隔符、身份证分组、全角数字、NFD 与零宽字符容错、关键词全角度大小写折叠、自定义模式长度上限 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | ① 第一版手机号分隔符可选、前一字符不限：全库扫描发现 UUID 片段 `dd75f159-9266-4208`、`d1879671-3694-49ad` 被当手机号（hex 数字段首尾恰好是十进制），改为两处分隔符必选并加「不跟在字母后」守卫，重扫误报 0；② 分隔符不一致或任意位数分组的卡号变体会把 `4444-555555555555` 这类数字吞进来，所以要求同一种分隔符、每组恰好四位；③ 我自己写的银联测试号 `6222021234567890018` 并不满足 Luhn（原测试注释同样写错），换成 `6222021234567890011`；④ 突变验证第一次全部「通过」：pytest 的 `pythonpath = ["src"]` 排在 `PYTHONPATH` 之前，被改动的副本根本没被导入，改用 `-o pythonpath=` 后重跑；⑤ 自查发现并已修：第一版按 `str.split()` 切关键词，Python 把 `\x1c`–`\x1f` 当空白而正则 `\s` 不当，含这类控制符的关键词会匹配不到自己，改为用同一个 `\s+` 切；手机号第一版写成两个分支的并列，每 2 万字符多约 0.4 ms，改成共用前三位后与改前一致，随机 40 万条串与 47,754 个文件（396 MB）的全库扫描上两种写法的匹配结果完全相同；⑥ 已知不覆盖与行为变化：不间断空格、混用分隔符、Amex 4-6-5 的卡号仍只是 S2 或不识别；工具结果与记忆写入里的测试卡号（`4111 1111 1111 1111` 这类）现在与连写形态一样被遮罩；已经含此类文本的进行中会话，下一轮的前缀会变一次，之后输出确定、不影响提示缓存命中 |
| **回归** | `tests/agent/security/test_pii_typed_in_groups.py`（新，分类 / 遮罩 / 假名化三层同验：分组卡号 4 种书写为 S3、遮罩成 `**** **** **** 0366`、假名化后按原样还原；Luhn 无效、不等长分组、混用分隔符、换行、双空格、UUID 等对照不升级；分组手机号 4 种书写为 S2、遮罩 `138****8000`、带 `+86` 的连写与分组同样；十位、多一位、前缀数字、换行、双空格、UUID 头尾对照不识别；遮罩后再遮罩不变）· `tests/core/security/detection/test_custom_rules.py::TestKeywordWhitespace`（空格 / 双空格 / 换行 / CRLF 加缩进 / 制表符 / 不间断空格 / 全角空格加大小写；`ProjectAtlas`、夹别的词、外侧边界、`pin` 与 `spinners`、`pass` 与 `password123`、含正则符号的关键词、空白关键词对照）· 另有三层消费者各一例（分类 / 遮罩 / 假名化：被换行隔开的 `Project\nAtlas` 命中，假名化后还原出原来的换行）与含 `\x1c` 的关键词匹配自己一例 · 两处原断言（`test_pii_classifier.py::test_credit_card_visible_format`、`test_pii_redactor.py::test_credit_card_visible_redacted`）原来用 Luhn 有效的分组卡号钉住「S2」，改用 Luhn 无效的 `4532-0151-1283-0367` 继续钉住 S2 回退。改动前红：28 例失败（未改源码）；突变验证 9 个（卡号回到连写 9 例失败、卡号混用分隔符 1、手机号回到连写 9、手机号分隔符含换行 1、去掉字母守卫 1、关键词回到字面 11、关键词改用 `str.split` 切 1、空白关键词不再跳过 1、遮罩不去 +86 2）全部被杀。全量：`tests/agent/security`、`tests/core/security`、`tests/agent/middlewares`、`tests/toolkits/memory` 8515 通过、7 跳过、9 例失败：7 例是 `test_leak_detector_json_keys.py::TestLinearTime` 的 1 秒墙钟断言（机器负载 35 到 88 时超时，该模块不导入本批任何文件），另两例 `test_approval_flow_coverage.py::TestAllowlistTTLCleanup::test_load_user_double_check_inside_lock` 与 `test_gather_per_stream_warning_codes.py::...test_graph_enrichment_error_records_failed_code` 单独运行全过，与本批无引用关系；含 `tests/architecture` 的整体运行 19 例失败，全部出在本批未触及的文件（行数护栏列的 `agent_runtime`、`batch_processor`、`memory` 等，分形文档头、manifest、工具注册、wheel 与 PyPI 校验）；`core/security/detection` 与 `agent/security/detection` 的清单检查均 OK；server 隐私相关 41 例通过（预览端点、设置 schema、lifespan、同步、converter 回退与深扫、安全策略扩展）；`ruff`、`mypy`（三个源文件）通过。语料扫描（本产品五仓、deer-flow、hermes-agent，47,844 个文件 / 396 MB，剔除我自己新增的测试与文档）：连写且 Luhn 有效的卡 15 处；分组形态新增 Luhn 有效 9 处，全部是公开测试卡 `4111 1111 1111 1111`，误报 0；手机号新增 6 处，全部是真实写法的测试号码（`+86 138 0000 1234`、`+86-155-4631-6576`、`+86 138 0013 8000`），UUID 误报修复后 0。性能（同进程交替对照、CPU 时间、9 轮：旧正则与旧关键词函数换入 vs 新代码，经过 `screen_user_input`，含 3 个自定义关键词、S2 假名化 + S3 遮罩，机器负载约 35）：33 字符 0.181 → 0.175 ms（−3.0%）、1833 字符 3.983 → 3.838 ms（−3.6%）、19033 字符 39.677 → 40.683 ms（+2.5%）取最小值，中位数 −3.9% / +0.3% / +0.0%，与测量噪声不可分，只能说「没有可测的变慢」；手机号正则单独在 1.9 万字符中文文本上：改前 0.657 ms，两分支并列写法 1.059 ms，共用前三位的写法 0.654 ms。端到端（真实代码，隐私默认值）：分组卡号预览 s3 / redact、手机号分组形态假名化为 `<PHONE_NUMBER_1>` 且回复里还原成用户键入的原样、`Project\nAtlas` 与 `Project\u00a0Atlas` 被遮罩 |
| **代码位置** | `core/security/detection/pii_classifier.py::_BANK_CARD_RE`（`:69`）、`_CHINA_PHONE_RE`（`:93`）· `core/security/detection/custom_rules.py::_keyword_regex`（`:150`）、`_raw_spans`（`:228`）· `agent/security/detection/pii_redactor.py::_redact_china_phone`（`:51`） |

### BUG-HARNESS-2026-10-14-007 · Wiki 反向链接卡片的上下文片段只认页面路径与别名：用文件名、标题、`canonical_id` 引用的页面没有片段，别名在 frontmatter 超过 2 KB 时同样失效

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-14（topic_02 #140 终审叩问时，用产品自己的命名规则与真实索引器做探针发现；先量改动前基线，再改，再量） |
| **修复时间** | 2026-10-14 |
| **症状** | ① 反向链接列表里（边已解析成功）的页面，只要用裸文件名 `[[five-layer]]`、`title`、`canonical_id` 引用目标页，卡片就没有 `context_snippet` / `line_number` / `heading`：解析器明确把这些写法列为合法（`core/link_resolver.py:213-222`），编译提示词也不限制模型用哪种写法（`core/config.py:107` 只要求用 `[[Wikilinks]]` 包起来）；② 别名写法也不可靠：旧实现只读目标页前 2048 个字符再解析 frontmatter，而 `parse_frontmatter` 需要闭合的 `---`，带 8 条 claims 的编译页面 frontmatter 约 3 KB，别名被读成空列表，别名写法同样没有片段（合成页面实测，解析器自己读到 `5la`、`five layers`）；③ 每条反向链接重复读一次目标页（最多 100 次），读与解析包在宽泛的 `except Exception: pass` 里，任何异常都静默变成「没有别名」；④ `_extract_mention_snippet` 没有生产调用方，只被一个测试使用 |
| **关联产品** | myrm-agent-harness `toolkits/wiki/retrieval`；server `app/api/wiki/router.py:1473` 的 `get_concept_links` 把结果交给前端 `WikiConceptLinksPanel`（卡片在没有片段时仍可点击进入来源页，缺的是片段、`§` 小节与 `L` 行号，且点击后不会定位到小节）。Local / 桌面 / 云托管三种部署相同。受影响的是「页面用非路径写法引用另一页」的库；这类写法在真实 LLM 输出中的占比没有测过（仓库里没有真实编译样本，调用真实模型要花用户的 token，也不能用生产数据） |
| **根因** | 片段有自己的一套「目标页写法」（页面键加 frontmatter 别名的正则，别名只读前 2 KB），与解析器认的写法（路径、标题、别名、`canonical_id`、裸文件名）是两个来源，边解析成功不代表片段能找到那条链接 |
| **修复** | `retrieval/graph_store.py`：新增 `_TargetSpellings`（每次查询构建一次、对每条反向链接复用）；`link_forms` 取 `page_link_forms(page_lookup_keys(…))`，与解析器同源，整页读取一次；每行的 `[[wikilink]]` 逐个用 `link_lookup_forms` 比对，命中即用该链接的位置做片段；markdown 链接与纯文本提及仍只认页面键与别名，裸文件名这类通用词只在写成链接时才算，不会把正文里碰巧出现的词当片段；删除宽泛 `except`（读取只防 `OSError`）、函数内延迟导入与无人使用的 `_extract_mention_snippet`；`graph_store.py` 370 → 389 行。评估过但不做（终审前后的结论）：① lint 与图谱对 markdown 页面链接统一口径：产品不生成 `[x](page.md)`（markdown 链接只用于图片与外部 URL：`pipeline/ingress/asset_store.py:220`、`video_segment_parser.py:210`、server `obsidian/adapter.py:136`、`source_sync/zotero.py:289`、`rss.py:73`，`core/refactor.py:307` 只改写已有链接），只剩手敲链接，而改动要碰核心解析器；② `broken_wikilink` 标签改名：歧义项的说明已写「Ambiguous wikilink [[X]] matches …」；③ 代码块里的 `[[x]]` 取错行：只影响在代码块里演示 wikilink 语法的页面；④ 写入时把上下文存进 `wiki_edges`（gbrain 的做法）：需要改表结构与迁移，收益相同 |
| **反复次数** | 第 1 次发现（同属 topic_02 #140，BUG-HARNESS-2026-10-14-005 之后） |
| **踩坑** | ① 第一版方案（拆新模块、用解析器重写片段、保持偏移的代码屏蔽）是过度设计，终审后整体砍掉，换成与解析器同源的写法集合；② 上一轮我说「卡片点不开」不准确：`WikiConceptLinksPanel.tsx:157-159` 的点击照常进入来源页，缺的只是片段与小节定位；③ 第一版里循环变量与海象运算符都叫 `match`，mypy 报类型冲突，改名后消失；④ 已知边角：同一来源页既有歧义的 `[[Overview]]`（解析器不建边）、又有指向目标的真链接时，片段可能取到前者那一行，卡片仍列正确的来源页，影响只在片段那一行；⑤ 性能数字来自合成库，没有用真实 vault 复测 |
| **回归** | `tests/toolkits/wiki/test_concept_links.py::test_backlink_context_for_every_spelling_the_resolver_accepts`（6 种写法：路径、大小写加片段加标签、文件名、别名〔frontmatter 超过 2 KB〕、标题、`canonical_id`；每条断言片段原文、行号、小节，来源页里另有一个无关链接作干扰）· `::test_generic_file_name_counts_only_when_written_as_a_link`（正文里的普通词不当片段）；既有 4 例按新签名更新并通过。负向对照（同进程把匹配换成只用旧正则）：2 例新测试都失败。实测（合成库，100 条反向链接，三种写法各约 1/3，目标页 frontmatter 约 3 KB，CPU 时间 7 次取中位数）：改动前路径写法 34/34 有片段、文件名写法 0/33、别名写法 0/33；改动后 34/34、33/33、33/33；CPU 中位数 27.7 ms（24.5–30.5）→ 28.6 ms（24.9–32.2），区间重叠，无可测量变化。`tests/toolkits/wiki` 全量 860 例通过；`ruff`、`mypy`（`graph_store.py`）、`_ARCH` 清单（`retrieval` OK）、行数门禁（本批文件无违规，其余失败项出在 `token_economics`、`stream_executor`、`classifier` 等未触及的文件） |
| **代码位置** | `toolkits/wiki/retrieval/graph_store.py`：`_TargetSpellings`（`:78`）、`_first_mention`（`:112`）、`_target_spellings`（`:303`）、`_extract_mention_record`（`:318`）、`get_concept_links`（`:343`）；生产调用点 server `app/api/wiki/router.py:1479` → `WikiIndexer.get_concept_links`（`retrieval/indexer.py:195`）→ `WikiGraphStore.get_concept_links` |

### BUG-HARNESS-2026-10-14-006 · 本地模式开了「允许访问内网」后，只要再配一个域名名单、或用带资源拦截的浏览器池，环回与内网地址仍被拦：标志只传给了导航守卫，没传到上下文的请求过滤器

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-14（复核 topic_04 #2 之后，追查 `tests/toolkits/browser` 里长期红着的 10 例真实 Chromium 集成测试时发现；每条都带对照组，并统计服务端实际收到的请求） |
| **修复时间** | 2026-10-14 |
| **症状** | ① 本地模式的 `BrowserSession(allow_private_networks=True)` 只把标志交给了 `Navigator`（直接 `page.goto`），而 context 级请求过滤器里「私网地址 / 云元数据逐跳校验」由 `install_http_filter(allow_private_networks=…)` 控制，`install_domain_filter` 与 `ContextFactory` 都没有把标志传下去，该参数恒为默认值 `False`。只要上下文装了过滤器（配了域名名单，或池配置带资源拦截，如默认的 `BrowserPoolConfig()`），本地访问就被它重新拦下：真实 Chromium 导航到环回服务得到 `net::ERR_ABORTED`，服务端一个请求也没收到；② 白名单里明确写了 `127.0.0.1` 的会话也进不去，与 `test_domain_allowlist_integration.py` 文件头声明的契约（放行路径靠环回服务 + `allow_private_networks=True`）矛盾；③ 10 例集成测试长期红色（`test_web_vitals_integration` 2、`test_domain_allowlist_integration` 4、`test_session_persistence_integration` 4）；另有两处测试夹具（`loopback_servers_reachable`、e2e 里的过滤器包装）用猴子补丁替换了过滤器安装函数，把这个缺陷遮住了，依赖它们的测试因此一直是绿的 |
| **关联产品** | myrm-agent-harness `toolkits/browser`（`session`、`pool`、`domain_filter`）；server 本地模式在 `app/ai_agents/general_agent/tool_setup.py:885` 构造 `BrowserSession(allow_private_networks=is_local_mode(), domain_allowlist=…, domain_blocklist=…)`，黑名单来自用户在设置页「安全策略」里的配置；本地池用 `BrowserPoolConfig.minimal()`（`app/config/browser.py:109`，无资源拦截），没有名单时 `install_domain_filter` 直接返回、不装过滤器。受影响面：本地 / 桌面模式下配置了 URL 黑名单或域名白名单的用户，打开 localhost 开发服务与局域网设备会失败；未配名单的本地模式、云托管（标志为 `False`，本就应当拦）不受影响。真实 Patchright Chromium（macOS）实测，Linux / Windows / Camoufox 未实测 |
| **根因** | `allow_private_networks` 是会话级策略，只在构造 `Navigator` 时传入；context 创建期的策略通道是 `context_kwargs` 里的特殊键（`domain_allowlist` / `domain_blocklist` / `resource_block`），标志从未加入；`install_domain_filter` 没有对应形参，`install_http_filter` 的同名形参于是无人传入、等同死参数 |
| **修复** | `BrowserSession` 把标志与两份名单一并写入 `context_kwargs`（仅在为真时写入）；`ContextFactory.create_context` 读取它并在唯一一次 `install_domain_filter` 调用里转发（原先「有名单」与「只有资源拦截」两条分支各有一个以 `object` 为参数类型、带 `type: ignore` 的包装方法，合并为一次调用并删除两个包装，参数改用真实类型）；特殊键集中为 `_POLICY_KWARGS`，不再传给 `Browser.new_context`；`install_domain_filter(allow_private_networks=…)` 转给 `install_http_filter`。只跳过「私网 / 元数据逐跳校验」，名单、广告、资源类型规则照常生效；标志为 `False`（云托管）时行为不变。`browser_session.py` 的行数护栏是 688 行等于基线上限，新增的键与原来两个 `if` 合并为一次字典过滤抵销，仍是 688 行。测试侧删除 `session/conftest.py` 的 `loopback_servers_reachable` 与 e2e 的过滤器包装；`test_stall_resilience_integration.py` 的 guarded 档（云托管形态，标志为 `False`，环回服务本应被拦）改用 `BrowserPoolConfig.minimal()`（无上下文过滤器）并只替换守卫的预检函数，local 档走默认池与真实标志 |
| **反复次数** | 第 1 次发现；对应 topic_03 #151 ⑤「`allow_private_networks` 贯通 context 级过滤器」 |
| **踩坑** | ① 会话层的「标志已传」是错觉：`Navigator` 用了标志、`navigate` 也返回了结果，过滤器在另一层又拦一次，单看会话层测试发现不了；红测必须走真实 Chromium 并统计服务端收到的请求数，才能区分「被拦」与「页面为空」；② 夹具替换安装函数是反向的 Goodhart：它让依赖它的测试变绿，却让没用它的 10 例一直红着，没有人把两件事连起来；删掉夹具后 guarded 档要自己说明为何需要放行；③ 新增的局部变量 `policy` 与同一构造函数后面的 `policy = DialogPolicy(…)` 同名，mypy 在 275 / 278 / 279 行新增 3 条类型错误，改名 `policy_kwargs` 后消失；④ 评估过但不做：云元数据地板——标志为真时仍对 `169.254.169.254` 等 `_CLOUD_METADATA_HOSTS`（`core/security/redirect_hop_guard/hop_evaluator.py:30,143`）保持拦截。结论不做：浏览器导航只能发 GET，读不出需要自定义请求头 / PUT 的 IMDSv2、GCP、Azure 元数据；受支持的云托管形态本来就传 `False`；剩余暴露面只有「自托管 WebUI 远程部署、云主机仍开着 IMDSv1、再叠加提示注入」这一条链，价值约 3 / 10。**【2026-10-14 更正，见 BUG-HARNESS-2026-10-14-010】本项结论已被推翻**：同日稍后实测，公网跳转器可把云托管会话带到环回页并读出内容，本地模式的无检查路径同样可被跳转利用；现在本地模式仍对 `_CLOUD_METADATA_HOSTS` 永远拦截，并把私网放行收窄为「会话显式导航到的源」 |
| **回归** | `tests/toolkits/browser/test_private_network_policy_integration.py`（真实 Chromium，5 例，每例统计服务端收到的请求：带名单 / 默认资源拦截的会话可达环回；名单里写了环回仍被拦；无标志的 context 与无标志的整条会话路径（云托管默认，导航守卫加上下文过滤器）对照仍被拦）· `test_domain_allowlist_context_kwargs.py::test_context_kwargs_forwards_private_network_policy`（参数化真 / 假，仅资源拦截的 context 也转发，且标志不进 `Browser.new_context`）· 原先红着的 10 例转绿。变异验证（在 `/tmp` 的源码副本上，未动仓库）：会话不写入标志，2 例失败；标志不从 Playwright 参数里剔除，5 例失败；工厂不转发，5 例失败；`install_domain_filter` 不转发，3 例失败；转发恒为真，仅无标志对照 1 例失败；仅有资源拦截的 context 跳过过滤器，仅 2 例单元失败（集成测试在没有过滤器时本就可达，抓不到）。全量：`tests/toolkits/browser` + e2e 真实 Chromium 集成 220 例全过（改动前同一批有这 10 例失败）；`tests/toolkits/browser`、`test_browser_security`、`test_redirect_hop_guard_suite`、`tests/toolkits/web_fetch` 单元 3711 例通过、1 例跳过；`ruff`、行数护栏（浏览器文件无违规）、`_ARCH` 清单与分形文档检查对 `toolkits/browser` 均 OK；其余护栏失败项（`memory`、`token_economics` 等）出在本批未触及的文件 |
| **代码位置** | `toolkits/browser/session/browser_session.py:212-218` · `pool/context_factory.py::create_context`（`:163`、`:210-223`）与 `_POLICY_KWARGS`（`:49`）· `domain_filter/__init__.py::install_domain_filter`（`:305`、`:345-352`）· `domain_filter/http_filter.py:96`（形参） |

### BUG-HARNESS-2026-10-14-005 · Wiki 链接语义的口径分裂：代码块里的 `[[ -f x ]]` 成图谱边、改名漏改解析器认的写法、同名页面出现或消失后边不收敛、best-first 展开被枢纽页吃光预算；另有链接扫描随页面大小平方增长、不可解码的页面让删除半途失败

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-14（对 topic_02 #140 链接语义做真实场景与竞品复核时，用真实索引器与真实发布路径逐条复现；每条都带对照组） |
| **修复时间** | 2026-10-14 |
| **症状** | ① best-first 展开的 `best_first_max_expansions` 既限制入队的邻居数、又在用完后停止出队：枢纽页（出边很多）或指向不存在页面的边先用掉预算，队列里其余种子与邻居被整体丢弃；② 链接的语法在边提取、lint、重命名、反向链接发现、画布里各用各的正则，围栏代码块里的 `[[ -f x ]]` 与行内代码里的 `[[x]]` 成为图谱边，lint 把 `#锚点`、`mailto:`、`file.md#片段` 报成断链；③ 重命名自己判断链接是否指向被改名页面（按文件名主干与路径比较），与解析器的判断不一致：页面没有标题与别名时，口语写法（`[[Borrow Checker]]` 指向 `borrow-checker.md`）、净化路径、`wiki/` / `concepts/` 前缀、`./` / `../` 相对写法在解析器里都指向被改名页面，改名对这些写法的处理与解析器不同（逐写法对照 9 例不一致）；④ `upsert` 自己已经提取边，每个发布入口（发布、修复发布状态、过期降级、向量重建、移动重建）在 `upsert` 之后又用同一内容各调一次边提取；⑤ 同名页面（两个目录的 `overview`，或共用同一别名的两页）出现或消失后，已存的边不收敛：删掉其中一页后，原本因歧义保留原文的边仍停在原文，不会解析到留下的那一页；先解析到页面 A 的边在同名页面 B 出现后仍指向 A，而 lint 已按歧义判为断链；lint 对「同名多页」与「根本没有这页」给出同一句「Broken wikilink」；⑥ 采集 `source_systems` 时用裸 `except Exception` 吞掉所有异常，frontmatter 的 YAML 解析失败也不留日志；⑦ 删除页面时重读指向它的页面，其中一页不是合法 UTF-8 会让 `UnicodeDecodeError` 越过 `delete`（索引行已删，向量清理被跳过）；⑧ 长行上没有闭合的 `[[` 或 `[x](` 让链接扫描随页面大小平方增长（合成页面 16k 个 `[x](`，64 KB，2.2 s；16k 个 `[[` 超过 6 s，同一行为在改动前的各处提取正则里同样存在） |
| **关联产品** | myrm-agent-harness `toolkits/wiki`；server `app/api/wiki/router.py` 的图谱、反向链接、移动概念（`refactor_links`）与 lint / 健康报告。Local / 桌面 / 云托管三种部署都受影响 |
| **根因** | ① 预算被两个职责共用，出队循环以「已展开次数」作为退出条件；② 没有链接语法的单一来源，各处正则与代码屏蔽范围不同；③ 重命名自己判断「这个链接是否指向被改名页面」，与解析器是两套规则；④ 边提取在 `upsert` 内与各调用方各有一份，同一次写入提取两遍；⑤ 已存的边只保存解析结果，不保存链接文字，页面集合变化后只有链接所在页面自己的文字能判断它现在指向谁；解析器与 lint 对「歧义」「不存在」不加区分；⑥ 本意是「frontmatter 解析失败就当没有」；⑦ 重读页面只防了 `OSError`；⑧ 链接模式的部分不限长度，每个开头都向后扫到行尾（markdown 链接标签不限行，扫到页尾） |
| **修复** | ① `retrieval/best_first.py`：预算只限制邻居入队，队列照常出队直到结果满；② 新增 `core/link_extraction.py`：围栏与行内代码先屏蔽再读链接，外部链接、同页锚点、非页面目标不算页面引用，边提取、lint、重命名、反向链接发现、画布共用；③ `core/refactor.py`：重命名恰好改写解析器会指向该页面的链接（任意写法），裸文件名链接只在改名后不与同目录页面冲突、或文件名全局唯一时改写，文件夹移动按路径段匹配前缀并保留链接其余写法；④ 边提取只在 `upsert` 内执行，发布、修复发布状态、过期降级、向量重建、移动重建里的重复调用删除；⑤ `WikiLinkResolver.ambiguous_pages` 给出歧义目标命中的页面，`PageChange` 增加 `colliding`（路径 / 标题 / 别名 / `canonical_id` 相同的页面）与 `namesakes`（只有文件名相同的页面）；删除页面时，指向它的页面（仍有同名页面在场时）按各自的文字重新读取并重新解析，未解析的原文边按页面名重新解析；新页面与路径 / 标题 / 别名 / `canonical_id` 相同的页面共存时，指向那些页面的页面重新读取；lint 仍用 `broken_wikilink` 类型，说明改为「Ambiguous wikilink [[X]] matches a, b …」（最多列 5 个）；⑥ 改为只捕获 `yaml.YAMLError` 并记一条警告；⑦ 顺带删除 `RefactorReport` 上无人使用的 int / bool / str / eq 兼容方法与无引用的 `_inject_alias_to_moved_file` 别名；⑧ `retrieval/fts_search.py` 484 行拆出 `fts_write.py`（写侧），两个文件 297 / 245 行；⑨ `_read_page` 同时防 `UnicodeDecodeError`，不可读页面保留既有的边并记警告；⑩ 链接模式每部分限长 1024 字符，16k 个 `[x](` 0.07 s、16k 个 `[[` 0.48 s |
| **反复次数** | 第 3 次（同属 topic_02 #140，补齐 BUG-HARNESS-2026-10-13-005 / 006 留下的口径缺口：-006 踩坑 ③「后来出现同名页面时已解析的边不重算」与 ⑤「重命名不改写净化写法」在此处理） |
| **踩坑** | ① 围栏识别要同时满足：开栏符独占一行、信息串里不能含反引号、关栏符不短于开栏符、未闭合的围栏延伸到页尾；第一版漏掉行中的 ```，并把信息串含反引号的行当成围栏开头，均已有回归；② 浏览同名页面的重读不能裁剪成「只看不同目录」：根页面、标题、别名相同的页面会让同目录的链接也变歧义（解析顺序里「标题 / 别名」先于「同目录文件名」），所以只对「仅文件名相同」的页面在新建时放弃重读；③ 新建时对仅文件名相同的同名页面重读，会让每建一个 `overview` 重读此前所有 `overview` 的链接页，页数随同名页数线性增长：合成 40 个目录（每目录 1 个 `overview`、6 个同目录页、6 个其它目录页）CPU 中位数约 2.0 s → 2.9 s（+46%），这一部分已放弃，这类边在链接所在页面下一次被写入时修正，lint 已如实报歧义；删除同名页面时只重读指向该页面的页面，保留；④ 重启后重建索引时，每个页面都像「新页面」：同名检查只在名字相对已读盘的结果有变化、或该页触发了第一次读盘时进行，所以整批重建至多让一个页面做检查；⑤ 性能数字全部来自合成库，没有用真实 vault 复测；⑥ 批处理脚本启动的后台测试会随外壳结束被杀，需用 `nohup` 脱离；⑦ 症状 ⑦ 与 ⑧ 是收尾复查时才发现的：前者靠构造非 UTF-8 的链接页复现，后者靠按页面大小翻倍的耗时曲线看出（2k / 4k / 8k / 16k 个开头，耗时约按 4 倍递增）；⑧ 的行为在改动前源码的正则里同样存在，不是本批引入；⑨ 方法移到新模块后，`test_wpg_invariant.py` 里对 `linter.publish_concept_article` 的打桩不再拦住发现路径，打桩目标要跟着调用方所在的模块走（改为 `backlink_discovery.publish_concept_article`；自动修复路径仍在 `linter.py`，那一处打桩不变） |
| **回归** | `tests/toolkits/wiki/test_best_first.py`（新增 3 例：枢纽页不吃掉其他种子、缺失邻居不消耗预算、预算限制入队邻居）· `test_link_extraction.py`（新文件：代码屏蔽、围栏边界、目标解析）· `test_link_rename_parity.py`（新文件：重命名与解析器逐写法对照，9 个用例在旧实现上失败）· `test_link_edges.py`（代码与非页面目标不成边、每个写入口恰好提取一次〔参数化 5 个入口〕、`source_systems` 成边、frontmatter 不可读时跳过并记日志）· `test_link_edge_convergence.py`（新文件 7 例：仅文件名相同的页面出现时不重读、删除后重读、共享别名出现与消失、删除无同名页不重读、重启后重建至多对一个页面重读、不可解码页面保留既有的边；其中 2 例在关掉重读后失败，1 例在无条件重读下失败，不可解码页面一例在修复前抛 `UnicodeDecodeError`）· `test_link_extraction.py`（增加限长与线性扫描 3 例）· `test_link_resolver.py`（新增 `ambiguous_pages`、`colliding` / `namesakes`、`forget_page` 返回值）· `test_structural_lint.py`（歧义说明、超过 5 个页面的计数）· `test_refactor.py`（`RefactorReport` 改为普通数据类后的断言）。实测（合成库，CPU 时间，旧新交替）：发布路径 300 页，边提取收回 `upsert` 后为链接工作前基线的 1.22× → 0.88×；本次变更发布 150 页（库内已有 150 页）6 轮中位数 0.628 s → 0.643 s（约 +2%，在噪声内）；上述同名页面合成库放弃新建重读后，3 轮旧 1.79 / 1.66 / 1.80 s、新 1.64 / 2.10 / 1.79 s，在噪声内。`tests/toolkits/wiki` 全量 858 例：除真实 LLM 的 `test_sidecar_integration::test_sidecar_build_index_query_pipeline` 外全部通过，该例随 LLM 输出波动（本批代码上全量运行 2 次失败 1 次通过；改动前的源码上单独运行 6 次失败 4 次；sidecar 检索代码本批未触及）；`tests/architecture` 行数门禁里 `maintenance/linter.py` 因本批 +2 行一度越过基线（516 > 514），先收回到 507，再把 LLM 反向链接发现（`_discover_connections`）原样移到 `maintenance/backlink_discovery.py`（`BacklinkDiscoveryMixin`），`linter.py` 降到 426 行并删掉基线条目，其余失败项（cron、memory、llms 等）出在本批未触及的文件；分形文档、`_ARCH` 清单、`md_ref` 三个检查脚本对 wiki 各目录均为 OK |
| **代码位置** | `toolkits/wiki/core/{link_extraction,link_resolver,refactor}.py` · `maintenance/{linter,backlink_discovery}.py` · `retrieval/{best_first,edge_links,indexer,fts_search,fts_write}.py` · `diagnostics/structural_lint.py` · `pipeline/publication/{publish,path_change,stale_guard}.py` · `retrieval/reindex_vectors.py` |

### BUG-HARNESS-2026-10-14-004 · 自定义隐私模式里的 Unicode 属性类静默失效、超大或嵌套过深的模式让每一轮对话报错、回溯爆炸的模式让整个进程停摆：用户写下的模式并不都真的在保护

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-14（复核「自定义隐私规则是否真的被遮罩」时，用同一批模式分别过标准库 `re` 与 `regex` 逐条对照；每条都带对照组） |
| **修复时间** | 2026-10-14 |
| **症状** | ① 用户从 AI 助手那里抄来的 `\p{Han}{2,4}科技` 这类 Unicode 属性类模式，在 `re` 下编译失败，按「无效模式从不命中」处理，该规则静默不生效，设置页却把它当作已保存的有效规则；② `a{99999999999}`（`OverflowError`）与上千层嵌套括号（`RecursionError`）不是 `re.error`，没有被捕获，异常经 `guard_outbound_messages` 一路冒到 LLM 调用，只要这条模式留在设置里，之后每一轮对话都失败；浏览器侧的 `new RegExp` 校验接受前者；③ `(a\|aa)+$` 一类回溯爆炸的模式在 `re` 下持有解释器锁：实测另一线程被停住 1.09 秒（n=23）、39.9 秒（n=28），此时同进程所有会话的请求都在等 |
| **关联产品** | myrm-agent-harness `core/security/detection/custom_rules.py`（分类器、脱敏器、假名化器共用的自定义词与模式匹配）、`agent/middlewares/security/privacy_preview.py`；server `POST /config/privacy-preview` 与前端「安全与隐私」设置页的试一试。Local / 桌面 / 云托管三种部署都受影响；macOS、Python 3.13、`regex` 2026.9.29 实测 |
| **根因** | ① 模式引擎是标准库 `re`，语法比用户可能带来的少，而「编译失败就当没写」没有任何出口把这件事告诉用户；② `_pattern_regex` 只捕获 `re.error`，而引擎还会抛 `OverflowError`、`RecursionError`；③ `re` 没有匹配超时，且匹配期间不释放 GIL |
| **修复** | 引擎换成 `regex`（`tiktoken` 已把它带进依赖，现显式声明；语法是 `re` 的超集）；`_pattern_regex` 捕获 `regex.error` / `OverflowError` / `RecursionError`，并在编译前估算计数重复额外展开的原子数、超过 `_MAX_REPEAT_ATOMS` 的按无效处理（踩坑 ⑤）；每个模式扫一段文本的时间上限 `_PATTERN_TIMEOUT_SECONDS`（1 秒，合法模式扫 5 MB 文本约 0.15 秒），超时按整段文本命中处理（`CustomSpan.timed_out`，不受已有标记豁免，同级其余规则不再扫描），宁可多遮不漏；新增 `ineffective_patterns`，`PrivacyPreview.ineffective_patterns` 在任意文本（含空文本）下列出编译失败的模式，供设置页如实告知 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | ① 超时测试不能在旧引擎上跑红：`(a\|aa)+$` 在 `re` 下是几十秒的死循环，红测只跑了不会卡住的用例；② `regex` 匹配 `str` 时释放 GIL（实测超时预算 0.5 秒内另一线程最长停顿 6.3 ms），所以换引擎本身就消除了整进程停摆，超时预算只限制工作线程与一个 CPU 核被占用的时间；预算只计引擎自身的时间，调用方迭代匹配结果的时间不计，要按引擎时间选；③ 引擎对照以 `re` 为基准做了差分：既有 336 例与新增 12 条标准语法对照用例结果完全一致；另把 harness 全部模块在导入时编译的 2371 条模式（含各种标志位）逐条过两个引擎，在 28 段文本（源码片段与 PII 样本）上编译结果与命中区间全部一致；④ `regex` 在稠密命中的 1 MB 文本上并不更快：`[\w.+-]+@acme\.com` 这类以长字符类开头的模式慢约 3 倍，其余形状持平或更快（见回归栏数据）；⑤ `regex` 编译时把计数重复逐份展开，`re` 只存计数：`a{10000000}` 实测占 2.7 GB、1.8 s（`re` 0.1 ms），嵌套时相乘（`(?:a{1000}){1000}` 约 300 MB），`{n,}` 与 `{n,m}` 的下限同样展开、`{1,1000}` 不展开；9 位以内的计数不抛 `OverflowError`，所以一条 11 个字符的模式就能让进程被系统杀掉，超时预算管不到编译。编译前的 `_repeat_atoms` 按「至少展开几份」估算计数重复比模式本身多出的原子数，超过 `_MAX_REPEAT_ATOMS`（10000）按无效模式处理，模式本身再长也不受限（5000 个词的 `a|b|…` 照常可用）：9 条炸弹模式 0.08 ms 全部拒绝、进程峰值内存不变（31 MB）；估算只会偏高：对 29964 条随机嵌套模式（分组、断言、原子组、字符类）与 `re` 解析树对照，低估 0 条，最多高估约 12 倍（分组头计入）；harness 自己的 2371 条模式没有一条被拒，最大估算 4096；估算本身对 24 万字符的模式约 1 ms |
| **回归** | `tests/core/security/detection/test_custom_rules.py`（`TestPatternEngine`：Unicode 属性类、命名分组、标准语法差分、极端模式不崩；`TestPatternTimeout`：整段命中、豁免标记、规则短路；`TestPatternSize`：7 种展开过大的模式被拒且不构建、含 5000 词交替式在内的 13 种真实模式保留）· `tests/agent/middlewares/test_security_privacy_preview.py`（`TestIneffectivePatterns` 含过大模式、`TestPatternThatCannotFinish`）· 实测对比（同一份含五个词和三个模式的混合文本，7 次取中位数）：20 KB 3.25 → 4.83 ms，200 KB 36.7 → 48.2 ms，1 MB 157 → 239 ms，命中的区间数完全一致 |
| **代码位置** | `core/security/detection/custom_rules.py::_pattern_regex` / `_repeat_atoms` / `_raw_spans` / `_live_spans` / `ineffective_patterns` · `agent/middlewares/security/privacy_preview.py::preview_privacy_policy` |

### BUG-HARNESS-2026-10-14-003 · 浏览器会话关闭拆掉共享上下文里别的对话的标签页、崩溃标签页被反复使用、切换标签后后台页继续写网络日志、主动关闭的浏览器被当成崩溃、默认引擎的控制台日志永远为空却不说明：生命周期与观测路径上五处各自独立的缺口

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-14（复核 topic_04 #2 Stop 边界之外的生命周期与观测路径时，用真实 Chromium 逐条复现；每条都带对照组） |
| **修复时间** | 2026-10-14 |
| **症状** | ① 自定义智能体的多个对话共用一个上下文（`agent_<id>`）；其中一个对话的会话因空闲回收、删除对话或引擎切换而 `close()` / `restart()` 时，会强行清空该上下文的在用页面集合并销毁上下文，另一个对话仍开着的标签页与登录 Cookie 一并消失；`restart()` 还会丢掉上下文键，之后的取页落到默认上下文，不同智能体的页面混在一起；② 渲染进程崩溃的页面 `is_closed()` 仍是 `False`，每次工具调用都在它上面失败，`snapshot` 甚至从缓存返回「无 DOM 变化」，像页面活着一样；③ `page.off` 在公开的 Page 上不存在（只有 `remove_listener`），摘除监听的调用抛 `AttributeError` 被吞掉，切换或关闭标签后，不再是活动标签的页面仍继续写网络日志；④ 池或会话自己关闭托管浏览器（空闲回收、关停、引擎重启）会触发 `disconnected`，与真实崩溃同路径，被记成 WARNING「Browser crashed」，并向没人读取的全局熔断域记失败；⑤ 默认 Chromium 引擎（patchright 保持 `Console.enable` 关闭以隐身）的页面不会向会话上报控制台事件，`console_log` 恒返回「No console messages captured.」，模型会据此断定页面没有报错 |
| **关联产品** | myrm-agent-harness `toolkits/browser`（`pool`、`session`、`tools`）；server 经 `tool_setup.py:839-844` 让自定义智能体的对话共用 `agent_<id>` 上下文，`execution_cache` 的空闲回收 / 删除对话调用 `BrowserSession.close()`。Local / 桌面 / 云托管三种部署都受影响；真实 Patchright Chromium（macOS）实测，Linux / Windows / Camoufox 未实测 |
| **根因** | ① `close()` 与 `restart()` 为了绕过 `destroy_context` 的「仍有在用页面」断言，直接清空 `PagePool._busy` 并手改全局计数、再强删跟踪表，默认这个上下文只属于自己；`restart()` 先把 `_context_key` 置空再 `close()`，之后没有恢复；② 池只在崩溃事件里归还许可，没有对外说明「这个持有中的页面已崩溃」，工具调用入口也没有检查；③ 接口名用错：公开 `Page` 只有 `on` / `remove_listener`；测试替身恰好有 `off`，把错误遮住了；④ `disconnected` 处理器只看 `is_managed`，不区分是谁关的；⑤ `get_console_log` 不区分引擎，把「没有事件来源」当成「没有消息」 |
| **修复** | ① `destroy_context(key, only_if_idle=True)`：仍有页面在用时保留上下文并返回 `False`；`close()` 改用它，删除强制清空与强删；`restart()` 经 `close()` 关闭并恢复上下文键；② `CrashWatchdog.is_page_crashed` 对在用页面保留崩溃标记，`BrowserSession.active_tab_crashed()` 暴露给边界，`cancel_boundary` 在每次工具调用前遇崩溃先 `recover_active_tab()`；③ 摘除监听改用 `remove_listener`（网络与控制台日志共 5 处），替身删去 `off`，其余用 `Mock(spec=Page)`；④ `BrowserInstance.expected_close`：池关闭托管浏览器、`restart()` 清理空浏览器前先置位，`disconnected` 处理器按 `is_managed and not expected_close` 分类，预期断开记 INFO；崩溃与浏览器断开不再向熔断器记失败（熔断器只由导航结果驱动，原来的全局崩溃域没有任何读取方）；⑤ 默认引擎返回 `CONSOLE_CAPTURE_UNAVAILABLE`，说明控制台不可捕获、不能当作无报错并指向 `network_log` / `evaluate`；Camoufox 照常返回捕获内容；工具 schema 与描述不变，不影响提示缓存。附带：`BrowserSessionNetworkMixin` 补上 `SessionHost` 基类（消掉该文件 11 处 mypy 错误）；例行事件（标签页创建/关闭、池关停统计、域名过滤器安装）由 WARNING 降为 INFO |
| **反复次数** | 第 1 次发现；与 2026-10-14-001 / 002 同属 topic_04 #2 的资源与会话守恒复核 |
| **踩坑** | ① 单元测试里替身遮住了 `page.off` 的错误，必须用真实 Chromium 或 `Mock(spec=Page)` 才暴露；② 崩溃判定对照组不能 `await cdp.send("Browser.crash")`：浏览器当场死亡，命令永远没有应答，要放进任务里，等断开处理器跑完后取消该任务；③ patchright 的 Console API 被设计性关闭，页面 `console.error` 已被独立的 CDP `Runtime` 监听收到，`ConsoleLogger` 仍为 0 条，所以用对照组证明是驱动不上报而不是测试写错；④ 评估过但不做的方案：为默认引擎开启 `Console.enable`（patchright 为隐身而关闭它，开启会抵消反检测设计，见 `BROWSER_SYSTEM.md` 反检测表）、给 `browser_manage` 的工具描述追加说明（改工具 schema，破坏提示缓存）、已知未修的既有竞态（`restart()` 清理空浏览器与另一会话正在 `acquire_page` 的交错；`destroy_context` 与进行中的 `acquire_page` 的时间窗）、导航 mixin 的 `or CHROMIUM_PATCHRIGHT` 引擎判断不看池默认引擎 |
| **回归** | `tests/toolkits/browser/session/test_shared_context_close.py`（真实 Chromium，5 例，含独占上下文对照）· `session/test_crashed_tab_recovery_integration.py`（3 例，含健康标签不被替换对照）· `session/test_network_log_tab_switch.py`（2 例，含活动标签自身请求对照）· `pool/test_expected_close_accounting.py`（4 例，`Browser.crash` 真实崩溃对照）· `session/test_console_capture_integration.py`（CDP 对照：页面已打日志而会话收到 0 条）· `session/test_console_log_availability.py`（6 例，按引擎）· `session/test_tab_recovery.py`、`tools/test_cancel_boundary.py`、`session/test_network_logger.py`、`session/test_console_logger.py`、`test_crash_watchdog.py` 同步。变异验证：还原强制清空，3 例失败；去掉入口崩溃检查，2 例集成与 1 例单元失败；还原 `.off`，4 例单元失败；去掉 `expected_close`，3 例失败；去掉「不可用」分支，5 例失败 |
| **代码位置** | `toolkits/browser/pool/browser_pool.py::destroy_context`（`:354`）· `session/browser_session_lifecycle_mixin.py::close/restart`（`:229` 调用，`:98` 置位）· `pool/crash_watchdog.py::is_page_crashed`（`:112`）/ `_handle_browser_disconnected`（`:83`）· `session/browser_session_tab_mixin.py::active_tab_crashed`（`:129`）· `tools/cancel_boundary.py`（`:64` 调用）· `session/network_logger.py` / `console_logger.py`（`remove_listener`）· `pool/browser_launcher.py::BrowserInstance.expected_close`（`:208`）· `session/browser_session_network_mixin.py::get_console_log`（`:41`） |

### BUG-HARNESS-2026-10-14-002 · 浏览器页面崩溃事件为没人持有的页面归还并发许可：空闲页崩溃让并发上限永久抬高，调用方已释放的页面崩溃则重复归还

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-14（复核 topic_04 #2 的取页许可守恒时，用真实 Chromium 触发 `chrome://crash` 逐条复现） |
| **修复时间** | 2026-10-14 |
| **症状** | ① 池里空闲的页面崩溃（例如一个标签关闭后留在池里复用，之后渲染进程被系统回收）：崩溃处理器照样归还一个并发许可，而这个许可没有人持有；全局信号量是进程级单例、从不对账，每发生一次，并发上限就永久多放一个槽位，同时留下一个再也不会被清掉的页面标记。真实 Chromium（macOS）实测，上限 3 时空闲页崩溃 3 次后许可数涨到 4 / 5 / 6；② 调用方已 `release_page` 之后才到达的崩溃事件会把同一个许可再归还一次（单元测试：10 变 11）。并发上限被逐步抬高，`minimal` / `standard` 档按页面数设的资源保护被削弱 |
| **关联产品** | myrm-agent-harness `toolkits/browser/pool`（`browser_pool.py::acquire_page` 在每次取页时给页面挂崩溃处理器，`session` 的标签页与 `web_fetch` 的浏览器抓取都经此取页）。Local / 桌面 / 云托管三种部署都受影响；真实 Patchright Chromium（macOS）实测，Linux / Windows / Camoufox 未实测 |
| **根因** | `CrashWatchdog._handle_page_crashed` 只检查浏览器是否已断开、该页是否已处理过，随后无条件归还一个许可并减负载；它默认崩溃的页面一定被调用方持有。但崩溃监听在页面整个生命周期内都有效，而许可只在页面被取出到被释放之间有人持有 |
| **修复** | `_handle_page_crashed` 加一个前提：页面属于该浏览器某个 `PagePool` 的在用集合（`_busy`）才归还许可并记标记，否则直接忽略；在用集合在取出时加入、`release` 时移出，与「许可由谁持有」同源，不引入新的状态。同一浏览器的空闲页崩溃后，下一次取页由 `PagePool.acquire` 既有的探活跳过已崩溃页面，无需额外处理 |
| **反复次数** | 第 1 次发现；与 2026-10-14-001 同属取页许可守恒，本次补齐崩溃路径 |
| **踩坑** | ① 单元测试里用页面替身无法复现标记残留（替身被其他引用持有，`id()` 不复用），必须用真实 Chromium 才看得到上限被抬高；② 崩溃只能用 `page.goto("chrome://crash")` 在真实浏览器里确定性触发，事件要等到后台任务完成后再断言；③ 评估过但不做的方案：改成按页记录持有关系的账本（改动面大，而在用集合已经是同一事实）、崩溃监听只挂一次（每次复用多挂一个监听，实测 2 → 6 个，开销可忽略）、`release_page` 重复调用的保护（生产调用方没有重复释放）、崩溃与取页交错的时间窗（微秒级，未复现，唯一后果是该浏览器一次空闲回收被跳过） |
| **回归** | `tests/toolkits/browser/test_crash_watchdog.py`（新增 2 例：空闲页崩溃被忽略且信号量、负载、标记不变；释放后到达的崩溃事件不重复归还）· `tests/toolkits/browser/pool/test_page_crash_accounting.py`（真实 Chromium，2 例：空闲页连续崩溃两次，许可数保持上限，新页面可正常使用；在用页面崩溃只归还一次，其后属主释放不重复归还）。变异验证（去掉前提，在仓库外副本上）：单元 2 例、真实 Chromium 1 例失败；在用页面崩溃那例旧代码也通过，作为保持行为的钉子 |
| **代码位置** | `toolkits/browser/pool/crash_watchdog.py::_handle_page_crashed`（前提在 `:139`） · `pool/browser_pool.py::acquire_page`（`:342` 每次取页注册崩溃处理器） · `pool/page_pool.py::PagePool`（`_busy`） |

### BUG-HARNESS-2026-10-14-001 · 浏览器取页被取消即永久丢一个并发槽位、非 Stop 的取消不自愈卡死页面、自愈后的空白页被当成「成功的空结果」：取页路径没有取消安全，边界只认取消令牌

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-13（复核 topic_04 #2 已落地的 Stop 边界时，用真实 Chromium 与真实 Agent 链路逐条复现） |
| **修复时间** | 2026-10-14 |
| **症状** | ① 浏览器冷启动期间点 Stop：`acquire_page` 在取页途中被取消，已取得的全局并发许可不归还；全局池是进程级单例、许可数从不对账，每漏一个就永久少一个槽位。实测并行取页 10 个并全部取消，漏 10 个，恰为 `minimal` 档的 10 个许可；许可耗尽后 `session.new_tab()` 无限等待（无内部超时）。另有两个窗口漏真实页面而不是许可：重置空闲页期间被取消、已取出页面后等池锁期间被取消，页面留在 `PagePool` 的在用集合里却没被计数，之后 `destroy_context` 因「仍有在用页面」拒绝执行；② 执行器自己的工具超时（`asyncio.timeout`）、IM 通道卡死任务看门狗（令牌与任务同时取消）、关停会在不翻转令牌的情况下取消工具，边界只处理 Stop，卡死页面（渲染进程死循环，CPU 100%）留在会话里，下一次运行立刻在同一个页面上再卡一次；③ 恢复后的标签页是空白页，`snapshot` / `inspect` 对它返回空文档这种看似成功的结果，模型不知道页面被重置过，已落地的 Stop 路径同样如此 |
| **关联产品** | myrm-agent-harness `toolkits/browser`（`pool` 的两个取页调用方：`session/tab_controller.py:131` 与 `toolkits/web_fetch/fetchers/browser_fetcher.py:107`，后者经 `engine/base.py` 的 `asyncio.gather` 批量并发取页；`tools` 的取消边界）；server 经 `tool_setup.py` 装配同一组工具。Local / 桌面 / 云托管三种部署都受影响；真实 Patchright Chromium（macOS）实测，Linux / Windows / Camoufox 未实测 |
| **根因** | ① `GlobalBrowserPool.acquire_page` 先裸 `await semaphore.acquire()`，之后跨越内存检查、浏览器启动、上下文创建、`PagePool.acquire`（含最长 5 s 的重置与探活）、池锁等多个挂起点，只有 `except Exception` 归还许可，`CancelledError` 是 `BaseException`，直接穿过；`PagePool.acquire` 在持锁状态下 `pop` 出空闲页后再 `await _revive`，被取消时该页既不在空闲列表也没人关闭；② `cancel_boundary` 只捕获令牌触发的 `OperationCancelledError`，普通 `CancelledError` 不经过自愈；③ `recover_active_tab` 返回新标签 id 后没有任何通道告诉模型，只有 `navigate` 自己的错误文案带了说明 |
| **修复** | ① 新增 `pool/page_acquisition.py::PageAcquisition`：`acquire_page` 在其内取许可，`hold` 记录已取出的页面，页面被计入「在用」后 `commit`；取页途中被取消或失败，则把页面还给 `PagePool` 并归还许可，崩溃处理器已为该页归还许可（`_crash_handled_pages`）时不重复归还；`PagePool.acquire` 的重置被取消时有界关闭已取出的页面；`browser_pool.py` 净减 2 行（763 → 761，行数基线同步下调）；② 边界对 `CancelledError` 先 `recover_active_tab()` 再继续抛出（自愈内部 `asyncio.timeout` 的预算耗尽转成 `TimeoutError` 被其自身捕获，不会吞掉取消）；③ `recover_active_tab` 记下一条一次性提示（`take_tab_reset_notice`，取出即清除），`navigate` 在自己的错误里说明后取走，其余由下一次工具的文本结果前置带出一次，一次成功的 `navigate` 让提示作废。同批删除 `session` 两个 mixin 里永远为真的 `hasattr(self, "_ensure_not_user_takeover")` 守卫（两处，页面 mixin 的三处因其不继承宿主契约而保留），并消掉 `browser_pool.py` 三条既有 mypy 错误 |
| **反复次数** | 第 1 次发现；与 2026-10-13-002 同一问题域（浏览器工具不响应取消），本次补齐取页路径与非 Stop 取消 |
| **踩坑** | ① 只给许可加 `except BaseException` 是错的：真实页面也会在两个窗口里泄漏，必须按阶段回滚（许可、已取出的页面、已计数）；「取页创建调用本身被取消」没有句柄可回收，属有界残留，页面留在上下文里直到上下文销毁，已写入文档；② 竞态窗口不能靠随机延迟复现：用只对指定任务生效的闸门锁（进入 `async with` 时挂起）与按需挂起的 `check_memory` / `create_context` / `_reset_page` 在每个挂起点确定性取消；③ 自愈放在取消处理里（二次取消落在自愈过程中仍照常传播）已用单元与真实链路测试覆盖；④ 并行两个工具同时被取消只会换一个新标签（`_tab_recovery_lock` 串行，后到者发现已是健康页面），已有测试断言；⑤ 恢复后的空白页让「读类工具返回空文档」成为静默的成功，没有提示就无法让模型知道要重新导航；⑥ conftest 以源码文本检测 `.acquire_page(` 并要求真实浏览器标记，使用替身浏览器的测试经辅助函数取页，未规避其初衷 |
| **回归** | `tests/toolkits/browser/pool/test_page_acquisition.py`（8 例：提交后不回滚、失败与取消各阶段归还、等许可期间取消不多还、崩溃处理器已还不重复、池无法收回仍还许可、二次取消仍还许可）· `tests/toolkits/browser/pool/test_acquire_page_cancel.py`（7 例，真实 `GlobalBrowserPool`、替身浏览器：等许可、冷启动、重置空闲页、等池锁、取页后失败、崩溃页，均断言许可数 / 在用计数 / 负载 / 在用页面守恒）· `tests/toolkits/browser/tools/test_cancel_boundary.py`（新增 7 例：非 Stop 取消自愈、`asyncio.timeout`、二次取消、提示一次、结构化结果与取消结果不消耗提示）· `tests/toolkits/browser/session/test_tab_recovery.py`（新增 9 例：提示一次、无替换与替换失败不留提示、真实会话下 Stop 后下一结果带提示、无 Stop 超时自愈、自愈预算耗尽不吞取消、并行两工具只换一个标签、成功导航作废提示、失败导航保留提示）· `tests/agent/streaming/test_stop_during_browser_tool_e2e.py`（真实 Chromium + 脚本化模型 + 生产执行器，新增 3 例：冷启动 Stop 后许可守恒、执行器超时后标签被替换且重试带提示、看门狗令牌与任务同时取消）。变异验证：去掉 `PageAcquisition` 的回滚 11 例失败；去掉 `PagePool.acquire` 重置取消时的关页 1 例失败；去掉边界的取消自愈 7 例失败；去掉提示前缀 3 例失败（单元、真实会话、真实链路各一） |
| **代码位置** | `toolkits/browser/pool/page_acquisition.py::PageAcquisition` · `pool/browser_pool.py::acquire_page` · `pool/page_pool.py::PagePool.acquire` · `tools/cancel_boundary.py::_cancel_aware` · `session/browser_session_tab_mixin.py::recover_active_tab/take_tab_reset_notice` · `session/browser_session_navigation_mixin.py::navigate` |

### BUG-HARNESS-2026-10-13-006 · Wiki 只写文件名的链接在 lint、图谱、展开里连不上、重命名却会改写它：链接解析口径不一致，补齐前向引用扫全表拖慢发布，删除页面丢入边，向量命中按原名重复

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-13（对 BUG-HARNESS-2026-10-13-005 的终审复核） |
| **修复时间** | 2026-10-13 |
| **症状** | ① 只写文件名的链接（`[[Ownership]]` 指向 `knowledge/rust/ownership`）：lint 报断链、不成图谱边、检索展开走不到，而重命名（`core/refactor.py`）按文件名主干把它当作指向该页的链接改写，同一个链接改名认、lint 与图谱不认；② lint 与边解析在同一模块里是两条解析路径（`wikilink_target_exists` 与 `WikiLinkResolver`），口径只能靠人保持一致；③ 每次写页后补齐前向引用要扫全部未解析边：1500 页乱序发布，全表补齐的每页均值是键控补齐的 3.0–3.4 倍（见回归）；④ 删除一页会连带删掉指向它的入边，页面被恢复或重建后，别的页面对它的链接不再成边，直到那些页面被重写；⑤ 旧库向量里同一页以编译名与磁盘路径各存一点，混合检索把它们算成两个候选 |
| **关联产品** | myrm-agent-harness `toolkits/wiki`；server `app/api/wiki/router.py` 的 `/wiki/graph`、`/wiki/graph/insights`、`/wiki/concepts/{name}/links` 与 lint / 健康报告。Local / 桌面 / 云托管三种部署都受影响 |
| **根因** | ① 解析器只有三层（路径、净化后路径、唯一的标题/别名/`canonical_id`），没有文件名层；② lint 用的是另一组原语；③ `relink_dangling_edges` 对每次写页都取全部未解析边逐条解析，不看这一页能影响哪些边；④ `FtsSearchMixin.delete` 的 SQL 同时按 `source` 与 `target` 删边；⑤ `sync_filter_vec` 直接拿向量点上的 `concept_name` 折叠命中 |
| **修复** | ① `WikiLinkResolver` 增加文件名层：不含 `/` 的链接按文件名（小写与净化两种写法）匹配，同目录页面优先，其次全局唯一，否则不解析——与 `core/refactor.py` 改名时的判定一致；② lint 改用同一个解析器（`diagnostics/structural_lint.py`），保留联邦只读公共挂载的放行，删除 `build_wikilink_title_index` / `wikilink_target_exists` / `_unique_key_index`；③ 边表增加 `target_key` / `target_slug` 两列与索引（`store_edge` 写入），`note_page` 返回 `PageChange`（这一页的查找键 ∪ 文件名写法，以及解析器是否刚重新读盘），补齐只取写法相同的未解析边再由解析器逐条判定，重新读盘或没有变更信息时才做全量；④ `identity_migration.py` 改为按 `PRAGMA user_version` 逐步迁移，`INDEX_SCHEMA_VERSION = 2`：第 2 步为所有边行补写目标的两种写法、全量补齐一次、删去自环；⑤ `delete` 只删该页自己的出边，入边保留，页面不在时读作未解析，页面回来时自动接上；已核对消费方都容忍悬空目标（洞察 `graph_analysis.py`、图谱节点 `graph_store.py`、展开 `best_first.py`）；⑥ 混合检索在线程内先用页面键规范化向量命中再折叠；⑦ 页面自己的边与它解析出的前向引用在同一个事务里写入（`extract_and_upsert_edges` 少开一个连接、少一次提交）。未改提示词、工具 schema、server 路由与前端 |
| **反复次数** | 第 2 次（同属 topic_02 #140，补修首版的遗漏与性能退化） |
| **踩坑** | ① 解析器首次读盘会置位「刚重新读盘」，所以新建索引器写的第一个页面一定报全量补齐，测 `PageChange.forms` 要先消耗这个标志；② 改名对非同目录的文件名链接改写成 `[[a/moved]]` 而不是 `[[moved]]`，一致性测试断言的是「原写法消失」；③ 键控补齐是单调的：已解析的边不会因为后来出现同名页面而重新计算，所以 `c/src` 里的 `[[X]]` 先解析到唯一的 `a/X`，之后 `b/X` 出现，lint 会按歧义报断链而边仍指向 `a/X`（未处理）；④ 迁移第 2 步在首次打开旧库时对所有边行重算写法并全量补齐一次：17954 条边的合成库耗时 350 ms，迁移后边集合散列不变、两列无空值，更大的库与真实库没测；⑤ `core/refactor.py` 仍只按 `casefold` 比较文件名主干（`:188,192,240,335,339`），不改写净化写法（`[[PostgreSQL Auth]]` 对 `postgresql-auth`）的链接，解析器认而改名不改写，未改；⑥ `structure` 的别名缓存仍是后写覆盖，别名被移除时已解析的边不回退，均未改；⑦ 新建索引器的首次发布仍要先读盘，1500 页库 5 次中位数无补齐 115.4 ms、键控 115.7 ms（合并事务前测得），耗时主要是读盘，这一项没有改善；⑧ 键控补齐本身只占约 0.46 ms/页（cProfile，600 页，约 2% 的写页耗时），与「不补齐」基线的墙钟差距来自改写边带来的额外页写入与提交；合并事务后键控 / 不补齐为 1.53、1.56 倍，略高于计划里 1.5 倍的验收线，未达标，没有再压（不补齐基线不做任何前向引用，正是未解析边目标从 540 降到 0 的那部分工作）；⑨ 测量机器负载很高（load average 约 68），同一方式两次运行的均值相差可达 2 倍，所以只比较相邻交替运行的比值，单个绝对值不可用 |
| **回归** | `tests/toolkits/wiki/test_link_resolver.py`（52 例，新增文件名层规则表、与 `LinkRefactorEngine.refactor_links` 在 5 个场景下逐一对照、`scan_concept_pages`、查找写法）· `test_link_edges.py`（新文件 13 例：文件名链接成边、先写后建收敛、同目录优先与同名不解析、无关页面不重新解析、页面的边与前向引用同一事务、别名超过一次查询分块、键控结果与全量补齐无差别、删除保留入边并在页面回来后接上、删除只清自己的出边、旧边表补列与收敛、迁移不重复执行）· `test_structural_lint.py`（新增：文件名链接不断链、同名页在两个目录时的歧义、歧义别名与图谱同判、联邦公共页放行、联邦页自身的链接）· `test_indexer.py`（新增：另一写法下的向量命中只算一次，向量库为桩）· `tests/toolkits/wiki` 全量 787 例通过（真实 LLM 的 `test_sidecar_integration::test_sidecar_build_index_query_pipeline` 在一次高负载运行里失败，单独重跑通过），相关非 wiki 用例通过，server `tests/api/wiki` + `tests/services/wiki` + `tests/integration/wiki` 414 例通过（不含真实 LLM 文件与已隔离的 3 条无关失败）。删除探针（1500 页合成库）：删除一个有 8 条入边的页面后入边仍在，图谱节点与边、洞察都不出现该页，`get_concept_links` 的出链仍列出该页名，重新发布后 8 条入边接上；向量命中的页面键规范化每个命中 14–21 µs。变异验证：把键控改回全表扫描，「无关页面不重新解析」1 例失败；让文件名层不解析，26 例失败（解析器、改名对照、lint）；换回两连接写法，「同一事务」1 例失败。基准（合成库，1500 页乱序发布，每页 8 条页面链接〔路径、标题、别名各约三分之一〕加 4 条永不解析的实体链接，同一索引器，墙钟 mean ms/页；机器负载高且波动，只比较相邻交替运行）：全表 / 键控 46.0 / 14.9、40.3 / 12.0（3.1 倍、3.4 倍；两连接版本另测一组 36.7 / 12.3）；两连接 / 合并事务 38.1 / 27.2、20.4 / 17.9（合并后快 29%、12%）；键控（合并后）/ 不补齐 27.2 / 17.8、17.9 / 11.5（1.53 倍、1.56 倍）；两连接版本的键控 / 不补齐曾测得 1.05、1.58、1.78 倍；键控、全表、两连接的边集合散列一致（`a5705016fb92`，17954 条），不补齐基线多 9 条边（17963，前向引用未合并）。每个组合只有 1–2 次测量，未在真实 vault 上测 |
| **代码位置** | `toolkits/wiki/core/link_resolver.py` · `retrieval/{edge_links,identity_migration,indexer,fts_search}.py` · `diagnostics/structural_lint.py` |

### BUG-HARNESS-2026-10-13-005 · Wiki 索引里同一页面两行、链接按原文存而连不上页面、图洞察统计失真：编译名与磁盘路径是两套索引键，边目标没有解析，洞察与图谱口径不一致

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-13 |
| **修复时间** | 2026-10-13 |
| **症状** | ① 经 `publish_concept_article` 发布 `Knowledge/Rust/Ownership` 这类编译名后，`wiki_fts` 里同一页有两行（编译名一行；维护流程重建索引时再写一行磁盘路径 `knowledge/rust/ownership`），图谱视图出现重复节点（合成库：3 个页面 → 6 行、6 个节点）；② `[[别名]]`、标题写法的链接按原文存为边目标，连不上目标页，图谱与反向链接缺边；③ 图洞察：互相链接的三角形内聚度显示 2.0（200%）；`raw:` 临时条目被当作孤立页面；`system:` 伪目标计入度数；孤立页多时桥接页被挤出缺口列表；「主题簇（N）」的 N 包含单页；面板把簇命名为 `Cluster #id` 并显示内部 `w=` 数值 |
| **关联产品** | myrm-agent-harness `toolkits/wiki`；server `app/api/wiki/router.py` 的 `/wiki/graph`、`/wiki/graph/insights`、`/wiki/concepts/{name}/links`；前端资料库图谱页 `src/app/library/components/WikiGraphInsightsPanel.tsx`。Local / 桌面 / 云托管三种部署都受影响 |
| **根因** | 同一页面有两套索引键：编译流程把模型给的概念名传给 `publish_concept_article`（`pipeline/publication/publish.py`）作键，维护流程（lint、重建索引、向量重建）传磁盘相对路径；`FtsSearchMixin.upsert` 按精确名先删后插，两种写法各留一行。`extract_and_upsert_edges` 把原始链接文字存为边目标，与页面键不同。`compute_graph_insights` 用与图谱视图不同的节点与边集合，且内聚度分子按有向行数、分母按无向对数 |
| **修复** | ① 索引键以磁盘页面路径为准（`core/link_resolver.py::concept_index_key`；没有对应页面文件的名字保持原样），`upsert` 按页面键入库，`delete` 对给定写法与路径写法都清理；`retrieval/identity_migration.py` 用 `PRAGMA user_version` 一次性把旧库里以编译名入库的行并到页面键；② `core/link_resolver.py` 成为链接解析的来源（lint 起初引用其中的原语，后改为同一个解析器，见 BUG-HARNESS-2026-10-13-006），`retrieval/edge_links.py` 写边时解析目标（路径、净化后路径、唯一的标题/别名/`canonical_id`；歧义与未知保留原文），目标页出现或别名变化后补齐先写后建的前向引用（全表扫描的补齐实现，后改为按键查找，见 -006）；③ `retrieval/graph_tables.py` 让洞察与图谱共用同一套联邦节点/边查询，`graph_analysis.py` 重写统计（互相链接只算一条、内聚度不超过 1、`system:` 与未解析目标不计、孤立与桥接各自限额、成员按度数、簇至少两页）；④ 面板以度数最高的页面命名簇、去掉 `w=`、文案全部走 6 语言 locales。同批删除无调用方的 `get_incoming_edges`；⑤ 复审补强：解析器按页记录已对账的查找键（`WikiLinkResolver.note_page`），新建索引器首次写某页、或解析器重新读盘后的第一次写页，都会触发一次 `relink_dangling_edges`，所以每次调用新建索引器、或另一进程先写入目标页时，前向引用同样收敛；`concept_page_exists` 统一页面存在性判断，绝对路径、`..` 与文件系统拒绝的名字（单段超过 255 字节）都不是页面；⑥ 洞察的第二个消费者 lint 的知识缺口检查（`maintenance/gap_issues.py::knowledge_gap_issues`，由 `linter.py` 调用）只对本库存在的页面出报告，洞察也覆盖只读公共挂载，挂载里的页面用户改不了；⑦ 面板的缺口页名与图谱用同一显示名，刷新按钮补无障碍名称（6 语言 `library.graph.insights.refresh`） |
| **反复次数** | 第 1 次发现 |
| **踩坑** | ① 复现必须走真实 `publish_concept_article`（含发布门）：手写 `upsert` 会绕过发布门，容易得出「索引键是路径主干」这类错误结论；② 在索引层无条件净化所有名字会破坏不透明键（暂存草稿、测试用名），所以只在有对应页面文件时规范化，迁移沿用同一规则；③ 两条原有测试把非规范键写成了期望（`test_reindex_concepts_after_move_deduplication`、`test_reindex_after_move_syncs_modified_referrers`），已改为页面键；④ 向量库里以旧键为键的点不随迁移清理，页面被删除或向量重建前仍在，`_is_published` 对未知名字返回真，它们可能作为重复候选出现（-006 在混合检索读侧把向量命中规范化到页面键，不再重复；点本身仍留在向量库）；⑤ 别名索引仍有三份口径：`structure` 的别名缓存（后写覆盖）、`canonical_registry`（先写优先）、`link_resolver`（歧义即不解析），本次只统一了 lint 与边解析；⑥ 迁移与旧库行为只在合成库上验证，未检查任何真实 vault；⑦ 首版 `note_page` 用解析器自己的磁盘扫描判断「新页」，而扫描发生在写文件之后，新页已在表里，被判为未变化，前向引用不补齐（新建索引器发布目标页时稳定复现：边停在 `[('guide/start', 'Deep Dive')]`），复审时发现并修复；当时的性能对比因此没有执行补齐，「无退化」的结论无效，已按终版代码重测；⑧ `Path.is_file()` 对超过 255 字节的名字抛 `OSError`，`concepts_dir / '/abs/x'` 会得到 vault 外的绝对路径，复审时一并堵上；`get_concept_links` 对超长名字仍会在既有的 `structure.resolve_concept_file_path` 抛错（改动前即如此，未改）；⑨ 给 `linter.py` 加缺口过滤后文件达 531 行，超过行数门禁基线 528，改为把缺口转 lint 条目的逻辑抽到 `maintenance/gap_issues.py`（`linter.py` 降到 514 行，基线同步收紧），而不是放宽基线 |
| **回归** | `tests/toolkits/wiki/test_concept_identity.py`（12 例：编译名与路径名同一行、边解析、前向引用收敛〔同一索引器、新建索引器、另一写入者先写目标页〕、别名后加重连、自环、markdown 相对链接、按任一写法删除、`get_concept_links` 两种写法、超长名字保持原键、旧库迁移幂等）· `test_link_resolver.py`（-006 补充后 52 例）· `test_graph_analysis.py`（新增 7 例：内聚度、`raw:`/侧车、`system:`、联邦挂载、缺口限额、成员排序、单页非簇）· `test_linter_scan.py`（新增 1 例：只对本库页面出缺口条目）与 `test_linter.py` 的两条缺口用例改为先建页面 · 前端 `__tests__/WikiGraphInsightsPanel.test.tsx`（6 例，真实 en/zh 文案）。旧版洞察实现在同一合成数据上复现：内聚度 2.0、缺口节点含 `raw:notes/meeting`；性能（`publish_concept_article`，CPU 时间，合成库每页 5 条链接：3 条路径、1 条别名、1 条先于目标页的前向引用，旧新交替）：500 页 5 轮，同一索引器连续发布的中位数旧 5.61 ms/页、新 7.16 ms/页（+1.55 ms，约 +28%）；每次调用新建索引器的单次发布旧 8.74 ms、新 46.91 ms（含解析器首次读盘，+38 ms）；3000 页 2 轮：同一索引器旧 5.54/6.21、新 8.33/8.38 ms/页，新建索引器旧 19.56/18.92、新 243/234 ms（约 +75 ms/千页）。这是真实的开销增加，不是噪声；换来未解析的原文边目标从 540（500 页）与 3005（3000 页）降为 0。合成数据，未在真实 vault 上测；以上是全表补齐实现的数据，-006 改为按键查找后的数据见该条 |
| **代码位置** | `toolkits/wiki/core/link_resolver.py` · `retrieval/{edge_links,identity_migration,graph_tables,graph_analysis,graph_store,indexer,fts_search}.py` · `diagnostics/structural_lint.py` · `maintenance/{gap_issues,linter}.py` |

### BUG-HARNESS-2026-10-13-004 · 多 Key 轮转池丢掉全部工具：`KeyPoolLLM.bind_tools` 丢弃绑定结果，同一 provider 配置两个及以上 Key 时 Agent 变成无工具聊天

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-13 |
| **修复时间** | 2026-10-13 |
| **症状** | 某个 provider 配置 ≥2 个 API Key 时，服务端把多个 `ChatLiteLLM` 包进 `KeyPoolLLM`；Agent 循环对它调用 `bind_tools` 后，发往提供商的请求不带 `tools`，Agent 不再调用任何工具（搜索、读写文件等），表现为一个没有工具的聊天模型，且没有任何报错。单 Key 不受影响 |
| **关联产品** | myrm-agent-harness `toolkits/llms/core`；server 侧触发链：`app/services/agent/params/resolvers.py:100`（`len(all_keys) > 1` 才传 `api_keys`）→ `app/ai_agents/general_agent/llm_factory.py:69-70` → `LLMManager._get_pooled_llm`（`toolkits/llms/core/manager.py:168`）。Local / 桌面 / 云托管三种部署都受影响。深度研究编排器（`agent/deep_research/_orchestrator_phases.py:149`、`_orchestrator_plan_research.py:129`）调用的是同一个方法，但没有拿池化 LLM 实测 |
| **根因** | `ChatLiteLLM.bind_tools` 返回新的 `RunnableBinding`、不修改自身（`toolkits/llms/adapters/chat_model/model.py` 末行 `return self.bind(**bind_kwargs)`）；`KeyPoolLLM.bind_tools` 对每个实例调用后丢弃返回值再 `return self`，工具参数全部丢失。唯一相关的测试用 `MagicMock` 只断言「被调用且返回 self」，把缺陷固化成了预期；池化 e2e 只测轮转策略 |
| **修复** | `bind_tools` 取主实例的绑定结果，把它携带的调用参数（工具 schema、`tool_choice`、`parallel_tool_calls` 等）重新绑定在池上（`self.bind(**binding.kwargs)`），请求仍经 `_agenerate` / `_astream` 的轮转逻辑发出。同批清掉 `_pool: CredentialPool \| None` 引起的 12 条 mypy 错误：构造函数必然赋值，改为非空类型并删除不可达的 None 守卫 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | ① 单测对 `bind_tools` 用 mock，只验证「被调用」不验证「请求里有没有工具」；必须用真实 `ChatLiteLLM` 加记录请求的 `litellm.acompletion` 替身，经 `ainvoke` 与 `astream` 两条路径断言提供商收到的 `tools`；② 「直接委托主实例」看似能保住工具，却会丢掉 Key 轮转，回归测试必须同时断言工具与轮转；③ 经 `create_agent` 的端到端复现（单 Key 的请求带 `['probe']`，2 Key 池的请求为 `[]`）才是判定标准，类型签名与 mypy 都发现不了 |
| **回归** | `tests/toolkits/llms/core/test_key_pool_llm_bind_tools.py`（5 例：返回池上的绑定、与单 Key 请求一致 ×`ainvoke`/`astream`、限流轮转后重试仍带工具 ×两条路径）。变异验证：恢复原缺陷 5 例全部失败；改成「委托主实例」3 例失败（绑定类型与两个轮转用例） |
| **代码位置** | `toolkits/llms/core/key_pool_llm.py::KeyPoolLLM.bind_tools` |

### BUG-HARNESS-2026-10-13-003 · 技能用量账本的内存缓冲：进程提前退出丢最后一次使用、合并吸收的计数落不了盘，缓存条目还会用旧值覆盖他处刚写入的计数

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-13 |
| **修复时间** | 2026-10-13 |
| **症状** | ① 运行结束记下的使用先留在内存，等 60 秒批量落盘或会话结束才写盘；一次性 CLI 调用、崩溃或停止信号让进程紧接着退出时，最近一次运行的使用丢失，技能健康面板少计一次；② 技能合并或建立总括技能时，执行器对目标取 `get_stats()`（没有缓存条目时是不落盘的视图）、加上来源技能的计数再 `flush()`：新总括技能与上次落盘后没被运行碰过的技能，加法被丢弃，吸收方从零开始而来源技能已归档；③ 同一账本被另一个收集器实例改过后，本实例缓存条目仍是旧值，下一次变更把旧计数写回：改写前账本 `call_count == 3`，另一实例取消置顶后变回 0（复现脚本跑旧实现得到 0，新实现保持 3）。产品内只有 server 一个进程写账本，③ 在产品中未触发 |
| **关联产品** | myrm-agent-harness `backends/skills`；调用方 `agent/skill_agent`（运行起止）、`agent/skills/curator/consolidation`（合并与总括）与 server 的 Curator 接口。Local / 桌面 / 云托管三种部署都受影响（①②），③ 只在同一技能目录有多个写入方时出现 |
| **根因** | `SkillStatsCollector` 把每个碰过的技能缓存在 `_pending_updates`，只有 `flush()` 清缓存：使用与生命周期变更走缓存，`get_stats()` 对无缓存条目的技能返回不会保存的视图，修改返回对象既不落盘也不更新缓存，生命周期变更写盘后缓存条目留着不清。缓存没有收益：满 200 条历史的账本 18 320 字节，真实流程里每个运行每个技能本来就是一次读加一次原子写 |
| **修复** | 分三步：`56c9c05f7` 运行结束即落盘并删除间隔批量；`08347039c` 由收集器自己写继承与归档；`1df9a980e` 把收集器改为无状态写穿——每次变更读账本、修改、原子写回，`get_stats()` 永远读盘，删除 `_pending_updates` / `flush()` / `_ensure_loaded` 与记录器的 `_persist()`。对照实测（满账本，开发机负载均值约 75，交替各跑两轮）：一次运行的账本开销中位数新 1.8–4.7 ms、旧 2.4–5.2 ms，没有变快也没有变慢，修复不以性能为理由 |
| **反复次数** | 同一缓冲机制第 3 次出现：前两次各修一个症状，这次移除机制 |
| **踩坑** | ① 「首次观察创建账本」是遗忘策略的隐含依赖（`backends/skills/forgetting_strategy.py:245-249,272,365-369` 以 `created_at` 计宽限期与「从未使用」的年龄），把 `get_stats()` 改成纯读会让从未使用的技能永不过期，所以保留并用测试锁定；② 合并测试用 mock 收集器时看不到 ②，必须用真实收集器跑执行器；③ 读改写之间没有锁：同一账本同一时刻的两个写入方仍可丢一次更新，产品内靠「server 单事件循环、读与写之间无 await」保证 |
| **回归** | `tests/backends/skills/test_stats_collector.py::test_every_use_is_on_disk_when_record_use_returns` · `::test_a_stale_view_never_overwrites_changes_made_elsewhere` · `::test_get_stats_reads_changes_made_by_another_collector` · `::test_first_observation_creates_the_ledger_and_anchors_created_at` · `tests/agent/skills/curator/consolidation/test_consolidation_stats_persistence.py` · `tests/backends/skills/test_usage_recorder.py::test_run_end_persists_the_use_before_returning` |
| **代码位置** | `backends/skills/stats_collector.py::SkillStatsCollector` · `backends/skills/usage_recorder.py::commit_skill_run_usage` · `agent/skills/curator/consolidation/executor.py::_archive_sources/_inherit_stats` |

### BUG-HARNESS-2026-10-13-002 · 卡在驱动里的浏览器调用不响应 Stop：导航停滞后页面卡死、看门狗误杀存活浏览器、页面池发放已关闭或卡死的页面

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-13 |
| **修复时间** | 2026-10-13 |
| **症状** | ① 目标服务器不应答或只发响应头不发正文时，`browser_navigate_tool` 在超时后继续挂起（兜底的 `window.stop()`、SSRF 守卫路径的 `unroute`、CDP `detach` 都落在同一个卡死的页面连接上），用户点 Stop 无效：令牌只在图产出下一个分片时才被检查；② 卡死的页面被放回池后，下一次 `new_tab` 在池锁内阻塞 20 s 以上；③ 单页面配置下，一次慢导航期间看门狗的页面级探针超时，把存活的浏览器判为崩溃并驱逐；④ `PagePool.acquire` 可能发放已关闭的页面；超时且从未提交的导航静默返回上一页的内容，模型会以为导航成功 |
| **关联产品** | myrm-agent-harness `toolkits/browser`、`utils/runtime`；调用方 `myrm-agent-server` 的浏览器工具装配（`app/ai_agents/general_agent/tool_setup.py:903`）。Local / 桌面 / 云托管三种部署都受影响；真实 Patchright Chromium（macOS）实测，Linux / Windows / Camoufox 未实测 |
| **根因** | 浏览器工具从不观察请求的取消令牌；超时善后（`window.stop()`、`unroute`、`detach`、`close`）全部无界地等待一个已卡死的页面；看门狗用「池内页面能否执行脚本」代表「浏览器是否存活」；`acquire` 取出空闲页后不检查是否已关闭，`release` 会把已关闭页放回池 |
| **修复** | `run_until_cancelled`（`utils/runtime/cancellation.py`）让每个浏览器工具与令牌赛跑，Stop 后取消在途调用、恢复标签页、返回 `CANCELLED_RESULT`；超时导航先发 `Page.stopLoading` 再结算（已提交返回现有内容，未提交抛 `BrowserNavigationError`，无应答抛 `PageUnresponsiveError`）；`recover_active_tab` 持锁、幂等、有 10 s 预算地替换卡死标签；`unroute` 与页面关闭 2 s、CDP `detach` 1 s 上限（页面关闭与 `detach` 统一在 `page_health.py`）；`acquire` 跳过已关闭页并在重置后探活，`release` 丢弃已关闭页；看门狗先问浏览器级 `Browser.getVersion`，不应答才用页面做第二意见 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | ① 卡死页面上 `page.evaluate` / `unroute` / `close` 都不返回，而 `Page.stopLoading` 与浏览器级 `Browser.getVersion` 仍然应答，探活与善后要走后者；② patchright 的 `Browser.version` / `Browser.contexts` 是缓存属性、不发 CDP 请求，不能拿来探活；③ 只在工具外检查令牌无法释放已卡在驱动里的调用，必须在调用内部与令牌赛跑；④ 取消边界对象是 `StructuredTool.coroutine`：必须在 `with_dynamic_hints` 产生最终副本之后包装，否则副本里仍是旧协程；⑤ 回环地址的测试服务器会被默认的 HTTP 过滤器拦截，集成测试要同时放行过滤器与 SSRF 预检，否则「卡死」的现象来自拦截而不是服务器；⑥ 用固定定时器触发 Stop 的测试在高负载下会赶在工具启动之前取消（日志 `Cancelled during execution: nodes=0`），断言「工具真的在跑」才暴露出来，Stop 必须等测试服务器真正收到请求之后再发 |
| **回归** | `tests/toolkits/browser/session/test_stall_resilience_integration.py`（真实 Chromium，`local` / `guarded` 两条导航路径，含对照组）· `tests/agent/streaming/test_stop_during_browser_tool_e2e.py`（脚本化模型 + 生产 `StreamExecutor` + 生产工具拦截中间件）· `tests/toolkits/browser/tools/test_cancel_boundary.py` · `tests/utils/runtime/test_run_until_cancelled.py` · `tests/toolkits/browser/session/test_tab_recovery.py` · `tests/toolkits/browser/utils/test_page_health.py` · `tests/toolkits/browser/pool/test_page_pool_acquire.py` · `tests/toolkits/browser/pool/test_crash_watchdog_probe.py` |
| **代码位置** | `toolkits/browser/tools/cancel_boundary.py` · `utils/runtime/cancellation.py::run_until_cancelled` · `toolkits/browser/utils/page_health.py` · `toolkits/browser/navigation/__init__.py::_settle_timed_out_navigation` · `toolkits/browser/session/browser_session_tab_mixin.py::recover_active_tab` · `toolkits/browser/pool/page_pool.py` · `toolkits/browser/pool/crash_watchdog.py` |

### BUG-HARNESS-2026-10-13-001 · macOS 上 psutil 读取正被回收的进程时抛 `SystemError`：残留浏览器扫描被截断成部分结果，服务端启动恢复误报“未发现残留进程”，强制清理的复核直接抛异常

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-13 |
| **修复时间** | 2026-10-13 |
| **症状** | `find_orphan_automation_processes` 在遇到这类进程时中止遍历，只返回已扫到的部分并记一条 warning；结果为空时服务端启动恢复（`app/core/infra/health/browser.py`）报告 SUCCESS“No orphan processes found”。`cleanup_orphan_processes` 开头的复核（`leftovers_at_start`）与逐 pid 复核不在 try 内，异常直接抛给健康接口、修复动作和启动恢复。整表扫描 A/B（同一台 macOS 机器、同一脚本，各 n=1）：空闲时修复前 0/2000 次被截断；每秒约 1300 个短命进程的高频退出负载下，修复前 6/2000 次、修复后 0/2000 次被截断；对 530,237 次 `environ()` 读取（进程持续被杀被回收）出现 2 次 `SystemError`；只调用 `read_owner_state`、反复读取刚被杀死并回收的带戳进程，229,410 次调用有 12 次逃逸 |
| **关联产品** | myrm-agent-harness `toolkits/browser/doctor`、`toolkits/browser/process_owner`；服务端的启动恢复、健康接口与修复动作是其调用方。仅 macOS 实测，Linux/Windows 未实测 |
| **根因** | psutil 7.2.2（发现时 PyPI 最新版）在 macOS 读取正被回收的进程的 `environ()` / `cmdline()` 时抛 `SystemError`（“returned a result with an exception set”），它既不是 `psutil.Error` 也不是 `OSError`，穿过了 `except (psutil.Error, OSError)`；上游已在 master 修复（giampaolo/psutil#3024 跟踪，#2854 修复）但尚未发布 |
| **修复** | 三处捕获元组加入 `SystemError`：`read_owner_state` 的环境读取（读不到按 `UNKNOWN`，不会被当作残留）、`find_orphan_automation_processes` 扫描内层捕获（跳过该进程继续）、`_is_chromium_process` 对名称 / 可执行文件 / `argv[0]` 的逐项读取。方向始终是“无法确认就不动”，不会多杀 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | ① 捕获 `psutil.Error` / `OSError` 覆盖不了 C 扩展抛出的 `SystemError`，而且概率很低，普通单测与手动运行抓不到，要对“被杀并回收的进程”做紧循环压测才能复现；② 只用 mock 的回归测试容易空测：`test_unreadable_source_does_not_hide_the_others` 原先因 `name` 先命中而从未读到不可读的来源，是逐个去掉捕获的变异验证才发现的 |
| **回归** | `tests/toolkits/browser/test_process_owner.py`（环境读取抛 `SystemError` 得 `UNKNOWN`）、`tests/toolkits/browser/doctor/test_orphan_detection.py`（失败进程排在真实残留之前，扫描仍报出后者；名称与可执行文件不可读但 `argv[0]` 可读、以及三个来源全部不可读，各用 `AccessDenied` / `NoSuchProcess` / `SystemError` 三种异常）、`tests/toolkits/browser/doctor/test_orphan_cleanup.py`（身份读不到则不发信号并报 `not_an_orphan`）；回退验证：分别去掉三处捕获使 2 / 1 / 2 个用例失败；同一压测脚本修复前 229,410 次 12 次逃逸，修复后 200,808 次 0 次（各跑 1 次） |
| **代码位置** | `toolkits/browser/process_owner.py::read_owner_state` · `toolkits/browser/doctor/orphans.py`（`find_orphan_automation_processes`、`_is_chromium_process`） |

### BUG-HARNESS-2026-10-12-003 · `CodeExecutor` 的 shell 默认文件操作不是字节无损的：名字含单引号的文件读写失败或可注入命令，读取经 stdout 被脱敏/截断，大文件读写失败

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-12 |
| **修复时间** | 2026-10-12 |
| **症状** | 只实现 `execute` / `execute_bash` 的自定义执行器上：（1）`read_file("it's.txt")` 报 `unexpected EOF while looking for matching '`，文件名 `x'; touch PWNED; echo '` 会让读取执行 `touch PWNED`，`list_files(".", "*'; touch PWNED2; echo '")` 同样执行注入命令；（2）文件内容 `api_key=sk-…`、`password=…`、绝对路径经 `cat` 读回后被 `ExecutionResult` 脱敏成占位符，读改写会把占位符写回磁盘；（3）超过 200K 字符的文本被静默截断并插入 `[Truncated: …]` 标记；（4）约 300 KB 的二进制读取报 base64 非法，写入 2 MB 报 `OSError: Argument list too long` |
| **关联产品** | myrm-agent-harness `toolkits/code_execution/executors`（仓内生产执行器 `LocalExecutor` 全量原生覆盖这些方法，不受影响；受影响面仅为继承默认实现的第三方执行器与测试桩） |
| **根因** | （1）路径与模式用 `'{safe}'` 手工拼接单引号，`resolve_path` 只校验工作区边界、不转义引号；（2）（3）所有 shell 结果都经 `ExecutionResult.__post_init__` 的 `truncate_output` + `scrub_sensitive_info`，把文件内容当文本从 stdout 读取天然有损；（4）整个文件的 base64 内联在一条命令里，超过单参数上限（Linux 128 KB）；base64 输出同样被脱敏器处理，实测 64 KB 随机数据的 base64 文本约 13%–20% 的分片被改写（`/tmp/`、`/var/` 等路径片段命中），因此不能用 base64 读取 |
| **修复** | 所有路径与模式统一经 `shlex.quote`；新增 `executors/shell_file_transfer.py`：读取按 32 KiB 分片用 `dd` + `od` 输出十六进制（不含 `/`，脱敏器不会改写），小于一个分片的文件只需一条命令，大文件先取 `wc -c` 再逐片读取并校验总长；写入按 32 KiB 分片经 `printf %s '<base64>' \| base64 -d`，首片截断写、其余追加，每条命令远低于参数上限，任一分片失败抛 `OSError`（此前写入失败被静默忽略）；`read_file` / `read_file_bytes` / `write_file` / `write_file_bytes` / `append_file` 共用这两个原语；`base64` 读取不再使用（BSD/macOS 不接受位置参数） |
| **反复次数** | 第 1 次发现 |
| **踩坑** | 经 shell 取回文件内容必须假设 stdout 会被改写：脱敏与截断是整个执行结果层的统一行为，换编码要实测才能确认不被命中（base64 实测约 13%–20% 的 64 KB 分片被改写，hex 在 60 个 32 KiB 分片上 0 次）；管道的退出码只反映最后一级，`test -f F && dd … \| od …` 才能让缺失文件使整条命令失败；BSD 与 GNU 的 `base64` 参数约定不同；`echo` 对以 `-` 开头的内容行为不一，写入用 `printf %s` |
| **回归** | `tests/toolkits/code_execution/executors/test_base_executor_shell_quoting.py`（带引号文件名与注入模式；含密钥与绝对路径的文本读回原样；0 / 1 / 分片边界 ±1 / 5 分片+7 字节的随机字节往返；约 620 KB 文本不截断；截断写与跨分片追加；`.gz` 解压；缺失文件抛 `FileNotFoundError`、写入失败抛 `OSError`）；回退验证：恢复旧实现后脱敏、大随机字节、大文本、写入失败 4 个用例失败 |
| **代码位置** | `executors/shell_file_transfer.py`（`read_bytes_via_shell`、`write_bytes_via_shell`）· `executors/base.py::CodeExecutor`（文件操作默认实现） |

### BUG-HARNESS-2026-10-12-002 · 没有 doctype 的页面被判为“被模态遮罩阻塞”：html/body 因覆盖视口 50% 以上被当成遮罩，带 label 的输入框被标 `[blocked]` 且拿不到 ref

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-12 |
| **修复时间** | 2026-10-12 |
| **症状** | quirks 模式页面（无 doctype）上快照把整页标为 blocked，表单字段没有可用 ref，Agent 无法点击或填写；模态框内仅靠 `label`、`placeholder`、`title` 命名的字段在遮罩说明里也缺失 |
| **关联产品** | myrm-agent-harness `toolkits/browser/snapshot` |
| **根因** | `MODAL_BLOCKING_SCRIPT` 把覆盖视口 ≥50% 的任意元素视为遮罩，quirks 模式下 `html`/`body` 恒占满视口；模态内可操作元素的名称只取 `innerText` 与 `aria-label`，与无障碍树的命名来源不一致 |
| **修复** | 遮罩候选排除 `document.documentElement` 与 `document.body`（仍可凭 modal 属性或 dialog 角色成为候选）；模态内元素名称追加 `label`、`placeholder`、`title` |
| **反复次数** | 第 1 次发现 |
| **踩坑** | quirks 模式下 html/body 恒占满视口，必然触发；标准模式取决于页面内容高度，缺陷表现随页面而变，不易稳定复现 |
| **回归** | `tests/toolkits/browser/snapshot/test_modal_detection_integration.py`（quirks 模式页面不是模态；dialog 列出 Username、Submit、Email 字段）；回退验证：去掉根元素排除时 quirks 页面被判为 `{'role': 'region', 'coverage': 1, ...}`；去掉 label/placeholder/title 命名时 dialog 只列出 `{'Submit'}` |
| **代码位置** | `observer_scripts.py::MODAL_BLOCKING_SCRIPT` |

### BUG-HARNESS-2026-10-12-001 · 浏览器动作录制从不产生步骤：捕获脚本被注入到 patchright 的隔离世界，`expose_function` 桥在那里是丢弃调用的空桩

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-12 |
| **修复时间** | 2026-10-12 |
| **症状** | 录制会话开启后点击、输入等页面事件不会进入 Python 回调，录制得到空步骤；没有任何错误日志（注入异常被 `logger.debug` 吞掉） |
| **关联产品** | myrm-agent-harness `toolkits/browser/action_capture` |
| **根因** | patchright 的 `page.evaluate` 默认在隔离世界执行（`isolated_context=True`），而 `expose_function` 绑定只在主世界才会把调用送达 Python；隔离世界里的 `__myrmCaptureCallback` 是丢弃调用的空桩 |
| **修复** | `ActionCaptureEngine._inject_capture` 的两次 `page.evaluate` 都显式传 `isolated_context=False`，监听器与 `__myrmCaptureActive` 开关位于同一个主世界 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | 主世界注入意味着页面自己的脚本也能调用 `window.__myrmCaptureCallback(...)` 伪造步骤；该信任边界来自 `expose_function` 的设计本身，修复前后都存在，未在本条处理 |
| **回归** | `tests/toolkits/browser/action_capture/test_capture_engine_lifecycle.py` 的替身 `evaluate` 断言 `isolated_context is False`；`test_capture_engine_navigation_integration.py::test_capture_survives_navigation_and_restart` 在真实 Chromium 中验证：把两处 `isolated_context=False` 改回默认值时失败（`baseline click not captured: []`），修复后通过 |
| **代码位置** | `capture_engine.py::ActionCaptureEngine._inject_capture` |

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

### BUG-HARNESS-2026-10-08-005 · 干净检出的 `origin/main` 导入 `agent.middlewares` 即抛 `ImportError`：三方授权委托包的定义从未提交，CI 单测与浏览器作业大面积变红

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-08 |
| **修复时间** | 2026-10-08 |
| **症状** | 在 `git archive origin/main src` 解出的纯净源码树上执行 `import myrm_agent_harness.agent.middlewares`，抛 `ImportError: cannot import name 'get_delegation_token' from 'myrm_agent_harness.agent.middlewares._session_context'`，导入该包的模块全部加载失败。`origin/main`（`61c328b7`）的 CI 因此单测作业 629 个失败 + 170 个错误（共 799 条异常行，其中 685 条出自这条导入链），浏览器作业的 116 个收集错误全部出自它；开发者本地树里这些文件存在，本机看不到任何异常 |
| **关联产品** | myrm-agent-harness `agent/security/delegation` · `agent/middlewares/_session_context.py` · `agent/middlewares/__init__.py` |
| **根因** | `agent/middlewares/__init__.py` 重新导出 `get_delegation_token`，而它的定义（`_session_context.py` 中的 `set_delegation_token`/`get_delegation_token`，以及整个 `agent/security/delegation/` 包）只存在于本地树，从未提交。仓库里没有任何一步在“只含已提交文件”的树上导入包，缺失只能由 CI 的干净检出暴露；该包此前也没有任何测试引用（`tests/` 下零处） |
| **修复** | 补交 `agent/security/delegation/{__init__,models,guard}.py` 与 `_ARCH.md`（`agent/security/_ARCH.md` 增加索引行），并在 `_session_context.py` 增加 `set_delegation_token`/`get_delegation_token`（用上下文变量承载当前令牌）；只补已提交导出所需的定义。同一 PR 的单测作业失败数：修复前 `origin/main` 为 629 个失败 + 170 个错误，修复后首轮为 66 个失败，同一分支继续收敛到 4 个失败（`a7d8f69e`；66 到 4 的下降来自同一分支里与平台、测试隔离相关的修复，与本条无关） |
| **反复次数** | 第 1 次发现 |
| **踩坑** | 本地树完整不等于仓库完整：导出点与被导出的定义分属不同提交时，开发机上一切正常，唯一的信号是在只含已提交文件的树上导入包。最便宜的复核：`git archive HEAD src \| tar -x -C <dir>` 后以 `PYTHONPATH=<dir>/src` 导入 `myrm_agent_harness.agent.middlewares` |
| **回归** | `tests/agent/security/delegation/test_triad_delegation.py`：首个导入即 `from myrm_agent_harness.agent.middlewares import get_delegation_token`（定义缺失时在收集阶段失败）；其余用例覆盖有效权限 = 请求者与执行智能体的交集、审批人只能补充智能体已有的权限、通配符、过期令牌、子智能体收窄、守卫缺令牌时失败即关闭、`SubjectIdentity` 往返、会话访问器；`.github/workflows/test.yml` 在干净检出上运行全部单测 |
| **代码位置** | `agent/security/delegation/{models,guard}.py` · `agent/middlewares/_session_context.py::set_delegation_token/get_delegation_token`（该包因无任何生产调用方，已整体删除，上述路径与回归测试不再存在；“在只含已提交文件的树上导入包”的复核方法仍然适用） |

### BUG-HARNESS-2026-10-08-004 · 健康探活与连通性测试的“5 秒超时、1 个 token”从未生效：写在 `config` 里的限制到不了提供方，挂起的端点最多占住调用方 300 秒

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-08 |
| **修复时间** | 2026-10-08 |
| **症状** | 假客户端加真实适配器实测：`llm.ainvoke(messages, config={"max_tokens": 1, "timeout": 5.0})` 到达提供方调用的参数是 `max_tokens=4096`、`force_timeout=300.0`，两个限制都没有生效。受影响的调用点共三处：`lightweight_health_check`（故障转移对冷却候选的探活，以及服务端 `/check-reachability`）、设置页「测试本地模型」`POST /config/test-local-model`、每日回顾生成 `daily_wrap`。端点挂起时调用方最多等 300 秒；设置页在 15 秒后中止请求，只能显示不带原因的“连接失败”。文档与注释还写着“1-token 探活”，与行为不符；`lightweight_health_check_with_retry` 全仓库没有调用方 |
| **关联产品** | myrm-agent-harness `toolkits/llms/fallback/health_check.py`；myrm-agent-server `app/api/config/router.py`、`app/api/statistics/daily_wrap.py`、`app/api/integrations/llms.py`（文档） |
| **根因** | `ainvoke` 的 `config` 是 LangChain 的 RunnableConfig（回调、标签、元数据），不是模型调用参数，其中的 `max_tokens`、`timeout` 不会被转给提供方；真正的超时要么来自模型自己的 `request_timeout`（默认 300 秒），要么必须由调用方用 `asyncio.wait_for` 强制 |
| **修复** | `lightweight_health_check` 改为 `asyncio.wait_for(llm.ainvoke(...), timeout_s)`，到期即取消并返回 False；不强制 `max_tokens`（推理模型会拒绝低于其思考预留的预算，探活成本由截止时间约束）；删除无调用方的 `lightweight_health_check_with_retry` 及其导出。服务端：`/test-local-model` 设 12 秒截止（低于设置页的 15 秒中止，到期报告为“无响应，模型可能仍在加载或地址有误”，与提供方侧的连接超时区分）；`daily_wrap` 设 60 秒截止，到期转为 408 `timeout_error`，因为裸 `TimeoutError` 会被 `internal_error()` 报成 `Database operation timeout`（去掉转换的变异实测：500 `Get daily wrap failed: Database operation timeout`）；各处“1-token”文档与注释改为真实行为 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | 把 `config=` 当作单次调用参数是同一个误读，harness `src`、服务端 `app`、控制平面 `src` 中该写法已清零（逐目录搜索无剩余）。要给模型调用加时间上限，只能用模型构造参数或 `asyncio.wait_for`。12 秒与 60 秒是按设置页 15 秒中止和端点现有行为取的设计值，没有时延分布数据；服务端依赖已发布的 harness 版本，`/check-reachability` 的真实截止时间要等 harness 升版后才随发布生效 |
| **回归** | harness：`tests/toolkits/llms/fallback/test_health_check.py`（7 个，含到期取消与不转发 config）；服务端：`tests/api/config/test_local_model_endpoint.py`（4 个）、`tests/api/statistics/test_daily_wrap.py` 与 `test_daily_wrap_integration.py` 各 1 个；去掉截止时间的变异使 3 个超时用例全部失败；真实套接字实验（无 mock）：`lightweight_health_check` 对挂起的服务 2.01 秒返回 False 并关闭连接，端点 12.10 秒返回，取消后再次调用正常，对照组中适配器自身 15 秒仍未返回 |
| **代码位置** | `toolkits/llms/fallback/health_check.py::lightweight_health_check` · 服务端 `app/api/config/router.py::test_local_model/_LOCAL_MODEL_TEST_TIMEOUT_S` · `app/api/statistics/daily_wrap.py::_generate_wrap_via_llm/_WRAP_LLM_TIMEOUT_S` |

### BUG-HARNESS-2026-10-08-003 · 提供方拒绝 `max_tokens` 时整轮失败或误触发破坏性压缩，流式重试还会把已发出的内容再发一遍

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-08 |
| **修复时间** | 2026-10-08 |
| **症状** | 真实 litellm `BadRequestError` 逐条实测（修复前 `c61149b4^`）：DashScope、DeepSeek、Azure/OpenAI（`supports at most N completion tokens`）、Anthropic（`max_tokens: X > N, which is the maximum allowed number of output tokens`）、网关（`exceeds model's maximum output tokens (N)`）、火山方舟（`expected a value <= N`）、Groq（`must be less than or equal to N`）七类“超出模型输出上限”的 400 全部分类为 `FORMAT_ERROR`，`is_context_overflow` 为 False；旧解析只认出 DashScope（8192），其余六类解析为空，没有任何恢复，整轮失败。压力闸门 `is_presumed_overflow`（`FORMAT_ERROR` + HTTP 400 + 占用 ≥ 0.85）还会把这类 400 当成上下文溢出，触发破坏性压缩。另一条路径：流式调用先流出 `Hello` 再报窗口溢出（Anthropic 措辞），旧代码重启请求，调用方收到 `['Hello', 'Hello', ' world']`，即 `HelloHello world`（真实重放 `c61149b4^`） |
| **关联产品** | myrm-agent-harness `toolkits/llms/errors` · `toolkits/llms/adapters/chat_model` · `agent/streaming/recovery` |
| **根因** | 三处叠加：（1）旧解析器只覆盖 5 种措辞（Anthropic `available_tokens`、OpenRouter 分解、LM Studio 字符数、vLLM、DashScope 范围），模型上限类只有 DashScope 能解析，且只作为单次覆盖使用，不会被记住，每个新请求都再被拒一次；（2）四个调用循环（异步/同步 × 流式/非流式）各自复制一份恢复代码，“尚未向调用方发出任何内容”的保护只存在于其中一块；（3）压力闸门用“FORMAT_ERROR + 400 + 高占用”推断溢出，无法区分模型上限拒绝。推理模型的输出预留下限（16384）还会把请求预算抬高，增加触顶机会 |
| **修复** | 新增 `errors/output_limit.py`：`parse_output_limit` 返回类型化的 `OutputLimit(tokens, model_cap)`，覆盖七类模型上限与窗口余量措辞；新增 `adapters/chat_model/output_cap_recovery.py`：四个循环共用同一恢复步骤，重试之间只改 `max_tokens`（提示前缀缓存照常命中）；模型上限按声明值采用，并按（模型、base_url）记入有界（256 条、先进先出）、带过期（3600 秒）的内存表，只会在截断放大覆盖之后向下收紧；窗口余量留 64 个 token 余量且不记忆；采用值低于 500、不小于原请求、不高于思考预算，或拒绝状态码不在 400/413/422 时拒绝恢复。网关参数、payload 与输出上限三处恢复统一加“尚未发出任何内容”保护，内容已流出后的错误原样抛给调用方；压力闸门遇到明确的模型上限措辞不再判为溢出 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | 全部改动被另一会话使用共享索引的提交带走，落在 `c61149b4`（提交说明写的是别的特性，历史不能改写）。七类措辞取自提供方 issue、文档与网关测试集，没有做真实提供方调用；被拒的 400 是否计费未核实；3600 秒过期、500 下限、64 余量是设计取值，没有频率或时延数据 |
| **回归** | `tests/toolkits/llms/test_output_limit.py`（49 个）· `tests/toolkits/llms/adapters/test_output_cap_recovery.py`（44 个，含流式“内容已发出后不重启”、重试只改 `max_tokens`、记忆表有界先进先出与过期）· `tests/agent/streaming/test_context_pressure_gate.py`（+1 个）；去掉“尚未发出内容”保护的变异使 6 个流式用例失败，“首块之前仍恢复”的用例保持通过 |
| **代码位置** | `toolkits/llms/errors/output_limit.py` · `toolkits/llms/adapters/chat_model/output_cap_recovery.py` · `adapters/chat_model/async_mixin.py` / `sync_mixin.py` / `model.py` · `agent/streaming/recovery/context_pressure_gate.py::is_presumed_overflow` |

### BUG-HARNESS-2026-10-08-002 · `litellm` 下限被抬到 1.104 后依赖集无解：`uv lock` 与 `uv sync --locked` 失败，发布的 wheel 也装不上

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-08 |
| **修复时间** | 2026-10-08 |
| **症状** | `pyproject.toml` 核心依赖同时要求 `litellm>=1.104.0` 与 `filelock>=4.0.12`；`litellm` 1.104 起的基础依赖要求 `filelock<4`，二者互斥，`uv lock` 与 `uv sync --locked` 无解，按该元数据发布的 wheel 同样无法安装 |
| **关联产品** | myrm-agent-harness `pyproject.toml`（核心依赖）· `uv.lock` |
| **根因** | `777f32ab` 把 `litellm` 下限抬到 1.104.0，没有考虑它对 `filelock` 的传递性上限与项目自己的 `filelock>=4.0.12` 冲突；这类冲突只有依赖解析器会报 |
| **修复** | 下限回到 `litellm>=1.98.0`，依赖行注释写明“`litellm>=1.104` 要求 `filelock<4`，下限不可越过 1.103.x”；`uv.lock` 保持 litellm 1.103.3，只刷新说明符行，锁定版本没有变化 |
| **反复次数** | 第 1 次发现；与 `BUG-HARNESS-2026-10-07-007` 同属“核心依赖下限与其他依赖的传递性约束互斥”一类 |
| **踩坑** | 抬升核心依赖下限必须同时重新解析（`uv lock`）。本机 uv 配置了清华镜像，在仓库内重新生成锁文件会把全部 registry 地址改写成镜像地址，提交前必须确认 `uv.lock` 的差异不含镜像 URL |
| **回归** | `tests/architecture/test_core_dependencies.py::test_uv_lock_core_matches_pyproject`；`.github/workflows/test.yml` 的 `uv sync --locked` |
| **代码位置** | `pyproject.toml`（`litellm` 依赖行） |

### BUG-HARNESS-2026-10-08-001 · 技能与专家导出的脱敏把密钥原样留在包里、把无害设置改成占位符，且审阅面板的类型标签是英文原文

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-08 |
| **修复时间** | 2026-10-08 |
| **症状** | 用修复前的脱敏器（`27c02425^`）对单行样本实测：`https://x.io/cb?access_token=abcdef1234567890abcd&a=1` 输出 `https://x.io/cb<REDACTED_PARAM>abcdef1234567890abcd&a=<REDACTED_VALUE>1`，令牌原文仍在、URL 被破坏；`Authorization: Bearer abcdefghijklmnop12345678` 输出 `Authorization: <REDACTED_TOKEN>abcdefghijklmnop12345678`，令牌原文仍在；`OPENAI_API_KEY=sk-…` 输出 `<REDACTED_TOKEN<REDACTED_VALUE>>`（占位符嵌套）。第一轮修复后（`27c02425`）密钥已被替换，但 `max_tokens: 4096`、`auth_type: bearer`、`api_key_env: OPENAI_API_KEY`、`api_key: $OPENAI_API_KEY`、`token: <your-token>` 这类只是描述或指向密钥的设置也被改成 `<REDACTED_VALUE>`，导出的专家包因此被改坏。审阅面板每条发现旁显示的类型是后端英文原文，非中文界面的用户直接看到英文 |
| **关联产品** | myrm-agent-harness `agent/skills/security/content_sanitizer.py`；消费方：单技能导出、专家导出、Marketplace 发布（共用同一脱敏器） |
| **根因** | （1）检测按共享正则的捕获组序号读取，组序号与规则漂移后替换的区间是密钥旁边的文字，而不是密钥本身；（2）关键词命中即脱敏，没有区分“密钥本身”和“关于密钥的设置/指向密钥的占位”；（3）重叠命中只保留一个，较短的那条所覆盖的片段会残留；（4）发现项携带的是展示用英文文本，而不是调用方可本地化的稳定码 |
| **修复** | 脱敏改为规则表：每条规则显式声明密钥所在的捕获组（以及名称组），复用运行期同一份关键词守卫；`_NON_SECRET_KEY_RE` 放过描述密钥的设置名（`max_tokens`、`*_type`、`*_env`、`*_url` 等），`_PLACEHOLDER_RE` 放过 `$VAR`、`{{x}}`、`<your-token>`、全大写变量名；重叠命中取并集，一个密钥不会只被遮住一半；发现项的 `reason` 改为封闭枚举 `SecretKind` 的 `kinds: list[SecretKind]`，server 原样透传，前端按六语言文案渲染，未知码回落到通用文案。取舍：单次脱敏比旧版慢约 1.3–2 倍（4000 行 / 360 KB 实测 266–406 ms 对 190–225 ms；64 KB 封顶时约 50 ms），换来的是上述密钥不再残留 |
| **反复次数** | 第 2 次发现（同一脱敏器连续两轮修复：先修“替换了错的区间”，再修“误伤设置与占位符”） |
| **踩坑** | 只改捕获组序号不会暴露问题，因为旧用例只断言“输出里出现占位符”，没有断言“密钥原文不再出现”；占位符 `$VAR`、全大写变量名与真密钥长得很像，必须用真实样本逐条对照；规则的组布局漂移必须由测试拦截，否则下次共享正则改动会悄悄复发 |
| **回归** | `tests/agent/skills/test_content_sanitizer.py::TestSecretNeverSurvives` · `::TestSurroundingSyntaxIsPreserved` · `::TestProseIsNotRedacted` · `::TestMultipleSecretsPerLine` · `::TestFindingKinds` · `::TestRuleTable`（组布局、每个类型码可达、重叠取并集）；跨层：myrm-agent-server `tests/integration/test_redaction_kinds_i18n_sync.py`（类型码与前端六语言文案一一对应） |
| **代码位置** | `agent/skills/security/content_sanitizer.py::_SECRET_RULES/_merge_overlaps/_NON_SECRET_KEY_RE/_PLACEHOLDER_RE/Redaction/SecretKind` |

### BUG-HARNESS-2026-10-07-008 · 连接在工具调用中途被干净关闭时，LiteLLM 合成的 `stop` 让半截参数被补全并当作完整调用执行

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-07 |
| **修复时间** | 2026-10-07 |
| **症状** | 真实 LiteLLM 1.98.0 加适配器，用回环假提供方端到端复现：工具调用参数流在两个字段之间被切断（`{"path": "/tmp/report.md", "content": "Dear Alice.", ` 之后连接关闭，提供方从未发出结束标记），适配器照常补全，把 `{"content": "Dear Alice.", "path": "/tmp/report.md"}` 当作完整调用交给执行，原本要带上的 `overwrite: true` 悄悄丢失；OpenAI 对话线路与 Anthropic（内容块未关闭、已关闭两种切法）三种情形全部复现；停在字符串值内部的切断本来就被拒绝（`truncated_mid_value`），不受影响 |
| **关联产品** | myrm-agent-harness `toolkits/llms/adapters` |
| **根因** | LiteLLM 流包装器在流结束而提供方没发过结束原因时，用合成的 `stop` 收尾（见到工具增量则升级为 `tool_calls`），块层与正常结束完全相同；`finalize_stream` 只看这个 `finish_reason` 判断流是否完整，于是把被切断的参数当作完整输出补全 |
| **修复** | 包装器自己记录提供方真正发送的结束原因（`received_finish_reason` / `intermittent_finish_reason`）；`StreamAggregator.track` 记住正在消费的提供方流，`provider_reported_finish` 在流耗尽后读取这两个标记，都为空即判定提供方没有结束这条流，`is_stream_complete(finish_reason, provider_finish)` 随之返回 False，沿用既有的“扣留—重试一次”协议；没有这两个标记的流（Responses 线路的迭代器）返回 None，仍只看 `finish_reason`；`finish_reason` 的记录、遥测与完成状态口径不变；`async_mixin.py`、`sync_mixin.py` 各改 1 行，行数不变。取舍：从不发送 `finish_reason` 的网关，其格式错误且需要补全的工具参数现在会被扣留并重试一次，而不是补全后执行（格式正确的参数走快速路径，不受影响） |
| **反复次数** | 第 1 次发现 |
| **踩坑** | 初版用例把切口放在字符串值内部，修复前后都通过（该情形早有闸门拦截），证明不了修复；切口必须落在两个值之间才暴露补全；判断依据用包装器真实记录的两个标记，而不是去猜“合成的 stop”；LiteLLM 改名这两个属性时，切断用例会变红而不是悄悄放行，起金丝雀作用；不把该信号写进 `finish_reason` 遥测，避免对从不发 `finish_reason` 的网关把每个回合都标成截断 |
| **回归** | `tests/toolkits/llms/core/test_stream_cut_wire.py`（OpenAI 对话与 Anthropic 的值间切断被扣留、值内切断仍被扣留、完整调用照常执行、被切断的文本回答原样保留）· `tests/toolkits/llms/adapters/test_stream_aggregator.py::TestFinalizeStreamProviderFinish` · `tests/toolkits/llms/adapters/test_streaming_and_parser_edges.py::TestProviderReportedFinish` · `tests/toolkits/llms/adapters/test_tool_recovery.py::TestIsStreamComplete` · 2026-10-08 复核：`test_stream_cut_wire.py`、`test_native_anthropic_wire.py`、`test_output_budget_wire.py` 三个回环文件在 LiteLLM 1.98.0、1.103.3（lock 版本）、1.104.1（最新发布）上均通过；litellm ≥1.103 下需要 `pyproject.toml` 放行 pydantic 对 LiteLLM `ReadOnly` TypedDict 的 `UserWarning`，否则 `filterwarnings = error` 会让这些用例全部失败 |
| **代码位置** | `toolkits/llms/adapters/streaming.py::provider_reported_finish` · `toolkits/llms/adapters/stream_aggregator.py::StreamAggregator.track/provider_finish` · `toolkits/llms/adapters/tool_recovery.py::is_stream_complete` · `toolkits/llms/adapters/chat_model/async_mixin.py` · `toolkits/llms/adapters/chat_model/sync_mixin.py` |

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

### BUG-HARNESS-2026-10-07-006 · 原生 Anthropic 调用带着 Messages API 不接受的字段：每次调用多发 1–2 个被拒请求且用量记录为空，设置推理强度或额外参数时请求永久失败

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-07 |
| **修复时间** | 2026-10-07 |
| **症状** | 用严格回环假提供方（对多余顶层字段回 400 `<key>: Extra inputs are not permitted`，字段集合取自 Messages API 的请求字段）实测，修复前：普通流式调用发 2 个请求（首个因 `stream_options` 被拒）、token 用量记录为 `(None, None)`；带工具的调用发 3 个请求；设置 `reasoning_effort`（产品的 lite/降级模型一律带 `low`）或任何额外参数（`top_p`、`top_k`、`thinking`、`metadata` 等）时只发 1 个请求并以 400 `extra_body: Extra inputs are not permitted` 永久失败。修复后四种情形均只发 1 个请求并成功，用量记录为 `(3, 9)`，`reasoning_effort=low` 被 LiteLLM 翻译为 `thinking`。真实 Anthropic 接口未用密钥验证，结论以该假提供方（按文档化的拒绝行为实现）与普通 LiteLLM 的请求体为准 |
| **关联产品** | myrm-agent-harness `toolkits/llms/core` · `toolkits/llms/adapters/chat_model` · `toolkits/llms/adapters/wire` |
| **根因** | 两处：① `_inject_allowed_params` 向每次调用注入 `allowed_openai_params`，LiteLLM 因此把调用里的每个键（`stream_options`、`reasoning_effort`、`parallel_tool_calls`、`response_format`、`stop`、`user`、字面 `extra_body` 等）原样转发，叠加在它自己的 Messages 翻译之上；② `llm.py` 把 `reasoning_effort` 与额外 kwargs 复制进 `extra_body`，LiteLLM 对 Anthropic 不会平铺它而是原样发送一个 `extra_body` 字段。被拒的 `extra_body` 不在网关归一化器可剥离的参数清单内，请求直接失败；`stream_options` 被剥离重试后，LiteLLM 不再产出 Anthropic 的用量事件，用量记录为空 |
| **修复** | 新增 `adapters/wire/native_anthropic.py::is_native_anthropic_wire`，用 LiteLLM 的提供方解析判断是否第一方 Anthropic 接口（OpenRouter、Bedrock、Vertex AI、`openai/` 自定义网关和无法分类的模型都不算，行为不变）；`allowed_params.py::inject_allowed_params` 从 `model.py` 拆出，对原生 Anthropic 调用不再注入白名单；`llm.py` 对原生 Anthropic 不再向 `extra_body` 复制 `reasoning_effort` 与额外 kwargs；`stream_options` 仍留在调用参数中（LiteLLM 靠它产出用量事件，并自行从线上请求体里去掉）；`model.py` 行数净减少 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | 只剥离已知被拒参数的反应式重试，既多发请求又会丢失依赖这些参数的副作用（用量事件），而且对不在清单里的字段无能为力，必须在发送前就不放进请求；只拦截三个已知字段的拒绝清单方案实测仍会泄漏 `response_format`、`stop`、`user`、`web_search_options`，整体不注入白名单才让多余字段为零；断言构造参数发现不了问题，必须用真实 LiteLLM 加严格回环假提供方断言线上请求体与请求数 |
| **回归** | `tests/toolkits/llms/core/test_native_anthropic_wire.py`（线上请求数与字段集合、用量到账、推理强度翻译为 `thinking`、带工具调用保留并行选择、`stop`/`user` 被翻译而非重复、额外参数不再变成字面 `extra_body`、短调用保护 `max_tokens=30` 且无 `thinking`、OpenAI 线路仍保留 `stream_options`/推理强度/镜像）· `tests/toolkits/llms/adapters/wire/test_native_anthropic.py`（判定真值表）· `tests/toolkits/llms/adapters/test_allowed_params.py` · `tests/toolkits/llms/core/test_merge_model_kwargs.py` |
| **代码位置** | `toolkits/llms/adapters/wire/native_anthropic.py` · `toolkits/llms/adapters/chat_model/allowed_params.py` · `toolkits/llms/adapters/chat_model/model.py::ChatLiteLLM._inject_allowed_params` · `toolkits/llms/core/llm.py::create_litellm_model` |

### BUG-HARNESS-2026-10-07-005 · 额外参数镜像把调整前的输出上限和调用方的 `extra_body` 写进请求体，思考模型的输出预算与截断重试在 OpenAI 兼容网关上不生效，传入 `extra_body` 时请求直接失败

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-07 |
| **修复时间** | 2026-10-07 |
| **症状** | 用户把最大输出长度配得低于思考模型的预留下限（如 1024），经 OpenAI 兼容网关调用思考模型时，请求体里的 `max_tokens` 仍是用户配置的 1024，而不是抬升后的值：真实 MiniMax 网关实测 `finish=length`、答案为空；长度截断后的“预算翻倍重试”同样不到线上，重试照旧被截断；调用方经 kwargs 传入 `extra_body` 时，请求在序列化阶段以 `Circular reference detected` 失败（LiteLLM `InternalServerError`，用回环假提供方端到端复现） |
| **关联产品** | myrm-agent-harness `toolkits/llms/core` · `toolkits/llms/utils` · `agent/streaming/recovery`；myrm-agent-server 三处短回复调用 |
| **根因** | `llm.py` 把全部额外 kwargs 同时复制进 `extra_body`，其中包含 `max_tokens`、`extra_body` 自身和仅供工厂使用的 `supports_reasoning`；OpenAI SDK 在发送时把 `extra_body` 平铺覆盖到类型字段之上，于是线上 `max_tokens` 永远等于调整之前的值，抬升与重试覆盖都被它盖掉；`extra_body` 被复制进自己，形成自引用字典 |
| **修复** | 镜像排除 `max_tokens`、`extra_body`、`supports_reasoning`，复制而不原地修改，调用方已有的键优先；抬升后的输出预算真正到达提供方，因此新增上限夹取：配置值被抬升到思考下限、以及截断重试放大预算时，都不超过 LiteLLM 价目表记录的该模型单次输出上限；价目表低于已被提供方接受的预算时视为过期条目，不会把预算压低，无配置值时仍使用完整下限；预算计算从截断恢复混入类拆出为 `StreamOutputBudgetMixin`；服务端的伴宠回应（30）、Advisor（256）、标题（1024）三处刻意很短的调用声明 `supports_reasoning=False`，不被抬升到思考下限；设置页“最大输出长度”说明文案改为说明推理模型会自动获得更大的上限（6 种语言） |
| **反复次数** | 第 1 次发现 |
| **踩坑** | 把同一个值同时放进类型字段和 `extra_body` 的镜像，在 SDK 的合并顺序下 `extra_body` 总是赢，凡是后续逻辑会调整的值都不能镜像；断言构造参数发现不了问题，必须用真实 LiteLLM 加回环假提供方断言线上请求体；价目表的远端副本与内置副本内容不同，依赖它的测试必须固定上限查找，否则随网络状况翻转；价目表条目可能过期偏低，夹取必须以“提供方已接受的预算”为下界 |
| **回归** | `tests/toolkits/llms/core/test_output_budget_wire.py`（线上请求体：低于下限的配置值抬升到下限、非思考模型的配置值原样保留、高于下限不被压低、短调用保护、重试覆盖值到达线上、调用方 `extra_body` 只发送一次）· `tests/toolkits/llms/core/test_merge_model_kwargs.py`（镜像排除项、复制不修改、调用方键优先）· `tests/toolkits/llms/core/test_thinking_headroom.py::TestOutputCeilingClamp` · `tests/toolkits/llms/utils/test_model_utils.py` · `tests/agent/streaming/test_stream_executor_length_truncation.py`（重试预算夹取）· 服务端 `tests/api/companion/test_companion_react.py` · `tests/services/copilot/test_advisor_service.py` · `tests/services/chat/test_chat_title.py` |
| **代码位置** | `toolkits/llms/core/llm.py::_NEVER_MIRRORED/_merge_model_kwargs_to_extra_body` · `toolkits/llms/core/reasoning_profile.py::apply_thinking_headroom` · `toolkits/llms/utils/model_utils.py::get_model_output_ceiling/clamp_budget_to_model_ceiling` · `agent/streaming/recovery/stream_recovery_budget.py` · 服务端 `app/api/companion/router.py` · `app/services/copilot/advisor_service.py` · `app/services/chat/chat_title.py` |

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
| **修复** | 单一谓词 `has_withheld_tool_calls`（`tool_recovery.py`）识别扣留记录；`event_handlers` 保留这类消息；`_handle_length_truncation` 在“长度截断”或“存在扣留调用”任一成立时触发，`_has_tool_calls`（截断与空响应处理器共用）把扣留调用计入工具调用；重试仍最多 1 次、输出预算翻倍（以 `MAX_EPHEMERAL_OUTPUT_TOKENS` 为上限；配置预算已达上限时保持原值，覆盖值不再低于配置预算）、请求前缀只追加一条提示（提示缓存前缀不变），重试失败上报 `tool_call_truncated`（用户可见文案说明该调用未执行，处理建议为重新发送请求，不再提示检查输出文件）；新增 `truncated_json.py::ends_inside_string` 与 `litellm_utils` 的闸门：截断落在字符串值内一律拒绝修复（`truncated_mid_value`，不可执行），数字、字面量、键、容器边界处的截断仍可补全；重试提示改为与成因一致（参数不完整或无效）；补齐 5 种语言的 `tool_call_retry` 文案；流在收到最终元数据块之前断开时，`finish_reason` 记为哨兵 `__stream_dropped__`：用量账本的 finish_reason 桶由空串改为该值，`completion_status` 由 `complete` 改为 `truncated`，并禁止“补全 JSON”式修复；统计截断率的报表需按原始 `finish_reason` 把 `length`/`max_tokens` 与 `__stream_dropped__` 分开，并以 2026-10-07 作为口径分界；上游干净关闭时 LiteLLM 会合成 `stop`，这类流不会落入该哨兵（实测，LiteLLM 1.98.0），其工具参数由 BUG-HARNESS-2026-10-07-008 处理 |
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
| **代码位置** | `toolkits/browser/doctor/checks.py` · `tests/toolkits/browser/doctor/test_doctor.py` |

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
