# Myrm Agent Harness — Bugfix Log

> 每次 harness 框架层用户可感知失败/运行时 bug，**必须追加一条**。产品业务 bug 记各产品仓台账（`myrm-agent/myrm-agent-server`）。

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
| **踩坑** | ① 会话层的「标志已传」是错觉：`Navigator` 用了标志、`navigate` 也返回了结果，过滤器在另一层又拦一次，单看会话层测试发现不了；红测必须走真实 Chromium 并统计服务端收到的请求数，才能区分「被拦」与「页面为空」；② 夹具替换安装函数是反向的 Goodhart：它让依赖它的测试变绿，却让没用它的 10 例一直红着，没有人把两件事连起来；删掉夹具后 guarded 档要自己说明为何需要放行；③ 新增的局部变量 `policy` 与同一构造函数后面的 `policy = DialogPolicy(…)` 同名，mypy 在 275 / 278 / 279 行新增 3 条类型错误，改名 `policy_kwargs` 后消失；④ 评估过但不做：云元数据地板——标志为真时仍对 `169.254.169.254` 等 `_CLOUD_METADATA_HOSTS`（`core/security/redirect_hop_guard/hop_evaluator.py:30,143`）保持拦截。结论不做：浏览器导航只能发 GET，读不出需要自定义请求头 / PUT 的 IMDSv2、GCP、Azure 元数据；受支持的云托管形态本来就传 `False`；剩余暴露面只有「自托管 WebUI 远程部署、云主机仍开着 IMDSv1、再叠加提示注入」这一条链，价值约 3 / 10 |
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
| **代码位置** | `agent/security/delegation/{models,guard}.py` · `agent/middlewares/_session_context.py::set_delegation_token/get_delegation_token` |

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
