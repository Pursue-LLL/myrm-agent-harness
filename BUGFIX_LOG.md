# Myrm Agent Harness — Bugfix Log

> 每次 harness 框架层用户可感知失败/运行时 bug，**必须追加一条**。产品业务 bug 记各产品仓台账（`myrm-agent/myrm-agent-server`）。

### BUG-HARNESS-2026-10-17-002 · 搜索链上头部供应商接受请求后不回话时，请求合并的等待与重试用光整条链的预算，备用供应商一次都没有运行，整次搜索只能在外层限时（默认 62.5 秒）后以超时结束；整链失败的最后一次异常是超时时，错误文字为空

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-17（复核 topic_02 #141 ② 当时「评估后不做」的结论：把网络边界换成永不应答，经真实的请求合并、单跳重试循环与外层 `wait_for` 复现） |
| **修复时间** | 2026-10-17（`ba6a36e3a`） |
| **症状** | ① 配置了多家搜索供应商、头部接受连接后不回话：备用供应商不被尝试，整次搜索直到外层限时才以超时结束；② 整链失败而最后一次异常是超时（`str()` 为空）时，`AllQueriesFailedError` 的文字为空，`WebSearcher._extract_key_error` 取不到原因，失败说明里没有内容 |
| **关联产品** | myrm-agent-harness `toolkits/web_search/providers/chain.py`、`toolkits/web_search/coalescing/search_coalescing.py`；server 与前端未改；不改提示词、消息顺序与工具 schema，提示缓存前缀不受影响 |
| **根因** | ① 链预算（`chain.py:47`，45 秒）只在两跳之间检查，单跳时长由该供应商自己的超时与重试决定：单次尝试 20 秒（`web_searcher.py:96`）、合并等待 30 秒（`search_coalescing.py:32`）两次、再加重试，合起来超过 45 秒，头部一旦挂起，就没有时间留给下一跳；② 最终错误文字取自 `str(last_error)`，超时异常没有文字 |
| **修复** | 除最后一跳外，每一跳的时限是链剩余预算的一半（`chain.py:194-196`），超时后转到下一家；最后一跳不另设上限，保有全部剩余预算；整链失败而最后一次异常没有文字时，错误文字回落为异常类型名（`chain.py:222-227`），`_extract_key_error` 把它读成 `Search request timeout`；被时限放弃的那一跳留下的合并请求领头者，其结果在创建时就登记取回回调（`search_coalescing.py:89-94`、`:132`），晚失败不再留下「Future exception was never retrieved」。同批（`3e315f31f`、`d97921446`）删除了链内转移事件及其余 8 处没有消费者的 `tool_fallback` 状态事件，以及从未接入任何搜索路径的分级 TTL 治理器（净减约 700 行） |
| **反复次数** | 第 1 次发现（同族问题记在 `BUG-HARNESS-2026-10-16-011` 的局限 ②，当时判为「评估后不做」，本条推翻） |
| **踩坑** | ① 最先想的是给最后一跳也封顶：只会让只配一家供应商的用户多发一次必然失败的请求，而且网关回退到自有密钥发生在单跳的重试循环里，不能靠把重试次数设为 0 替代，所以最后一跳不封顶；② 限时放弃等待方后，领头者晚失败会在日志里留下「Future exception was never retrieved」，是写测试时发现的，随修复一并处理；③ 复现要让真实的请求合并与重试循环参与、只替换网络调用，三个时钟按生产的 20、30、45 秒同比缩小 |
| **回归** | `tests/toolkits/web_search/test_chain_hang_failover.py` 4 例：头部挂起时备用接手、最后一跳保有全部剩余预算、只配一家供应商挂起时报 `Search request timeout`、被放弃的领头者晚失败不留「未取回」日志。三个时钟缩小 100 倍（单次尝试 0.2 秒、合并等待 0.3 秒、链预算 0.45 秒），外层限时放宽到 5 秒、不干扰判定。修复前 4 例全部失败（用 pytest 插件在内存里换入 `ba6a36e3a^` 的 `chain.py` 复跑，不动工作区）；变异验证两处：把最后一跳也封顶则「最后一跳保有剩余预算」一例失败，去掉领头者结果的消费则「未取回」一例失败；该文件连续运行 5 次稳定；`tests/toolkits/web_search` 整个套件 498 例通过（8 例按项目配置未选中） |
| **局限** | ① 挂起在真实供应商上的发生频率与计费没有实测，所有失败形状都是构造的；② 「剩余的一半」是按预算推导的（默认链预算下约 22.5 秒），不是按真实延迟分布调出来的；③ 缩时复现只证明路径，没有在真实供应商上做断网对照；④ 只配置一家供应商的用户没有更快失败，只得到有文字的错误；⑤ 删除的 `tool_fallback` 事件在仓内没有消费者，仓外的第三方消费者没有核对；⑥ 被放弃的那一跳在后台继续跑完自己的重试：合并请求的领头者任务不随等待方取消（`search_coalescing.py:134`），受单次 20 秒上限约束，对挂起供应商的请求照发，晚到的成功结果会写进缓存、它的指标也晚到；⑦ 链成员自带网关配置时，网关超时后的自有密钥直连重试在非末位只剩链剩余时间的一半以内；生产路径里链成员不带网关配置（`config_parsers.py:1021-1027`），`agents.py:95` 只给头部包装配置挂网关，而链模式不读头部的网关配置，这是否符合预期没有核对 |
| **代码位置** | `toolkits/web_search/providers/chain.py::search_provider_chain` · `toolkits/web_search/coalescing/search_coalescing.py::_mark_outcome_retrieved` · `tests/toolkits/web_search/test_chain_hang_failover.py` |

### BUG-HARNESS-2026-10-17-001 · 存储占用台账只认 server 的五个固定目录名和两个数据库文件：备份目录、其余目录与文件、数据库的 `-shm`、被部署搬到别处的记忆与日志都不在账上，各类占用之和对不上状态目录；框架里写死了业务层的目录名，查看占用还会顺手创建不存在的数据目录；同批删掉没有兑现承诺的压缩器、按固定阈值给出的建议与无人读取的逐表行数

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-16（核对存储治理的对外说法与实现时读 `inspector.py`：目录名与数据库路径写死，没有「其余」一类；随后在改动前的源码（`65d24ab17^`）上，用临时目录里的合成状态目录复现） |
| **修复时间** | 2026-10-16 至 2026-10-17（先删除没有兑现的部分 `63c713437`，再改归属规则 `65d24ab17`，补测试类型 `71f04aed7`） |
| **症状** | ① 合成状态目录（`data.db` 及其 `-wal`、`-shm`，检查点库，工作区、向量库、记忆、事件日志、快照目录，备份目录，上传目录与一个配置文件，共 7,933,768 字节）：改动前各类占用之和 5,950,000 字节，差 1,983,768 字节 = 备份目录 1,700,000（含一个 100,000 字节的 `.tmp-` 孤儿）+ 上传目录与配置文件 251,000 + `data.db-shm` 32,768，这三样没有任何类别提到；② 记忆与事件日志挪到另一块盘（部署用的 NAS 布局）：两类显示 0 字节（实际共 400,000），差额扩大为 2,383,768；③ 对一个不存在的状态目录调用 `inspect()`，检查器先 `mkdir` 把它建出来（改动前创建了该目录）；④ 同一模块里有四样没有兑现承诺或没有读取方的东西：`StateStorageCompactor`（WAL 截断加 `PRAGMA optimize`，应用侧已经覆盖：SQLite 自己做检查点，`VACUUM` 在 server 的存储优化里；增量 vacuum 的分支对没有开 `auto_vacuum` 的库不可达）、`recommended_actions` 与 `is_growth_healthy`（按固定字节阈值产生，用户无从据以行动）、逐表行数 `details` 与 `display_name` 回退（没有读取方） |
| **关联产品** | myrm-agent-harness `observability/storage_governance/`（`layout.py`、`walker.py`、`inspector.py`、`types.py`、`__init__.py` 与 `observability/__init__.py` 的导出、`_ARCH.md`）；`StorageGovernanceInspector` 的构造由 `checkpoints_db=` 改为必填的关键字 `layout=`，仓内唯一的生产调用方是 server 的 `app/api/system/router.py`（产品仓同日条目 `BUG-AGENT-2026-10-17-001`）；删除的符号 `StateStorageCompactor`、`CompactionResult`、`recommended_actions`、`is_growth_healthy`、`details`、`display_name`，全仓检索没有其他引用；不改提示词 |
| **根因** | ① 业务层的目录布局写进了框架：检查器写死了 server 的五个目录名与两个数据库路径，部署搬走路径或 server 新增目录时账本不认，也违背「框架只放自己的规则」；② 没有「其余」一类，各类之和不对应状态目录；数据库只统计 `-wal`，不统计 `-shm` 与 `-journal`；③ 查看接口先 `mkdir`，读操作有写副作用；④ 压缩器、建议与逐表行数没有核对过它们对用户是否起作用：压缩器做的事应用已经做了，建议依据固定阈值，逐表行数没有读取方 |
| **修复** | `StorageGovernanceInspector(data_dir, layout=...)`：应用声明每个类别的路径，检查器只负责规则与量取。归属规则在 `layout.py`（纯路径逻辑，不触碰磁盘）：文件归属于声明路径最深的类别；声明为非目录的路径视为数据库文件，其 `-wal` / `-shm` / `-journal` 一并归属；数据目录里没有被认领的部分报为 `other`（永远排在最后，不可声明，声明会抛 `ValueError`）；声明路径可以在数据目录之外；同一路径被两个类别声明时归先出现的类别并记一条警告，不让整份报告失败。量取在 `walker.py`（`os.scandir` 迭代实现）：符号链接不跟随也不计，只计常规文件的表观大小。`inspect()` 不再创建目录。新增类别 `sqlite_backups`（排在 `snapshots` 之前，`other` 永远最后）。删除上述四样，类别仍按文件大小归属，共用的报告类型保留 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | ① 项目的 mypy 只门禁 `src`，测试里 25 处缺少返回类型一直没人看见，核对时才由 `no-untyped-def` 报出，随 `71f04aed7` 补齐；② 核对「各类之和等于总量」不能拿检查器自己的遍历当基准：测试里用一次独立的 `os.walk` 作为基准，被测代码与基准各走一遍 |
| **回归** | `tests/observability/test_storage_governance.py` 与 `test_storage_layout.py` 共 24 例通过（harness `dc7937b41`），含：各类之和等于对数据目录独立遍历的结果、NAS 式布局、WAL 模式的活库、符号链接、不可读目录、三种 sidecar；归属规则的 8 个变异各使至少一例失败（提交 `65d24ab17` 说明里的记录，落地时测得）；同一份合成状态目录在改动前后的对照（复现脚本放在 /tmp，没有入库）：① 改动前差 1,983,768 字节，改动后各类之和 7,933,768 与独立遍历一致，差 0；② 搬到另一块盘的记忆与事件日志，改动前显示 0，改动后在原位报出 300,000 与 100,000，差 0；③ 对不存在的目录 `inspect()` 之后该目录是否被创建：改动前是，改动后否；目录量取在 6 万个文件（600 个目录，每个 100 个 100 字节的文件）、暖缓存下，旧写法（`os.walk` 加 `Path.stat`）与 `os.scandir` 迭代的总量一致，各 9 次取中位数：三轮分别为 835 / 768 / 660 ms 对 400 / 347 / 272 ms，快 2.1–2.4 倍；整份 `inspect()`（同样 6 万个文件加一个 45 万行的 `data.db`，旧实现含逐表 `COUNT(*)`）两轮各 7 次取中位数：602 / 792 ms 对 243 / 280 ms，快 2.5 与 2.8 倍；绝对耗时随机器负载波动一倍以上（较空闲时测得 440–460 对 211–285 ms），可移植的是比值；测量脚本放在 /tmp，没有入库；ruff、ruff format、mypy（strict）对触及文件无问题 |
| **局限** | ① 报告的是文件的表观大小，不是磁盘块占用：同一文件的每个硬链接名各算一份，稀疏文件按逻辑长度，块对齐不计，总量因此与 `du` 不一致；符号链接不跟随：把某个目录以链接形式放进数据目录时，链接指向的内容不计入（声明的路径本身是链接时会解析一次）；② 没有在本机真实数据目录上测过耗时与差额（不用真实数据做开发测试），目录量取的数字来自合成目录；③ 删除的是公开导出的符号，仓内检索没有其他引用，仓外使用者没有核对；④ 与 `BUG-HARNESS-2026-10-16-013` 相同：改动在本地源码、没有 push、没有发布，服务端依赖固定 `==0.1.0rc5`：新的服务端代码用到 `layout=` 与 `StorageCategory.SQLITE_BACKUPS`，只能在发布 harness 并 `./myrm harness sync-lock` 之后一起上线，拆开会让 `GET /system/storage/governance` 报错（按代码推断，没有在 rc5 上实测）；⑤ 存储优化前生成的 `data.db.optimize_backup` 落在 `other`，没有归入 `sqlite_backups`；⑥ 每次请求都完整遍历数据目录，没有缓存也没有合并并发请求：6 万个文件时单次 169–244 ms，4 个并发请求的总耗时 2.2–2.4 s（三轮，合成目录，本机）；前端在打开页面与每次快照创建 / 恢复 / 删除之后各请求一次，较早的请求结果被丢弃，但服务端仍会把它算完 |
| **代码位置** | `observability/storage_governance/layout.py::resolve_layout` · `walker.py::measure_tree` · `inspector.py::StorageGovernanceInspector` · `tests/observability/test_storage_governance.py`、`test_storage_layout.py` |

### BUG-HARNESS-2026-10-16-013 · 备份在复制或哈希途中失败、或进程被杀时，临时备份镜像及其 `-journal` / `-wal` 永远留在备份目录里，保留份数不会回收它们；镜像在复制后消失时，校验会新建一个空库，`create_backup` 把它当作成功发布出一个 0 字节的备份

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-16（核对存储占用由哪些文件构成时通读 `SQLiteBackupManager.create_backup`：临时镜像 `.tmp-<毫秒时间戳>.sqlite` 只在 `quick_check` 失败的一个分支里删除；随后在改动前的源码（`caa08dcfb^`）上，用临时目录里的合成库跑通下面三个场景） |
| **修复时间** | 2026-10-16（`caa08dcfb`） |
| **症状** | ① 复制完成后写入失败（用「计算哈希时抛 `OSError: disk full`」模拟）：`snapshots/` 里留下 `.tmp-….sqlite` 与 `.tmp-….sqlite-journal`；② 备份进程被杀后留下镜像与 `-wal`（用一个闲置 10 分钟的 `.tmp-` 文件模拟）：之后连续成功备份 5 次（保留 3 份），两个孤儿文件仍在，目录里是 2 个孤儿加 3 份备份，空间不会自己回来；每次失败或被杀最多留下一份数据库大小的文件（按复制方式推断，没有在真实库上量过）；③ 镜像在复制结束后消失（用「复制连接关闭时删掉镜像」模拟）：校验时 `sqlite3.connect` 对不存在的路径会新建数据库，`quick_check` 答 ok，`create_backup` 返回成功并发布 `backup-*.sqlite`，大小 0 字节；③ 在改动前没有已知的触发者（没有任何代码会删这个镜像），是为新增的清扫配套补上的保险 |
| **关联产品** | myrm-agent-harness `infra/sqlite_backup_models.py`、`infra/sqlite_backup.py`；调用方不用改：`create_backup()` 的签名与返回值不变，只多一种失败（镜像缺失或为空时抛 `RuntimeError`）；server 里的四处调用在 `app/lifecycle/schedulers.py`、`app/server/lifespan.py`、`app/database/connection.py`、`app/services/repair/sqlite_repair.py`；不改提示词、消息顺序与工具 schema |
| **根因** | ① 清理只写在 `quick_check` 失败这一个分支里，复制、哈希与发布都不在保护内，`KeyboardInterrupt` 一类的 `BaseException` 更不会被处理；② 没有任何位置回收被杀进程留下的文件，保留份数的修剪只认 `backup-*`；③ `sqlite3.connect` 对不存在的路径会新建数据库，校验函数因此对一个已消失的镜像也答 ok |
| **修复** | `infra/sqlite_backup_models.py` 新增三件：`_discard_on_failure`（上下文管理器，块内出现任何异常，包括 `KeyboardInterrupt`，都先删镜像及 `-journal` / `-wal` / `-shm`，再原样抛出）；`_require_backup_image`（镜像不存在或为空时抛 `RuntimeError`，且不创建文件）；`_sweep_stale_tmp_backups`（每次备份开始前清扫快照目录里 `.tmp-` 开头、闲置超过 5 分钟的文件，不跟随符号链接、不碰 `backup-*`，目录不存在或个别文件删不掉都不影响本次备份）；`create_backup` 把复制、校验、哈希与发布整段放进 `_discard_on_failure`，复制之后先过 `_require_backup_image` 再校验 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | ① 清扫用修改时间判断是否被遗弃：正在复制的镜像一直被写入，所以只清闲置 5 分钟以上的；并且只认 `.tmp-` 前缀，不从名字推断 `backup-*` 是孤儿（各有一例用例）；② 复现脚本第一版在校验函数里删镜像，这发生在 `_require_backup_image` 之后，守卫看不到，改动后的代码也发布了 0 字节备份，看上去像没修好；改成在复制连接关闭时删镜像后，改动前发布 0 字节、改动后拒绝，才与守卫所在的位置一致；③ 变异检查里「清扫跟随符号链接」第一版同时改了 `stat` 与 `is_file`，这个变异存活了；拆成两个后，只让 `is_file` 跟随的变异被杀死（链接会被当成文件删掉），只让 `stat` 跟随的变异存活但与原行为等价（`is_file(follow_symlinks=False)` 对链接恒为假，链接从不会被删） |
| **回归** | `tests/infra/test_sqlite_backup_tmp_cleanup.py` 15 例通过；`tests/infra` 整目录 354 例通过（harness `dc7937b41`）；对 `sqlite_backup_models.py` 做 7 个有观察效果的变异（失败后不删镜像、守卫放行缺失或空镜像、清扫什么也不删、清扫不看闲置时间、清扫碰非 `.tmp-` 名字、只让 `is_file` 跟随链接、只在 `Exception` 时清理），各使 5、2、2、2、1、1、2 例失败，恢复后 15 例通过；同一份复现脚本（放在 /tmp，没有入库）在改动前后的源码上各跑一遍：① 改动前留下 2 个文件，改动后 0 个；② 5 次备份之后，改动前 2 个孤儿仍在，改动后只剩 3 份备份；③ 改动前发布 0 字节备份，改动后拒绝并抛出 `Backup image .tmp-… is missing or empty after the copy`，目录为空；ruff、ruff format、mypy（strict）对触及的源文件与测试文件无问题 |
| **局限** | ① 清扫没有跨进程锁：同一目录里两个备份并行、且前一个的校验阶段（只读镜像，不更新修改时间）超过 5 分钟时，后一个的清扫会删掉前一个的镜像，前一个在计算校验和或发布时抛 `FileNotFoundError`，这次备份失败（不会发布空库，也没有重试）；这个窗口按代码推断，没有复现，也没有量过真实库的校验耗时；② 没有查看本机真实备份目录里是否已有 `.tmp-` 孤儿（不用真实数据做开发测试），已有的会在下一次备份时（闲置超过 5 分钟）被清扫；③ 改动在本地源码（版本 `0.1.0rc6`），没有 push，也没有发布：服务端仓固定的依赖是 `myrm-agent-harness==0.1.0rc5`，按锁文件安装的环境仍是旧行为，先发布 harness，再 `./myrm harness sync-lock`；④ 「内容没变就不再备份」（路线图 topic_05 #53 ⑥ 后半）没有做 |
| **代码位置** | `infra/sqlite_backup_models.py::_discard_tmp_backup`、`_discard_on_failure`、`_require_backup_image`、`_sweep_stale_tmp_backups` · `infra/sqlite_backup.py::SQLiteBackupManager.create_backup` · `tests/infra/test_sqlite_backup_tmp_cleanup.py` |

### BUG-HARNESS-2026-10-16-012 · 用户接管浏览器后交还时，刷新快照的调用带了一个不存在的参数，每次都抛 TypeError 并被吞成一条警告，快照与差异基线停在接管前；同批删掉浏览器里只写不读的运行遥测与无人调用的动作看门狗

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-16（删除浏览器运行遥测时核对 `browser_session.py` 的调用关系，mypy 报 `Unexpected keyword argument "force" for "snapshot"`；用 `inspect.signature(BrowserSession.snapshot).bind(..., force=True)` 复现 `TypeError: got an unexpected keyword argument 'force'`） |
| **修复时间** | 2026-10-16 |
| **症状** | ① 用户在界面交还浏览器控制权时，server 调 `resume_from_takeover`（`task_space_service.py:127`），方法里的 `self.snapshot(force=True)` 每次都抛 `TypeError`，被 `except Exception` 吞成一条 `Failed to refresh snapshot after takeover resume` 警告，元素引用与差异基线没有刷新到用户留下的页面；② 两个测试（`test_browser_session_takeover.py`、`test_takeover_hard_stop.py`）把 `snapshot` 换成 `AsyncMock` 后断言 `assert_awaited_once_with(force=True)`，`AsyncMock` 接受任何关键字，这个错误被断言成了「正确」；③ 同批清理：`BrowserRunTelemetry`（运行时长与传输字节遥测）只有写入方，没有读取方：`NetworkLogger` 每个响应结束时多算一次字节数再写入，`attach_to_context` 没有调用方；`check_action_watchdog`、`get_observability_stats` 没有调用方（产品仓台账已有同样的记录）；`BrowserSession.stats["telemetry"]` 与 `runtime_telemetry` 没有读取方 |
| **关联产品** | myrm-agent-harness `toolkits/browser/`（`observability.py`、`session/{browser_session,browser_session_lifecycle_mixin,network_logger}.py`）；server 与前端未改（`resume_from_takeover` 的签名不变）；不改提示词、消息顺序与工具 schema，提示缓存前缀不受影响 |
| **根因** | ① 调用处写的是 `snapshot` 当前签名里没有的参数 `force`，而 `snapshot()` 的签名里只有 `diff`、`update_baseline` 等；② 唯一的覆盖用 `AsyncMock` 替掉了被调用的方法，签名检查被一并替掉；③ 遥测按「写入方、读取方、展示」三段设计，只做了写入这一段 |
| **修复** | `resume_from_takeover` 改为 `snapshot(diff=False)`：返回值本来就被丢弃，调用只为刷新元素引用与差异基线，不必再算一次与接管前页面的差异（`browser_session.py:386`）；两个测试改断言 `diff=False`，`test_browser_session_takeover.py` 再用 `inspect.signature(BrowserSession.snapshot).bind` 对真实签名核对所用关键字；删除 `BrowserRunTelemetry`、`BrowserObservability.telemetry` 与构造参数、`attach_to_context`、`check_action_watchdog`、`get_observability_stats`、`NetworkLogger` 的 `telemetry` 参数与每个响应的字节计算、`BrowserSession.runtime_telemetry` 与 `stats["telemetry"]`；`BrowserObservability` 保留录像配置、`get_context_kwargs`、`notify_progress`、`mark_task_status`、`cleanup_recording`、`recording_enabled` 与 `video_path` |
| **反复次数** | 第 1 次发现 |
| **踩坑** | ① 删除遥测时 ruff 报 `SIM102`：关闭会话处原来是 `if self._observability:` 里套 `if self._observability.recording_enabled:`，去掉外层的 `mark_closed()` 后两层条件合并为一个；② 被删的 `test_search_quota_and_browser_telemetry.py` 里还有三个搜索指标用例（`WebSearchMetrics` 的供应商额度计数，不属于遥测），先搬到新文件 `tests/toolkits/web_search/test_web_search_metrics.py` 再删旧文件；③ `BUG-HARNESS-2026-10-14-016` 的回归一栏提到的 `test_observability_bandwidth_integration.py` 随被测的字节统计一起删除（它测的就是被删的 `BrowserRunTelemetry`） |
| **回归** | `tests/toolkits/browser/session/test_browser_session_takeover.py` 与 `test_takeover_hard_stop.py` 共 9 例通过；`tests/toolkits/browser` 与 `tests/toolkits/web_search` 整目录 3576 例通过、1 例跳过（另有 350 例按项目默认标记不收集）；变异验证：把调用改回 `force=True`，两个断言 `diff=False` 的用例失败（2 失败、7 通过），换回后 9 例全过；`inspect.signature(BrowserSession.snapshot).bind(force=True)` 抛 `TypeError` |
| **局限** | ① 没有在真实浏览器里验证接管交还后第一次快照的内容，下一次 `snapshot()` 此前是否比对了接管前的旧基线只是按代码推断；② 被删的遥测没有保留任何一段，将来要做运行成本或带宽展示，读取侧与写入侧都要从头设计；③ `browser_session.py` 里还有一个与本条无关的既有 mypy 错误（`PageAnalyzer` 收到 `patchright` 的 `Page`，声明的是 `playwright` 的 `Page`），没有动 |
| **代码位置** | `toolkits/browser/session/browser_session.py::resume_from_takeover`（`:386`）· `toolkits/browser/observability.py::BrowserObservability` · `toolkits/browser/session/network_logger.py::NetworkLogger.__init__` · `tests/toolkits/browser/session/test_browser_session_takeover.py`、`test_takeover_hard_stop.py`、`tests/toolkits/web_search/test_web_search_metrics.py` |

### BUG-HARNESS-2026-10-16-011 · 搜索链上头部供应商超时、5xx、连不上时不会转移到备用供应商，整次搜索直接失败；查询词里带 quota、429 一类词的搜索，一次超时就能把健康的头部供应商标成额度耗尽或限流

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-16（复核 topic_02 #141：用真实 `search_provider_chain`、真实 `WebSearcher` 重试循环与真实分类函数，只假掉 `LiteLLMSearch.search` 这一层网络边界的模拟脚本复现；roadmap 里 16 种失败形状的实测同样是供应商自身故障的 8 种形状全部停链） |
| **修复时间** | 2026-10-16 |
| **症状** | ① 头部供应商超时、HTTP 500/502/503/504/408、连不上、DNS 失败时，链记「failed with retryable error, not advancing chain」后结束，备用供应商一次都不调用，整次搜索失败；而 400/401/403/404 与配额类失败反而会转移；② `SearchAPIError.__str__` 在文字里附带用户的查询词，分类函数对整段文字做子串匹配，查询「how to raise aws service quota」「http 429 meaning」遇到一次超时就被判为额度耗尽或限流，头部被跳过 1 小时或 5 秒；③ 同一处还有两处指标重复计数：一次切换在失败分支和成功分支各记一次 `chain_hop_count`，一次配额失败在重试循环（`web_searcher.py:350-356`）和链里各记一次 `provider_attempts` 与 `provider_quota_exceeded` |
| **关联产品** | myrm-agent-harness `toolkits/web_search/providers/chain.py`、`toolkits/web_search/core/exceptions.py`；server 与前端未改；不改提示词、消息顺序与工具 schema（`format_for_llm` 的诊断照旧给模型看查询词），提示缓存前缀不受影响 |
| **根因** | ① `_should_stop_chain` 把「可重试」当作停链条件，而可重试的恰恰是供应商自身的故障（超时、连接、5xx）；② 分类函数的输入是 `str(exc)`，`SearchAPIError.__str__` 追加了 `query=<用户查询>`；③ 切换成功后与切换前的失败各记一次跳数，供应商指标在重试循环与链内各记一次 |
| **修复** | 删除 `_should_stop_chain` 与停链分支：任何一跳失败都在链的 45 秒预算内转移到下一家，只有配额与限流失败额外进冷却（`chain.py:131` 起的 `search_provider_chain`）；`SearchAPIError.__str__` 不再包含查询词，状态码与错误码仍在（`exceptions.py:53`）；删除成功分支的重复跳数记录与链内重复的 `record_provider_search`；转移改在循环入口、真正尝试下一家时记一次（`chain.py:183-189`），某一跳的失败耗尽整链预算、没有下一家可试时不记转移 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | ① 最初的设计是给三个分类函数各加一层「只读消息」的辅助函数，读码后发现根因就是 `__str__` 本身，把查询词从那里拿掉改动更小，还覆盖了 volcengine 适配器直接抛 `SearchAPIError`、被重试循环当作内部异常再分类的那条路径；② 旧用例把 `chain_hop_count` 写成 `>= 1`，正好遮住了重复计数，新用例改成精确断言；③ `default_quota_tracker` 是进程级单例，同类用例会互相影响，`test_fallback.py` 的链用例类补了复位；④ 整目录回归里 `test_chunking_concurrency_benchmark.py` 与 `test_concurrent_safety.py::test_stress_test_1000_concurrent` 的耗时断言失败（0.86x、615 毫秒对 500 毫秒），当时机器负载约 38，它们不经过搜索链，与本条无关 |
| **回归** | `tests/toolkits/web_search` 下 `test_chain_quota_hop.py`、`test_fallback.py`、`test_web_search_error_handling.py`、`test_volcengine_doubao_search.py` 共 97 例通过（含事后补充的矩阵与预算用例）。新增或改写：查询词不被当作配额信号 6 例、供应商回复里的耗尽与限流仍被识别 1 例、十种宕机形状（500、502、503、504、408、请求超时、连不上、裸超时、裸连接被拒、DNS 失败）各自转移且头部保持健康 10 例、八种请求或账号类形状（400、401、402、403、404、429、LiteLLM 包装的套餐上限、普通 RuntimeError）各自转移且只计一次转移 8 例、整链预算在某一跳内耗尽时不记转移 1 例、全员宕机时每家各试一次后失败 1 例、含 quota 与 429 字样的查询在宕机后不拉黑头部且下一次搜索仍先走头部 3 例、配额失败仍进冷却 1 例，以及经真实重试循环的转移（含头部自身 3 次重试）3 例与链用例 2 例；`test_primary_quota_exceeded_chain_succeeds` 改为精确断言一次切换、一次尝试、一次配额事件。变异验证：把 `chain.py` 与 `exceptions.py` 换回修复前的版本，这四个文件 97 例里 34 例失败、63 例仍通过，换回后 97 例全过 |
| **局限** | ① 没有用真实供应商验证，所有失败形状都是构造的；② 头部供应商挂起时，本条落地时仍会耗尽 45 秒链预算、备用来不及试，已由 `BUG-HARNESS-2026-10-17-002` 修复；③ 宕机期间每次搜索都要先付头部的重试时间（默认 2 次重试，退避约 1.5 秒，加上调用本身的耗时），没有宕机冷却；④ 供应商自己的回复里含 quota、rate limit 等词时仍按全文匹配判为配额或限流，至多让该供应商被跳过 1 小时；查询词若出现在供应商自己的错误回显里（例如 400 invalid query）仍可能命中标记，没有逐家验证供应商是否回显；⑤ 只配置一家搜索服务的用户不受影响，多家用户的占比没有数据 |
| **代码位置** | `toolkits/web_search/providers/chain.py::search_provider_chain`（`:129`）· `toolkits/web_search/core/exceptions.py::SearchAPIError.__str__`（`:53`）· `tests/toolkits/web_search/test_chain_quota_hop.py`、`test_fallback.py`、`test_web_search_error_handling.py` |

### BUG-HARNESS-2026-10-16-010 · 搜索供应商链里被标为「额度耗尽」的供应商在进程重启前一直被跳过：到期时间只在限流状态里生效，耗尽状态没有到期也没有任何复位入口；一次回显了查询词的错误就能让健康的头部供应商整个进程生命周期不再被调用

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED（到期恢复；失败分类收紧与更新密钥时立即复位未做） |
| **发现时间** | 2026-10-16（复核 topic_02 #141 ④：用真实 `ProviderQuotaTracker` 与单调时钟实测，把时钟与 `depleted_at` 推进 40 天后 `get_status` 仍返回 `DEPLETED`；roadmap 里 S2 的复现是头部对含「quota」的查询返回 `HTTP 400: invalid query` 后被标为耗尽，供应商恢复后头部被调用 0 次） |
| **修复时间** | 2026-10-16 |
| **症状** | ① `mark_depleted` 之后 `get_status` 永远返回 `DEPLETED`（旧 `chain.py:75-88` 的耗尽分支不看时间），额度重置或充值之后该供应商也不会再被调用，直到进程重启；② 回显查询词的错误文本里出现 `quota` 一类词会走同一个永久标记，健康的头部供应商因此被一直跳过；③ 在 `myrm-agent-harness/src` 与 `myrm-agent/myrm-agent-server/app` 下，`reset_provider`、`reset_all`、`get_all_states` 除 `chain.py` 本身外没有调用方，没有任何入口能复位 |
| **关联产品** | myrm-agent-harness `toolkits/web_search/providers/chain.py`；server 与前端未改，不改提示词、消息顺序与工具 schema，提示缓存前缀不受影响 |
| **根因** | `ProviderQuotaState` 把限流的到期时刻放在 `rate_limited_until`，耗尽只记一个没有读者的墙钟 `depleted_at`，`get_status` 的耗尽分支直接返回；耗尽靠错误文本里的子串判定，误判与真耗尽走同一个永久标记 |
| **修复** | 状态机只保留一个单调时钟的 `unavailable_until`：限流默认 5 秒、耗尽默认 1 小时（`_DEFAULT_DEPLETED_COOLDOWN_SECONDS`，`mark_depleted(..., cooldown_seconds=)` 可调），到期时删除状态，下一次真实搜索担任探测，仍耗尽则被再次标记，没有另写探测路径；删除零调用方的 `get_all_states()` 与无读者的 `depleted_at`；`ProviderQuotaStatus` 改为 `StrEnum`。1 小时是取舍：额度重置发生在带外（计费周期、充值），追踪器观察不到，一小时在「误判的代价」（跳过一小时）与「探测的成本」（每小时多一次真实搜索）之间折中，没有按供应商实测过 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | ① roadmap 草案写的是「到期后半开探测一次」，读码后发现状态一删除下一次调用天然就是探测，不需要另写一条探测路径；② 被删除的 `get_all_states()` 在 topic_02 #141 ④ 里被规划接到设置页的健康显示，零调用方的事实让这条依赖落空，已在该条下注明；③ 用例用可拨动的假时钟替换 `chain.py` 里的 `time`，直接断言到期，不 sleep；写变异验证时，变异体若用真实的 `time` 会让限流用例也失败，那是变异体的问题，不是被测行为 |
| **回归** | `tests/toolkits/web_search/test_chain_quota_hop.py` 11 例通过，其中新增 3 例：`test_depleted_provider_recovers_after_cooldown`（到期前一秒仍耗尽、到期后恢复、再次耗尽会再次标记）、`test_rate_limited_provider_recovers_after_cooldown`、`test_chain_probes_depleted_primary_again_after_cooldown`（链上头部耗尽时由备用供应商出结果，一小时后头部被再次调用）。变异验证：在进程内把 `get_status` 换回「耗尽不看时间」后，`test_depleted_provider_recovers_after_cooldown` 与 `test_chain_probes_depleted_primary_again_after_cooldown` 失败，`test_rate_limited_provider_recovers_after_cooldown` 照常通过（限流语义没变）；ruff、ruff format、mypy 对该文件通过 |
| **局限** | ① 没有在真实供应商上验证到期后的探测与再次标记；② 耗尽到期固定为 1 小时，「月度额度」与「余额不足」两类没有区分；③ 回显查询词的误判本身没有修（topic_02 #141 ⑤ 的锚定分类），后果由永久缩短为 1 小时；④ 用户在设置里更新密钥或端点时不会立即复位，要等到期；⑤ 没有设置页的健康显示与「立即重试」；⑥ `tests/toolkits/web_search` 整目录里有一条并发压力用例（1000 并发、500 毫秒内完成）在机器负载高时偶发失败，单独重跑通过，与本条无关 |
| **代码位置** | `toolkits/web_search/providers/chain.py`：`_DEFAULT_DEPLETED_COOLDOWN_SECONDS`（`:50`）、`ProviderQuotaTracker.get_status`（`:77`）、`mark_rate_limited`（`:88`）、`mark_depleted`（`:102`）· `tests/toolkits/web_search/test_chain_quota_hop.py` |

### BUG-HARNESS-2026-10-16-007 · 同一条消息里两个委派同时停在审批上时，界面只收到第一个中断的卡片；两个中断同时待决时任何答复都被 LangGraph 拒绝，一张已被处理过的旧卡再被点击时答复会落到用户没看到的下一个审批上；同批删掉子代理检查点里无人调用的「按文件快照恢复」半边

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-16（#436 复审：用生产图构建器 `langchain.agents.create_agent`（langgraph 1.2.14）核对并行中断的 resume 语义，不靠读码推断；hermes、codex、openclaw、opencode、deepseek-harness、Claude Agent SDK 的审批答复读源码核对，全部按各自的请求 id 寻址，没有一家按「当前待决的那个」） |
| **修复时间** | 2026-10-16 |
| **症状** | ① 一个 `__interrupt__` 分片里有多个中断时，分发器只取第一个发出事件，另一个委派的审批卡永远不出现；② 两个中断同时待决时，不带 id 的 resume 被 LangGraph 以 `RuntimeError: When there are multiple pending interrupts, you must specify the interrupt id when resuming` 拒绝（`langgraph/pregel/_loop.py:962`），用户答复的那一张也答不成；③ 只剩一个中断待决时，不带 id 的答复总落在「此刻待决的那个」上，所以一张已被超时计时器或另一台设备处理过的旧卡被点击后，答复会落到用户没看到的下一个审批上 |
| **关联产品** | myrm-agent-harness `agent/streaming/{interrupt_events,stream_dispatcher}.py`、`agent/_internals/{resume_addressing,agent_runtime}.py`；前端与服务端见 `myrm-agent/BUGFIX_LOG.md` 的 `BUG-AGENT-2026-10-16-019` |
| **根因** | ① 旧分发器取 `interrupts[0]`（读码结论）；② resume 咽喉把前端的载荷原样交给 `Command(resume=value)`：LangGraph 对纯值的解释是「答复当前待决的中断」，待决数大于 1 时直接抛错；只有 `Command(resume={interrupt_id: value})` 才按 id 寻址，且字典的每个键都必须是 32 位十六进制才会被当作 id（`langgraph/pregel/_utils.py:219`），未知或已处理的 id 被忽略；③ 流事件与卡片都没有携带 LangGraph 分配的中断 id（它只取决于挂起它的任务，重放时不变） |
| **修复** | 新增 `agent/streaming/interrupt_events.py`：一个分片里的每个中断各发一个流事件，顶层带 `interruptId`（`stream_dispatcher.py:101` 调用，旧的内联分支删掉）；新增 `agent/_internals/resume_addressing.py`：`address_resume` 是纯规则，`address_resume_to_pending` 读线程当前待决的中断后应用，由 `agent_runtime.py:576-578` 的 resume 咽喉调用。规则：载荷带 `interruptId` → 改写为 `Command(resume={id: 去掉该键的载荷})`（该 id 已不待决则 LangGraph 忽略，旧卡的答复什么也不改变，运行回到真正待决的中断上暂停）；不带 id 且至多一个待决 → 原样，IM、语音、定时器等既有调用方行为不变；不带 id 且多个待决 → 只有全局驳回（`{"decision": "reject"}`，无 `decisions`，即超时计时器的驳回）广播给全部待决中断，其余原样交给 LangGraph、继续被拒（失败关闭：批准不会被施加到用户没有单独答复的中断上）；待决中断读不出时原样放行。同批清理：`SubAgentResult.result` 实际是 `str \| dict[str, object]`（字典是隔离合并元数据，文本在 `text` 下），新增 `agent/sub_agents/result_output.py` 的 `SubAgentOutput` 与 `answer_text` 作为读取答案文本的唯一入口，council、verifier、server 唤醒处理改用它（chain 的改动见局限 ⑩），并清掉 `_orchestrator_verification.py` 的 3 条 mypy；删除无生产调用方的 `SubagentManager.resume_from_checkpoint`、`SubagentCheckpointManager.resume_from_checkpoint` / `delete_checkpoint`、`restore_subagent_state`、`BaseAgent.restore_checkpoint_state` 与对应测试和文档（中断任务由业务层按保存的任务描述重新发起，不按检查点续跑） |
| **反复次数** | 第 1 次发现 |
| **踩坑** | ① LangGraph 只在字典的全部键都是 32 位十六进制时才把它当作「按 id 作答」，所以端到端用例必须用真实图产生的 id，写成 `"abc"` 的假 id 只能测纯改写规则；② 部分作答后图会重新挂起，仍待决的中断会作为新分片再发一遍，客户端必须按 id 去重，否则同一张卡出现两次；③ 一次大回归里本条的 6 个用例断言「未被寻址」失败，同一条命令随后重跑全部通过；失败那一轮（约 20:16–20:20）开始后，被测的三个模块文件又被改写（修改时间 20:17，与本条自己的编辑时段重叠），推断那一轮加载的是改写前的版本；这是按时间线的推断，没有把旧版本复原来验证。长回归期间被测文件还在被改时，以同一命令重跑的结果为准，不要并行跑改文件与跑回归 |
| **回归** | `tests/agent/_internals/test_resume_addressing.py` 9 例（生产图构建器上两个并行 `interrupt()`：按各自 id 作答、已处理的 id 什么也不改变、全局驳回结清全部待决、未寻址的批准在多个待决时仍被拒、单个待决时未寻址原样、已结束线程上的 id 无变化、id 从答复里剥掉、`Command` 其他字段保留、线程读不出时原样）、`tests/agent/streaming/test_interrupt_events.py` 7 例（各类中断的事件类型与值、空动作列表、无可用 id 时不带键、非字典值跳过、事件 id 就是 LangGraph 用来恢复的那个 id）、`tests/agent/test_base_agent_resume_addressing.py` 2 例（经真实 `BaseAgent` 咽喉：卡片带 id 且按 id 作答能继续运行；不在待决中的 id 不批准任何东西）、`tests/agent/streaming/test_stream_dispatcher.py` 新增 1 例（一个分片的每个中断各发一次、带各自 id）；对 `resume_addressing` / `interrupt_events` 手工注入 9 个变异，每一个都至少被其中一个用例杀掉；`tests/agent/{sub_agents,streaming,_internals,meta_tools,middlewares/approval}` 与 `test_base_agent_subagent_methods.py` 共 4750 通过、6 失败：3 个是他人未提交的 `SubagentConfig` 默认值改动（`concurrency_limit` 5→10）与 `tests/agent/sub_agents/test_config_loader.py` 里写死的 5 不符，3 个是 `tests/agent/meta_tools/skill_manage/test_skill_manage_lock.py` 的 `SkillManageInput` 要求 `operations` 而用例没传，均与本条无关；`tests/agent/sub_agents/test_spawn_trust_boundary.py`（他人未跟踪的文件，在 xdist 下会让进程崩溃）被排除。性能：每次 resume 多一次待决中断读取，实测中位数内存检查点 0.125 ms、SQLite 检查点 0.986 ms（本机） |
| **局限** | ① 没有用真实模型验证「同一条消息里并行委派」出现的频率，也没有在浏览器里同时看到两张卡并分别答复；② 旧卡（其中断已被别处处理）被点击后，答复被忽略、运行回到真正待决的中断上，界面上旧卡是否闪一下空助手消息没有验证；③ IM 的 `/approve` 与超时计时器的「允许」在多个待决中断下仍被拒（失败关闭），IM 里没有逐张卡的寻址；④ 服务端在进入 harness 之前就应用了目录授权（`apply_directory_resume_grant`），所以带授权的旧卡答复，授权会生效而答复本身被忽略（既有顺序，未改）；⑤ 抽屉里合成的审批卡没有中断 id，仍走无寻址的原路径；⑥ `SubagentCheckpointManager.save_checkpoint_for_task` 现在只有测试调用，`SubAgentResult.checkpoint_data` 只剩 `{"thread_id": task_id}`；⑦ 性能数字是本机基准，不代表线上；⑧ 那次一过性的失败只有时间线上的推断（见踩坑 ③），没有复原旧版本验证；同一命令重跑已通过；⑨ 澄清卡与计划确认卡的答复不回传中断 id（`resumePlanConfirmStream` 与澄清答复都只发普通值）：它们与别的中断同时待决时答复仍被 LangGraph 拒绝（失败关闭），先答完其余卡片、待决只剩一个时即可作答；⑩ `orchestrator.py` `run_chain` 里 `previous_result = answer_text(last_result.result)`（链式步骤把隔离合并的字典结果原样塞进下一步提示词的修复）与用例 `test_chain_hands_the_answer_text_of_an_isolated_step_to_the_next_step` 在工作区、未入库：该文件正被他人改写，入库会让它超过行数基线（930），等其改写提交后补 |
| **代码位置** | `agent/streaming/interrupt_events.py` · `agent/streaming/stream_dispatcher.py:101` · `agent/_internals/resume_addressing.py::address_resume/address_resume_to_pending` · `agent/_internals/agent_runtime.py:576-578` · `agent/sub_agents/result_output.py::answer_text` |

### BUG-HARNESS-2026-10-16-009 · 模型请求的超时设置在聊天补全与 Anthropic 两条线上没有任何作用：配置的 300 / 450 / 1800 秒一律被 litellm 换成缺省的 600 秒（本地端点配置的 1800 秒从未生效，官方主机的 300 秒也没生效），按超时失败的既有处理因此只在 600 秒处才触发；同一个字段旁边还有一个没人读的元组写法和一个没人读的重试次数字段

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-16（#140 的「文章阶段限流」追问里核对「超时是否真的会触发」：读 `ChatLiteLLM` 的参数装配与 litellm 源码，再用回环服务器的真实 socket 验证，不靠读码推断） |
| **修复时间** | 2026-10-16 |
| **症状** | ① `ChatLiteLLM.request_timeout`（官方主机 300 秒、本地端点 1800 秒、推理模型 450 与 600 秒的下限）原先以 `force_timeout` 交给 litellm（旧 `model.py:240`、`:270`）。litellm 的 `completion()` 只把 `force_timeout` 带进日志用的参数（`litellm/main.py:5187` 标着 deprecated，`:5520` 传给 `get_litellm_params`），聊天补全与 Anthropic 原生两条线不会把它用在 HTTP 客户端上；只有 Responses 线由 `wire/params.py` 把它换成 `timeout`。所以这两条线上配置值没有进入 HTTP 客户端（Anthropic 线同样经 `litellm.completion()`，`wire/anthropic_params.py:26-27` 只改模型名与提供方），读超时取 litellm 的聊天缺省：`CompletionTimeout.resolve` 按 `timeout`、`kwargs["timeout"]`、`kwargs["request_timeout"]`、已显式配置的全局值的顺序取第一个非空，全都没有时是 `COMPLETION_HTTP_FALLBACK_SECONDS` 的 600 秒（`litellm/litellm_core_utils/completion_timeout.py`、`litellm/constants.py:544`；对 litellm 1.103.3 实跑：`{"force_timeout": 300}` 得 600.0，`{"timeout": 300}` 得 300.0，什么都不给得 600.0；产品代码里没有设置 litellm 的全局 `request_timeout`）。`constants.py:541` 的 6000 秒 `DEFAULT_REQUEST_TIMEOUT_SECONDS` 是 Router、responses 等其它入口用的哨兵，聊天补全不用它。结果：官方主机配置的 300 秒实际是 600 秒（比配置宽），本地端点配置的 1800 秒实际也是 600 秒（比配置严，生成超过 10 分钟的本地模型在 600 秒被判超时），供应商接受连接后不回话（网关挂起、上游黑洞）的调用要等满 600 秒才失败，只有按超时失败才会进入的既有处理（流恢复的重试 `agent/streaming/recovery/stream_recovery.py:514`、`FailoverReason.TIMEOUT` 的备用模型切换 `toolkits/llms/errors/classifier.py:88`、wiki 的瞬时类自动重试 `toolkits/wiki/pipeline/resilience/failure_policy.py:34`）因此也只在 600 秒处才触发；流式的 `first_event_timeout`、`inter_chunk_timeout` 只在拿到 HTTP 200 之后才计时，管不到这段沉默。对旧代码做过一次回环黑洞服务的探针，调用没有返回、被我手动中断，没有量出确切时长，600 秒这个值来自读码与上面的实跑，没有在黑洞服务上实测满 10 分钟。② `request_timeout` 的类型写着 `float \| tuple[float, float] \| None`，元组写法没有任何地方读（旧 `model.py:147`）；`max_retries: int = 1` 既没有读也没有写（旧 `:168`），读者会误以为请求重试由它控制 |
| **关联产品** | myrm-agent-harness `toolkits/llms/adapters/chat_model/model.py`、`adapters/wire/params.py`；server 与前端未改，不改提示词、消息顺序、工具 schema，提示缓存前缀不受影响 |
| **根因** | 参数名选错，而保护它的测试断言的是「传给 litellm 的参数名」，没有任何一个测试让真实 socket 沉默，所以名字与效果脱节（topic_07 #283 的实测已显示：对 `force_timeout` 加 1 的变异，2,376 例无密钥用例 0 例检出） |
| **修复** | `request_timeout` 以 `timeout` 交给 litellm（`model.py:241`）：这是 HTTP 读超时，流式下只要还在收到数据就不会被切，沉默的供应商按 `ErrorKind.TIMEOUT` 失败；`wire/params.py` 里只有 Responses 线才有的换名删除，三条线用同一个键；显式的 `model_kwargs["timeout"]` 在三条线上都覆盖 `request_timeout`；类型收窄为 `float \| None`；删除没人读的 `max_retries` 字段。`chat_model/_ARCH.md` 的 `model.py` 一行同步 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | ① 起初想用已有的 `first_event_timeout` 一类开关补，读码发现它们只在 HTTP 200 之后才计时，覆盖不到前置沉默；② 对旧代码的黑洞探针挂住了终端，之后所有用例都带 `asyncio.wait_for` 的 15 秒守卫；③ 集成用例 `test_remote_timeout_default` 期望 300，在配了本机推理模型环境变量时得到 450（推理模型的下限），与本条无关，但属于既有的环境依赖，改成显式构造官方主机的模型，不再随环境漂移 |
| **回归** | 新增 `tests/toolkits/llms/adapters/test_request_timeout_effect.py` 11 例，用回环 TCP 服务器（真实 socket，不是桩），`request_timeout` 取 0.8 秒：三条线 × 流式 / 非流式的「接受连接后不回话」都在 10 秒内失败且被分类为 `TIMEOUT`，同步 `invoke` 的三条线各一例同样如此；一个比超时晚到的响应按 `TIMEOUT` 失败；一个每 0.25 秒出一块、总长 1.5 秒的慢流不被切断并读出 `xxxxxx`。在测试进程里把键名改回 `force_timeout`（保留新的 `params.py`）的变异下，11 例中 10 例变红（没红的是慢流那一例）；注意这不是旧代码的真实状态：旧代码上 Responses 线本来就生效，真正坏的是聊天补全与 Anthropic 两条线。另有三个测试文件按新键名改写（`test_reasoning_timeout_integration.py`、`wire/test_params.py`、`tests/integration/test_local_endpoint_timeout_integration.py`），`test_chat_model_stream_flows.py` 删除对已删字段的赋值。全量：`tests/toolkits/llms` 2654 例通过（1 例集成用例按默认标记被排除）；ruff、mypy 对触及文件无错误，`validate_arch_inventory` 对 `toolkits/llms` 通过 |
| **实测** | 回环服务器、`request_timeout=0.8`，单跑耗时：聊天补全非流式 4.05 秒、流式 3.88 秒，Responses 0.83 与 0.82 秒，Anthropic 0.94 与 0.82 秒；晚到的响应 3.62 秒；慢流 1.53 秒读完；同步 `invoke`：聊天补全 3.9 秒、Anthropic 1.0 秒，同样被分类为 `TIMEOUT`。聊天补全线比超时长是因为 openai SDK 在超时后再试两次：探针数到服务器收到 3 个连接（4.0 秒），Responses 与 Anthropic 各 1 个连接。没有验证：真实供应商（只验证了 litellm 加 SDK 在 HTTP 层的真实行为） |
| **局限** | ① 聊天补全线上超时后 SDK 会再试两次，按默认 300 秒，一个沉默的供应商最长约 3 倍的超时加退避才失败（0.8 秒的探针对应 4.0 秒与 3 个连接；乘到 300 秒是推算，没有实测 15 分钟）；本条没有改 SDK 的重试次数，那是另一个取舍；② 默认值（300 / 450 / 1800 秒）本身没有重新评估；③ 依赖当前 litellm 版本把 `timeout` 传给底层 SDK 客户端，升级后的漂移由这 11 例报警；④ 流式在 HTTP 200 之后的沉默仍由 `first_event_timeout` / `inter_chunk_timeout` 管，本条没动；⑤ topic_07 #283 的实测数字里的 `force_timeout` 是当时的键名，历史数据不改，条目里已加注；⑥ 窗口的方向不一：官方主机 600 → 300 秒、450 档推理模型 600 → 450 秒（收窄），本地端点 600 → 1800 秒（放宽）。wiki 编译的模型是非流式的（`myrm-agent-server/app/services/agent/llm_access.py:41`），读超时就是整次生成的上限，生成时间超过窗口的合法调用现在会更早按 `timeout` 失败并进入瞬时类自动重试；没有生产数据说明这样的调用是否存在，所以默认值没动。竞品对照（官方文档）：Claude Code 为非流式超时的重发单独设了上限，文档写明超时的生成每次重发都会再次超时（code.claude.com/docs/en/errors），并在 v2.1.101 修过一次把慢后端误杀的固定 5 分钟超时 |
| **代码位置** | `toolkits/llms/adapters/chat_model/model.py`：`request_timeout`（`:149`）、`_default_params` 里的 `"timeout"`（`:241`）· `adapters/wire/params.py`（Responses 线的换名已删）· `tests/toolkits/llms/adapters/test_request_timeout_effect.py` |

### BUG-HARNESS-2026-10-16-008 · wiki 编译里某个概念的文章没写成（限流、超时、模型拒绝）时，对应原文照样被标成「已完成」：队列里看不到失败、不会重试，增量编译也当它没变过；另外自动重试每次只看最早的 9 条失败，更早的永久失败多了，限流的原文永远轮不到

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED（C、H 两处同一条） |
| **发现时间** | 2026-10-16（#140 `-005` 收尾后追问「文章阶段遇到限流会怎样」：用桩模型与真实队列实测，不靠读码推断；自动重试的窗口问题是核对重试路径时读码发现，再用红灯用例复现） |
| **修复时间** | 2026-10-16 |
| **症状** | ① 概念的文章生成抛任何异常，旧 `compiler.py:639-641` 都是 `except Exception` 后 `return "blocked"`，只让 `articles_blocked` 加 1，该概念的每个来源照常被结算为 `completed`。实测（桩模型、3 个原文，`beta` 概念的文章请求返回 429，worker 与 `compile_all` 各一遍）：旧代码三行都是 `completed`、`error_kind` 为空、`retry_count 0`；队列面板的失败计数、`/queue/retry`、自动重试都看不到它，元数据已记下这 3 个原文的哈希，增量编译也不会再排它。`articles_blocked` 在 harness、server `app/`、前端 `src/` 里只有三处出现：agent 工具的返回文字（`wiki_agent_tools.py:475`）、`core/types.py:64`、`compiler.py:396`，没有界面或接口读它。② 自动重试只在没有待处理条目时取 `get_transient_retryable_items(max_retries=3, limit=3)`（`compiler.py:314`），旧实现先 `ORDER BY updated_at ASC LIMIT limit*3`（9 行）再在 Python 里丢掉永久类，所以有 9 条以上更早失败的永久失败（如 `format_error`）时，之后的限流、过载、超时失败永远选不到。红灯：12 条永久失败加 2 条限流，旧实现返回 `[]` |
| **关联产品** | myrm-agent-harness `toolkits/wiki/pipeline/`：新增 `articles.py`，改 `batch_settle.py`、`compiler.py`、`queue.py`、`resilience/`；server 与前端未改：失败行走既有路由 `/queue/retry`（只重置瞬时类）、`/queue/retry-all`（重置全部失败并恢复 worker）、`/queue/resume-circuit`（`myrm-agent-server/app/api/wiki/router.py:1716`、`:1729`、`:1743`），队列面板已有失败计数与错误分类标签（`WikiQueuePanel.tsx:39-56`） |
| **根因** | ① 文章失败只进一个计数，没有带上概念与来源，批次末尾无从知道该让哪些原文失败；`-005` 之后的 `settle_extracted` 也只区分「未改」「被改」两种，失败的原文只能被结算为完成。② 自动重试的 `LIMIT` 发生在类别过滤之前（读码结论，红灯复现） |
| **修复** | ① 文章阶段迁出到 `pipeline/articles.py`（`compiler.py` 837 → 700 行，`file_line_baseline.txt` 同步收紧）：每个失败的概念记一条 `ConceptFailure`（概念名、它的全部来源文件、`resolve_llm_failure` 给出的错误分类与退避）；被取消的文章任务同样记为失败；embed 窗口违规不记为失败（文章已落盘，缺的只是向量索引，仍由 compile 暂停报告，原文照常完成，与 `-005` 一致）；等待审批的暂存稿算写成。② `batch_settle.py::settle_extracted` 新增第四个参数：批次期间被改过的原文仍优先放回 `pending`；其次有概念失败的原文 `fail_processing`（文字固定为 `Article generation failed`，原始异常只进日志，分类与退避沿用）；其余完成。一个概念被多个原文提到时，每个来源都失败（`blocked_sources`）；一个原文有多个失败时留最严重的：永久类优先于瞬时类，其次退避更长的。瞬时类由 worker 既有的自动重试接手（上限 3 次，守退避），永久类等用户点重试。③ `compiler.py::_maybe_pause_for_failed_articles`：整批没写出任何文章、且失败满足既有的 `evaluate_batch_pause`（认证 / 计费，或至少 3 个全是瞬时类，或至少 5 个任意）时暂停熔断；embed 暂停已发生时不覆盖那条更可操作的原因。④ `queue.py::get_transient_retryable_items` 把瞬时类过滤放进 SQL，`reset_transient_failed` 用同一组类别。⑤ 不改提示词、表结构、server 与前端；成功路径上发给模型的提示逐字节不变（见「实测」）。不做的：后处理抛异常时也暂停熔断（探针证明现状自愈、暂停反而会让整条流水线停下，理由写在 `pipeline/_ARCH.md` 的「Failure Policy Decisions」） |
| **反复次数** | 第 1 次发现 |
| **踩坑** | ① 起初以为「一个失败的概念对应一个原文」，读 `source_files` 才发现一个概念可以来自多个原文，失败必须落到每一个来源上，否则其余来源仍被标成完成；② 「批次期间被改过」的用例对 worker 入口的预期写成了 `pending`，实际 worker 在同一轮把重排的原文再编译一遍，终态是 `failed`、`retry_count 1`，所以拆成 `compile_all` 与 worker 两个用例各自断言；③ 一次并行工具调用里，脚本与 StrReplace 同时写 `compiler.py`，脚本那份被覆盖，靠 `git diff` 发现，之后同一文件的编辑不再放进同一批；④ 差分对照里 `hot.md` 的 `HH:MM UTC` 戳没有规范化，第一次对比所有格的文件都「不同」，规范化后只剩预期差异 |
| **回归** | 新增 `tests/toolkits/wiki/test_compile_article_failures.py` 22 例（worker 与 `compile_all` 两个入口各一遍：限流的文章只让该原文失败、其余完成；退避过后 worker 把缺的文章写出来；永久类不自动重试；共享概念让每个来源都失败；永久加瞬时只留永久；批次期间被改的原文重排而不是失败；等待审批算写成；全部限流或被供应商拒绝时暂停熔断；暂存稿计入暂停判断；embed 暂停不被覆盖）、`test_articles.py` 8 例，`test_batch_settle.py` 增 9 例（共 17），`test_queue.py` 增 2 例（C：12 条更早的永久失败不再挡住 2 条限流；按最旧优先取到上限）。首版 18 个编译级用例在旧代码上 15 例红、3 例本来就绿（等待审批的暂存稿算写成 2 例、`compile_all` 下编辑优先于失败 1 例，钉的是既有行为）；其后补的 4 例（暂存稿计入暂停判断、embed 暂停不被覆盖，各两个入口）没有在旧代码上单独跑，由变异 M13、M14 证明会红。变异检查 16 项，每项都有用例变红，每轮后用哈希确认文件已还原：embed 违规记成失败、取消的任务被丢、失败不分类、暂存稿不算成功、失败不按概念顺序、没有严重度排序、退避压过永久、失败压过编辑、文字不固定、退避丢失、未知来源不跳过、不暂停、embed 守卫去掉、成功数被忽略、来源键用裸文件名、结算忽略失败。全量：harness `tests/toolkits/wiki` 1042 例全部通过；最终代码上的另一次全量是 1041 通过、1 例失败，失败的是调用真实模型的 `test_sidecar_integration::test_sidecar_build_index_query_pipeline`（断言 `search_sidecars` 至少 1 个命中），它不经过编译器、队列与文章阶段，单独重跑 3 次都通过，按偶发记录；它经 `create_litellm_model` 调真实模型，超时改动是否对它有影响没有单独证伪，只知道它自带 120 秒上限、小于默认 300 秒的 `request_timeout`，超时不会先触发（此前一次全量里调用真实模型的 `test_sidecar_integration` 偶发失败过，这次通过）；server wiki 回归 466 例（`tests/api/wiki`、`tests/services/wiki`、`tests/integration/wiki`〔不含调用真实模型的 `test_wiki_real_llm.py`〕、`tests/test_wiki_writeback_routes.py`）通过 463，失败的 3 例与 `-005` 相同（`test_wiki_clip_security_blocked_job_response`、`test_import_folder_blocks_credential_content`、`test_import_urls_security_blocked`：导入闸门的 `security_blocked_count` 是 0，不经过编译、队列与模型超时，没能在改动前的 harness 上复跑），4 例被配置排除；ruff、mypy 对触及文件无错误，`validate_arch_inventory` 对 `wiki/pipeline` 通过 |
| **实测** | 差分对照（桩模型、真实队列与真实 vault）：把 H 之前的代码与最终代码各跑 4 个场景（成功、等待审批、已有文章加 purpose、`beta` 文章 429）× 2 个入口，记录发给模型的全部提示（排序后）、vault 全部文件、队列行、暂停状态与 `CompileResult`。前三个场景 6 格逐项一致（`hot.md` 的 `HH:MM UTC` 戳已规范化），所以成功路径上的提示、文件与结果没有变；`beta-429` 两格只有队列行不同：旧代码 `alpha`、`beta`、`gamma` 全是 `completed`，新代码 `beta` 是 `failed`、`rate_limit`、`retry_count 1`，`alpha`、`gamma` 仍是 `completed`，两边都是 8 条提示、相同的 `CompileResult`。没有验证：浏览器界面（失败计数、重试按钮），本条没改前端与 server，消费的是既有字段 |
| **局限** | ① 没有线上数据说明文章阶段失败的真实频率；价值是「完成」的含义变对：写不出文章的原文不再显示完成、也不再静默丢失，没有做性能声明；② 重试一个原文会重新抽取并重写它的全部概念文章，已有文章要求模型把新证据追加到时间线，真实模型是否重复追加没有测（与 `-005` 局限③同一条路径，被自动重试的上限 3 次约束）；③ 永久类失败（如上下文超限）重试仍会失败，每次点「重试」付一次完整重编的成本；④ 一个概念确定性失败会让它的每个来源都失败，同批其他概念的文章已写入，不回滚；⑤ 既有现象、未改：`publish_concept_article` 在安全扫描拦截时返回 `BLOCKED`，而 `generate_article` 丢弃返回值（`pipeline/publication/publish.py:66` 返回、`articles.py:250` 调用），仍计为已发布；这是确定性的内容拦截、重试无用，原文保持完成，只是计数不准；⑥ 后处理抛异常时不暂停熔断，见 `_ARCH.md`；⑦ 取消的文章任务被归因为失败时，退避与分类取自取消异常的文字，分类可能是 `unknown`，需要用户手动重试 |
| **代码位置** | `toolkits/wiki/pipeline/articles.py`：`ConceptFailure`（`:67`）、`ArticleBatchStats`（`:77`）、`generate_articles_batch`（`:98`）、`generate_article`（`:174`）· `pipeline/batch_settle.py`：`_severity`（`:51`）、`blocked_sources`（`:57`）、`settle_extracted`（`:79`）· `pipeline/compiler.py`：`_run_batch`（`:400`）、`_maybe_pause_for_failed_articles`（`:652`）、worker 自动重试（`:314`）· `pipeline/queue.py`：`_TRANSIENT_KINDS_SQL`（`:54`）、`get_transient_retryable_items`（`:334`）、`reset_transient_failed`（`:367`） |

### BUG-HARNESS-2026-10-16-006 · 更换嵌入模型后留在旧集合里的记忆管不住：「清空全部记忆」「按类型清空」「删对话级联」只清当前模型的集合，旧模型里的同一批记忆照样留着、迁移后又会冒回来；迁移只复制不搬走，且把旧模型的 BM25 镜像与前缀相近的外来集合也算进孤儿

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-16（#181 修完迁移后，对「迁移完旧集合还留着」这一设计逐条追问：用户在换模型前后各写过记忆、中间又删过，会怎样；本机开发库的估算接口当前仍返回 1591 条遗留在旧模型 `openai-baai-bge-m3` 的记忆——对话 1515、情景 14、语义 62，未点迁移、未改动该数据） |
| **修复时间** | 2026-10-16 |
| **症状** | ① 换模型后点「清空全部记忆」，界面显示已清空，但旧模型集合里的记忆还在，下次迁移（或任何读旧集合的路径）又把它们带回新模型；② 对话级联删除、按类型清空、按项目清空对旧模型里的同源记忆同样无效；③ 孤儿统计会把旧模型集合的 `_bm25` 稀疏镜像当作一个独立的待迁移集合，也会把前缀相近的外来集合（`{prefix}X_semantic_*`）算作自己的孤儿；④ 设置页只有在刚应用完嵌入模型的那次会话里才看得到迁移提示，之后重开设置页看不到，而这些记忆在迁移前根本不参与回复；⑤ 迁移进行中点「清空全部记忆」「按类型清空」或删对话，删除完成后，在途的一页（至多 100 条）又被写回新模型集合，用户删掉的记忆再次出现 |
| **关联产品** | myrm-agent-harness `toolkits/memory/_manager/{model_collections,reindex,deletion,queries,listing_maintenance}.py`、`toolkits/vector/qdrant/store.py::delete_by_filter`；server `app/core/memory/adapters/cascade.py`；前端迁移提示见 `BUG-AGENT-2026-10-16-007` |
| **根因** | ① 集合名带模型后缀，而删除、查询、清空全部只算当前模型的集合名（读码结论）；② 旧的孤儿判定用 `find` + `startswith(prefix)`，既不排除 `_bm25` 后缀，也不要求前缀后紧跟类型名（读码结论）；③ 迁移是复制：旧集合保留，所以旧副本永远在；④ 清空全部记忆没有覆盖 conversation 集合，且向量库删除失败被吞成成功；⑤ `QdrantVectorStore.delete_by_filter` 对空过滤器把 `None` 当作选择器交给 SDK，被拒绝为 `Unsupported selector type`（嵌入式 Qdrant 上红灯复现），所以「按空过滤器清整个集合」这条路在向量库侧从来没通过；⑥ server 的级联删除管理器曾从集合列表里「猜」一个嵌入模型，猜到哪个就只清哪个模型的集合；⑦ 迁移的一页要经过读取、重嵌、写入几次等待，期间没有任何东西挡住同一集合族上的删除：删除清空旧集合后，这一页把已读到的记忆写进当前集合（用卡住嵌入调用的测试嵌入器在真实嵌入式 Qdrant 上复现：5 条记忆，`delete_all` 完成后新集合里仍是 5 条） |
| **修复** | 新增 `_manager/model_collections.py` 作为集合命名的唯一解读方：只认 `{prefix}_{semantic|episodic|conversation}_{后缀}`，排除当前模型集合与 `_bm25` 镜像，外来前缀不认；列不出集合的后端（模拟存储）退回只处理当前模型。删除类全部改为集合族口径：`delete_all`（含 conversation）、`delete_by_type`、按元数据级联与其预览、项目清空都覆盖当前模型加所有旧模型；清空的旧集合连同其镜像一并删除。`delete_all` 在关系库或向量库失败时先试完所有后端再抛 `MemoryError`（图谱与缓存仍为尽力而为）。迁移改为搬家：目标集合已有的 id 视为已搬，否则写入新集合；写入后回读确认目标里确有该 id，才从旧集合删除；任一步失败保留旧副本并计入 `failed`；正文为空的记忆直接从旧集合移除并计入 `skipped`；旧集合清空后删除集合与镜像。`QdrantVectorStore.delete_by_filter` 空过滤器改用空 `Filter()` 作选择器（与 `search` / `count` 的「空过滤器 = 全部」一致）。server 级联管理器不再推断模型，改用固定占位模型名（删除跨整个集合族，模型名不影响结果）。迁移的每一页与 `delete_all`、`delete_by_type`、按元数据级联共用 `model_collections.py::family_lock`（按向量后端与集合前缀各一把锁）：删除等在途的一页做完；删除抢在两页之间完成时，迁移发现旧集合已不存在就结束，不计失败。`delete_by_type` 的旧模型集合清不掉时，先清图谱与缓存再抛 `MemoryError`；孤儿统计里某个集合的数量读不出时记警告日志，不再静默当作 0。`delete_by_type` 新增关键字参数 `include_previous_models`（默认真）：server 的备份「覆盖恢复」要替换的是用户看得见的记忆，快照里没有旧模型遗留的那批，覆盖不能把它们销毁，所以只清当前模型的集合（`EphemeralMemoryManager` 的覆写签名同步） |
| **反复次数** | 第 2 次：同日自审发现迁移与删除交错时的竞态（症状 ⑤、根因 ⑦），补集合族锁 |
| **踩坑** | ① 「迁移」与「删除」是同一个集合族上的两个操作，只修一个会让另一个把问题放大——复制式迁移叠加只删当前集合的删除，等于删了又复活；② 模拟存储的用例对 `list_collections` 返回 MagicMock，必须让「列不出集合」退回当前模型，否则一大批原本有效的用例会因此失去意义；③ 清空旧集合时要连同 `_bm25` 镜像一起删，否则镜像成为永远清不掉的残留；④ `delete_by_filter` 的空过滤器问题只在真实嵌入式 Qdrant 上才暴露，模拟客户端接受任何选择器；⑤ 单看迁移或单看删除的用例都能过，两者交错才出问题，要用卡住嵌入调用的测试嵌入器让删除落在一页中间；锁的变异检查：把共享锁换成每次新建的锁，4 个交错用例全部变红 |
| **回归** | `tests/toolkits/memory/model_switch/` 48 例，跑在真实嵌入式 Qdrant（旧模型 8 维、新模型 12 维）上：`test_model_collections.py`（集合识别、镜像与外来前缀不算孤儿、列不出集合时的退路、清空旧集合连镜像一并删除、仍有记忆的集合不删、集合族锁跟随向量后端与前缀而不是管理器）、`test_family_deletion.py`（`delete_all` 清掉每个模型的记忆并删除旧集合、`include_previous_models=False` 只清当前模型、失败在其余集合清完后才上报、按类型清空只动该类型、元数据级联与预览覆盖旧模型、不推断模型的级联管理器、删掉的记忆不会随下一次切换复活）、`test_reindex_migration.py`（回读确认才删旧副本、写入但目标不含该 id 时不被信任、删除失败可重试且不重复、空正文移除、情景记忆不触图、对话两个命名向量重嵌、读不出数量的集合会记警告）、`test_deletion_during_migration.py`（`delete_all`、`delete_by_type`、按会话级联落在迁移一页进行中时都不被写回，两页之间的删除让迁移结束且不计失败，旧集合清不掉时 `delete_by_type` 先清图谱再抛出）；`tests/toolkits/vector/test_qdrant_store.py` 新增空过滤器 3 例；`tests/toolkits/memory/test_manager_crud.py` 的 `delete_all` 失败用例改为断言先清完再抛 `MemoryError`；server `tests/core/memory/adapters/test_cascade.py` 经真实级联管理器验证两个模型的同源记忆都被清掉。红灯：空过滤器在嵌入式 Qdrant 上对旧实现抛 `Unsupported selector type`（已复现）；其余几项的旧行为是读码结论，没有逐项对旧实现跑红灯 |
| **局限** | ① 远程 Qdrant 服务对空过滤器的行为只有公开 issue 的说法，没有连远程服务验证；② 按元数据的级联不回收清空的旧集合，只有 `delete_all`、`delete_by_type` 与迁移回收；③ 没有「按 id 跨族清除」入口：搬家后同一条记忆只存在于一个集合，不需要；④ `delete_all` 对关系库 / 向量库失败的契约由「吞掉」改为「试完后抛出」；⑤ 空正文记忆在迁移时被移除（无法向量化，留着也永远召不回）；⑥ 没有用真实嵌入服务量过迁移耗时与费用；⑦ 没有在浏览器里走完「清空全部再重新加载」的端到端流程；⑧ 锁只在同一进程内有效（本产品是单进程服务，多个进程共用同一向量库时不互斥）；⑨ 一页持锁期间含一次嵌入请求，期间发起的删除请求要等到这一页结束，等待时长取决于嵌入服务，没有实测；⑩ 按 id 的单条删除不取锁：迁移中的记忆在搬进新集合前列表里看不到，用户点不到它；⑪ 竞态用例用的是测试嵌入器，没有用真实嵌入服务和真实交错时序跑过；⑫ 备份覆盖恢复的保护靠调用方传 `include_previous_models=False`，新增的覆盖类调用方需要自己想到这一点；⑬ server 的 mem0 兼容接口 `DELETE /v1/memories/`（`app/api/mem0_compat/endpoints.py:198-207`）对每个类型 `except Exception` 后只记警告、照样回「删除成功」，所以 `delete_by_type` 因旧模型集合清不掉而抛出的 `MemoryError` 在这个接口上仍被吞掉（既有写法，没有改：不确定哪些类型会正常抛错，改成失败即报错可能让原本成功的调用变 500）；`DELETE /memory/all` 则会把它变成 500 |
| **代码位置** | `toolkits/memory/_manager/model_collections.py::family_lock` · `_manager/reindex.py::detect_orphan_collections/_migrate_orphan/_migrate_batch` · `_manager/deletion.py::delete_all/delete_memories_by_metadata` · `_manager/queries.py::list_memory_ids_by_metadata` · `_manager/listing_maintenance.py::delete_by_type` · `toolkits/vector/qdrant/store.py::delete_by_filter` |

### BUG-HARNESS-2026-10-16-005 · wiki 编译在概念抽取完就把原文标成「已完成」，之后写文章、矛盾综合、认知地图、反向链接、侧车、元数据还在跑：这段时间队列显示空闲，界面提前提示「编译完成」、维护任务被放行，进程在这段时间被杀则文章丢了、原文却显示已完成

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-16（#140 第七批收尾复审：`BUG-HARNESS-2026-10-16-001` 之后追问「被杀如果发生在抽取之后会怎样」，用真实被杀的子进程与外部轮询队列库实测，不靠读码推断） |
| **修复时间** | 2026-10-16 |
| **症状** | ① 一批原文在概念抽取完时就被标成 `completed`（HEAD 的 `compiler.py:556` 的 `mark_completed`），之后才写文章、矛盾综合、认知地图、反向链接、侧车、元数据、vault 快照；这段时间队列里 `processing == 0`。所有人都拿 `processing > 0` 当「编译在跑」：前端 `WikiSection.tsx:899` 的 `isWikiCompileBusy`、`:886` 的「编译完成」提示（`active = processing > 0 \|\| pending > 0 \|\| 暂停`）、server `app/services/wiki/maintain/runner.py:81-83` 与 `app/services/wiki/dedup_runner.py:75-78` 的 `_compile_is_busy`、`app/services/wiki/daily_review/runner.py:123` 的「后台 worker 空闲」判断（`pending > 0 且 processing == 0` 时再跑一次 `compile_all`）。② 这段窗口里进程被杀：队列已是 `completed`，重启后没有任何东西重跑，文章却没写完，界面显示全部完成 |
| **关联产品** | myrm-agent-harness `toolkits/wiki/pipeline/`（`compiler.py`、`queue.py`）；读同一个 `processing` 计数的 server 维护 / 去重 / 每日回顾与前端 `WikiSection.tsx`（本条均未改） |
| **根因** | 「完成」被定义成「概念抽取完」，而不是「这个原文的全部产出写完」。一批在抽取之后还有 5 个步骤、每步都有模型调用（文章每个概念 1 次，`compiler.py:677` 的 `_generate_article`；矛盾检测与侧车另有调用），这些步骤全在 ack 之后；同一条流水线还在 worker 与 `compile_all` 里各写了一份，任何一处修都得改两遍 |
| **修复** | ① 两份重复的抽取后流水线合并成 `compiler.py` 的 `_run_batch`（worker 与 `compile_all` 都走它）与 `_postprocess_batch`；两个入口原有的差异保持：worker 在没有概念时整段跳过、`compile_all` 仍刷新认知地图与元数据（参数 `postprocess_empty`），embed 窗口违规暂停后 worker 不拍快照、`compile_all` 提前返回部分结果。② 抽取阶段只落失败行；成功的原文留在 `processing`，连同抽取读文件之前取的内容哈希（`_extract_concepts_batch` 的 `read_hashes`）一起带到批次末尾；元数据保存完才由 `pipeline/batch_settle.py` 的 `settle_extracted` 结算：文件内容仍是读取前哈希的原文 `complete_processing`，批次期间被改过的原文 `requeue_processing` 放回 `pending`（`save_metadata` 记录的是保存那一刻所有原文的哈希，`pipeline/postprocess.py:99`、`core/claims_contract.py:544`，而入队会跳过 `processing` 的文件，`pipeline/compiler_enqueue.py:49-51`；一律标成已完成，批次期间的改动就再也不会被增量编译发现）；读不到的文件（批次期间被删）照旧算完成；之后才拍 vault 快照（快照是对 vault 的备份，不属于某个原文的产出；快照出错的传播方式与以前一致）。③ 后处理抛 `Exception`：`fail_extracted`（`batch_settle.py:66`）让这批行 `fail_processing`，错误分类沿用抽取阶段的 `resolve_llm_failure`，瞬时类（限流 / 过载 / 超时）由 worker 既有的 `get_transient_retryable_items(max_retries=3)` 自动重试，然后原样抛出，worker「遇意外异常即停」的既有行为不变；失败行的文字固定为 `Compile postprocess failed`（队列面板把它展示给用户，原始异常常是文件路径或 sqlite 错误，只进日志），分类放在 `error_kind`；`CancelledError` 等 `BaseException` 不捕获，行留在 `processing`，由 `-001` 的首次打开清扫接手。④ embed 窗口违规暂停：行照常 `completed`（文章已写，缺的只是向量索引，暂停对用户可见），与改动前一致。⑤ 保活：行在整批期间保持 `processing`，而 `reset_stale_processing`（300 秒）在每次 worker 启动时执行（旧代码里行早已 `completed`，碰不到它），所以批次期间 `queue.keep_alive` 每 60 秒（阈值的 1/5）刷新这批行的 `updated_at`。⑥ 四个新状态方法（`complete_processing`、`fail_processing`、`requeue_processing`、`touch_processing`）都带 `AND status = 'processing'`：`add_item` / `add_batch` 的 upsert 把已在 `processing` 的行无条件写回 `pending`（`queue.py:132-133`、`159-160`），归档器的 `enqueue_file` 也直接走 `add_item`，批次期间被新请求重新排队的行必须保持 `pending`，不能被 ack 盖成 `completed`。无生产调用方的 `mark_completed` 换成 `complete_processing`。不改表结构、提示词、工具 schema、前端与 server |
| **反复次数** | 第 1 次发现 |
| **踩坑** | ① 计划里用 `mark_processing` 当保活：读 `add_item` 的 upsert 后发现它会把被新请求重排的行写成 `processing`，ack 不带条件还会盖掉重排，改成带条件的 `touch_processing` / `complete_processing` / `fail_processing`；② 保活最初想用 `asyncio.sleep` 循环：现有测试在 `patch("asyncio.sleep")` 下跑 worker，会变成空转写库，改用 `loop.call_later`；③ 被杀恢复用例第一版在杀进程之前就建了编译器：本进程已「打开过」该库，`-001` 的首次打开清扫不会再跑，重启后行仍是 `processing`；用例里重启前不能先打开队列；④ 对旧代码做对照时，`PYTHONPATH` 在 pytest 下不生效（`pyproject.toml:301` 的 `pythonpath = ["src"]` 排在前面），第一次「旧代码也通过」是假的；改用 `-o pythonpath=` 并用必红用例证明导入的确是旧代码；被杀恢复用例的子进程另走 `sys.executable -c`，不继承 pytest 的路径，只设 `-o pythonpath` 时它跑的是已安装的新代码而假通过，旧代码对照必须同时设 `PYTHONPATH` 环境变量；⑤ 同一概念有多个来源时 `source_files` 来自 `list(set(...))`（`compiler.py:569`），进程之间的顺序不定，差分对照要固定 `PYTHONHASHSEED`；⑥ `/tmp` 上我的 `mutate.py` 被别的会话的同名脚本覆盖，第一次变异检查跑的是别人的脚本；之后用私有临时目录，并用哈希确认产品文件每轮变异后都还原；⑦ 第一版在批次末尾一律 ack，对抗式审查时用探针对照旧代码才发现回归：批次期间被改的原文丢更新（数据见「实测」⑤）；把 ack 往后推时，要核对推迟的窗口里别的路径依赖的前提——入队跳过 `processing` 的文件、元数据按保存时刻记哈希 |
| **回归** | 新增 `tests/toolkits/wiki/test_compile_batch_ack.py` 19 例与 `test_batch_settle.py` 8 例，最初的 13 例是：worker 与 `compile_all` 各一遍，抽取之后到元数据保存之前队列都是 `{processing: 3, completed: 0}`，快照时才 `completed: 3`；后处理抛错时 3 个原文是 `failed` 而不是 `completed`（`error_kind` 为分类结果，`retry_count == 1`，不被自动重试）；瞬时错误带退避时间；批次期间被重新排队的原文保持 `pending`；批次比过期阈值长时不被 `reset_stale_processing` 放回；真实 `os._exit(137)` 在文章阶段杀掉的进程之后，下一个进程的队列是 `{pending: 1}`，worker 无需用户点击就把文章写完（文章文件恰好 1 个）；embed 暂停后 3 个原文 `completed` 且不拍快照；没有概念时只有 `compile_all` 刷新元数据；worker 与 `compile_all` 对同一批原文产出同一个 vault（逐文件内容，去掉时间戳与 vault 路径）；其后补的 6 例：批次写文章期间改了源文件（worker 与 `compile_all` 各一遍，期间点编译入队 0 个）与抽取的模型调用期间改了源文件，都被放回 `pending` 并重编，最终读到两版内容各一次；批次期间被删的原文仍算完成；保活的一拍失败（`database is locked`）既不停批次、也不向事件循环报未处理异常；取消的批次让原文留在 `processing` 且保活计时器已停。`test_batch_settle.py` 对真实队列与临时文件覆盖结算的六种情形（未改、被改、被删、读取前读不到现在能读、批次期间被重新排队、失败分类与固定文案）。`test_queue.py` 新增 4 例（`requeue_processing` 只动 `processing` 的行、已被重新排队的行不被 ack / fail 动、`touch_processing` 只碰 `processing`），改了 2 例；`test_compiler_extended.py` 的 2 例原来靠让 `mark_completed` 抛错注入失败，改为在抽取步骤注入，断言不变（外加失败行数）。旧代码上 7 例红且原因对（被杀恢复用例红在重启后队列是 `pending: 0` 而不是 `pending: 1`）；其余 6 例旧代码上也通过：「embed 暂停」2 例、「无概念」2 例、「两个入口产出同一个 vault」1 例钉住的是既有行为；「批次期间被重新排队的原文保持 pending」在旧代码上平凡成立（批次期间行早已 `completed`，没有 `processing` 行可被覆盖），它保护的是新实现，ack 不带条件的变异会让它变红。变异检查在最终代码上共 20 项，每项都有用例变红，每轮后用哈希确认文件已还原：去掉保活、ack 不带条件、先结算后处理、失败不落库、无概念也处理、touch 不带条件、快照先于结算、`fail_processing` 不带条件、失败不带分类、瞬时失败不带退避、原始异常进了界面文字、忽略批次期间的改动、读取后才取哈希、`requeue_processing` 不带条件、读不到的文件算被改、被改的行不放回、`BaseException` 也记成失败、保活的错误不捕获、计时器不取消、失败后不重新排下一拍。差分对照（在补上批次期间改动的结算之前做的，之后没有重跑；那之后的差别只在批次期间源文件被改过的情形，见「实测」⑤）：把 HEAD 的 `src` 导出到临时目录对照当前代码，6 个场景（正常、全部失败、部分失败、认证失败暂停、无概念、embed 暂停）× 2 个入口，固定 `PYTHONHASHSEED` 后 12 格的队列状态、逐行状态与错误分类、暂停状态、`CompileResult`、模型调用数、vault 下所有文件内容（去时间戳）逐项一致。全量：harness `tests/toolkits/wiki` 最终代码上 1001 例全部通过（此前一次全量里 `test_sidecar_integration.py::test_sidecar_build_index_query_pipeline` 失败过，那是调用真实模型的集成用例，不经过编译器与队列，在未改动的 HEAD 源码上单独跑 4 次也失败 2 次，按偶发记录），server `tests/api/wiki`、`tests/services/wiki`、cron job runner 与写回路由 467 例通过 464，失败的 3 例与前几批相同（`test_wiki_clip_security_blocked_job_response`、`test_import_folder_blocks_credential_content`、`test_import_urls_security_blocked`：导入闸门的 `security_blocked_count` 是 0，不经过编译器与队列；server 虚拟环境固定导入工作区的 harness，`PYTHONPATH` 指到 HEAD 也不生效，没能在 HEAD 的 harness 上复跑），4 例被配置排除；ruff、mypy 对触及文件无错误，`validate_arch_inventory` 对 `pipeline/` 通过；`compiler.py` 861 → 837 行，`file_line_baseline.txt` 同步收紧 |
| **实测** | 真实进程，不是桩：真实 `WikiCompiler` 的后台 worker 跑在子进程里（每次模型调用延迟 1.5 秒的桩模型，3 个原文），父进程只读 sqlite 外部轮询队列（不打开队列对象，免得触发清扫），每 0.2 秒一次；对 HEAD 与当前代码各跑一遍。① 不杀：旧代码队列在 9.6 秒变成 `completed: 3`，而模型请求到 12.6 秒才结束，空闲假象 3.2 秒；新代码队列忙到 8.1 秒，最后一个请求 8.3 秒结束，只差一个采样间隔；两者都是 7 次模型请求、3 个文章文件。② `kill -9` 落在文章阶段、重启后没有任何新请求（无用户点击）：旧代码杀后立刻是 `completed: 3`，之后共 6 次模型请求就结束，**文章文件 0 个**；新代码杀后是 `processing: 3`，重启后首次打开清扫放回、worker 接着编译，共 13 次请求，3 个文章文件，`completed: 3`，队列忙到最后一个请求结束。③ 同样的杀法、重启后再发一次入队（相当于用户点编译）：旧代码也能补齐（元数据没写，增量检查把它们重新排上），代价是空闲假象再来一次 3.2 秒；新代码忙到结束。⑤ 批次期间改源文件（私有目录里的真实 `WikiCompiler`，桩模型，批次写文章时把源文件改掉，旧代码取 HEAD 导出）：批次内点编译：旧代码入队 1 个、批次结束后 `pending: 1`；第一版（没有结算时的内容检查）入队 0 个、`completed: 1`，改动丢失；最终代码入队 0 个、批次结束后 `pending: 1`；批次内改了、批次结束后才点编译：旧代码与第一版都是 `completed: 1`、之后点编译入队 0 个（改动丢失），最终代码批次结束后 `pending: 1`。第一版的丢失是对抗式审查里发现的：批次内点编译在旧代码里靠「行已是 `completed`」才被放行，第一版把这个窗口延长到整批，而另一种情形（批次内改、之后才点）本来就丢。一个 1 MB 的原文算哈希 0.6 毫秒、10 MB 为 5.6 毫秒（5 次取平均），一批至多 5 个原文、前后各一次。⑥ 没验证：浏览器界面（「编译完成」提示的时机、忙碌标签、按钮禁用，桌面与 390 像素、明暗主题）——常驻的 :3000 / :8080 是旧代码加真实数据，不能动，另起一份 Next 开发服务在这台高负载机器上不安全；server HTTP 层（本条没改 server，消费者只读同一个 `processing` 计数，所以按公式代入真实队列状态推断）；真实模型供应商 |
| **局限** | ① 没有线上数据说明进程被杀的真实频率；价值主要是「完成」的含义变对：忙 / 空闲信号与真实工作一致、被杀不再静默丢文章，没有做性能优化声明；② 一个原文若确定性地把进程弄死，会在每次重启时被放回并重跑，没有次数上限；改动前也是这样（300 秒后被 worker 启动时的清扫放回），没有观察到真实触发源，不处理；③ 被杀后的重编与「用户改了文件再增量编译」「重试全部」是同一条路径：`_generate_article` 对已有文章要求模型更新 Compiled Truth 并往 Timeline 末尾追加新证据（`compiler.py:698`），模型可能把同一来源的证据再追加一次；这不是本条引入的，只是被杀后的重编现在自动发生；桩模型下的重编没有产生重复页面，但真实模型的追加行为没有测过；④ 一个 vault 一个进程仍是假设（与 `-001` 同口径）；⑤ 批次的暂停路径之后 worker 多睡 1 秒再回到循环顶部检查暂停（原先 `continue` 直接回顶部），没有可见影响；⑥ 日常回顾的救援 `compile_all` 与用户点编译的 worker 同时在跑的并发写没有复现；保活只保证批次不被当成死的，不是互斥；⑦ 保活让一个永不返回的批次（模型调用卡死）一直读作「忙」：流水线里没有超时（`pipeline/` 下只有 `ingress/asset_store.py:174` 一处下载超时），原先卡在后处理阶段读作「空闲」，卡在抽取阶段同样读作「忙」；没有核对模型客户端自身的超时，也没有给批次加总时限；⑧ 批次期间被改过的原文会多编译一次（多花一次抽取与文章生成）；哈希在抽取读文件之前取，所以读文件之后的改动一定被抓住，哈希之后、读之前（信号量排队期间）的改动会多重编一次，方向安全；批次期间把原文改回原样不会被发现（哈希相同）；⑨ 与本条无关、未动：每批结束时 `save_metadata` 记录全部原文的哈希，被取消或没轮到的原文下次增量编译会被当成未变更（见 `-001` 局限 ④） |
| **代码位置** | `toolkits/wiki/pipeline/compiler.py`：`_run_batch`（`:416`，保活 `:430`、`fail_extracted` `:449`、`settle_extracted` `:451`；worker 调用 `:345`、`compile_all` 调用 `:395`）、`_postprocess_batch`（`:457`）、`_extract_concepts_batch`（`:497`，读取前取哈希 `:517`、记入 `read_hashes` `:533`）· `pipeline/queue.py`：`complete_processing`（`:218`）、`requeue_processing`（`:237`）、`keep_alive`（`:258`）、`fail_processing`（`:291`）、`STALE_PROCESSING_SECONDS`（`:49`）· `pipeline/batch_settle.py`：`source_hash`（`:39`）、`settle_extracted`（`:47`）、`fail_extracted`（`:66`） |

### BUG-HARNESS-2026-10-16-004 · 本地开发模式下持久化根被重映射后，存储配额管理器、restore-map 路径匹配、bash 上下文访问追踪仍按 `/persistent` 字面量工作

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-16（持久化根改为由 `MYRM_PERSISTENT_ROOT` 在调用时派生之后，逐个核对仍写死 `/persistent` 的运行时代码） |
| **修复时间** | 2026-10-16 |
| **症状** | ① `SimpleStorageQuotaManager()` 默认扫描 `/persistent/.context`，本地模式该目录不存在，会话用量恒为 0，配额检查与自动清理从不触发；server 的 `get_quota_manager()` 用的就是这个默认值；② `archive_path_matches` 只认 `/persistent/` 前缀，根被重映射后，restore-map 里带根的路径与根相对路径互不相等，恢复范围被判为无效；③ `track_context_access_in_command` 只收 `/persistent` 开头的路径，重映射后 bash 读取上下文文件不被记录，「近期读过的文件不清理」这条规则对这条通路失效 |
| **关联产品** | myrm-agent-harness `runtime/quota/manager.py`、`runtime/context/restore_map_contract.py`、`agent/meta_tools/bash/_tool/helpers.py`、`runtime/paths/execution_paths.py`；server `app/platform_utils/__init__.py::get_quota_manager`、`app/platform_utils/persistent_root.py`、`app/services/agent/session_access_service.py` |
| **根因** | 持久化根改为调用时派生后，这三处仍保留字面量，没有走 `get_persistent_root()` / `get_context_root()`；原有测试都在默认根下运行，看不出差别 |
| **修复** | 配额管理器的 `context_root` 缺省为 `None`，构造时取 `get_context_root()`；`archive_path_matches` 与上下文访问追踪按 `get_persistent_root()` 取前缀；`DEFAULT_PERSISTENT_ROOT` 改为公开常量，server 两处 `/persistent` 字面量改用它 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | 第一次做「换回旧源码」的变异检查时，路径带了错误的仓库前缀，`git show` 失败而重定向已把三个源文件清空；随即从事先备份还原，并用 `cmp` 确认备份与当时文件逐字节一致后重做 |
| **回归** | `tests/runtime/test_quota_manager.py` 1 例 · `tests/runtime/context/test_restore_map_archive_paths.py` 3 例 · `tests/agent/meta_tools/bash/test_bash_tool_coverage.py` 1 例。把三个源文件换回修改前的版本，3 个针对重映射根的用例全部失败，换回后通过 |
| **局限** | `toolkits/code_execution/security/validator.py::_get_allowed_paths` 仍写死 `/persistent/.context`。toolkits 层不允许导入 runtime（`tests/architecture/test_toolkits_agent_boundary.py`），所以没有在这里改。实测：根重映射后 `validate_command("cat <根>/.context/s1/compacted/f.txt")` 返回「Access denied … Only current session workspace is accessible.」，默认根下同一条命令通过。改法应在 agent 层经 `ExecutionContext.additional_readonly_paths` 注入上下文根；该字段目前只有评测代码填充，生产路径没有 |
| **代码位置** | `runtime/quota/manager.py::SimpleStorageQuotaManager.__init__` · `runtime/context/restore_map_contract.py::archive_path_matches` · `agent/meta_tools/bash/_tool/helpers.py::track_context_access_in_command` · `runtime/paths/execution_paths.py::DEFAULT_PERSISTENT_ROOT` |

### BUG-HARNESS-2026-10-16-001 · wiki 编译进程被杀后，队列里遗留的「处理中」条目没有任何进程认领：崩溃后 300 秒内重启时，界面一直显示「编译中」并禁用维护与重建索引

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-16（#140 第七批收尾复审：追问「点了编译后进程被杀会怎样」，用真实被杀的子进程复现，不靠读代码推断） |
| **修复时间** | 2026-10-16 |
| **症状** | 编译中途进程被杀（`kill -9`、崩溃、断电）后，队列里 `status='processing'` 的行没有任何进程持有；界面与 server 都以 `processing > 0` 判断「正在编译」（前端 `WikiSection.tsx:899` 的 `isWikiCompileBusy` 驱动「编译中」标签、禁用维护与重建索引；server `maintain/runner.py:81-83` 的 `_compile_is_busy` 拒绝维护），所以重启后界面一直显示忙；原先唯一的恢复路径是 `reset_stale_processing`（`pipeline/queue.py:415`，超过 300 秒的 `processing` 回到 `pending`），它只在后台 worker 启动时执行（`pipeline/compiler.py:316`）：worker 在归档器建好时（server `app/services/wiki/memory_to_wiki.py:181-183`）与点编译时启动，但条目距上次更新要超过 300 秒才会被放回，所以崩溃后 300 秒内重启的，会一直忙到之后某次 worker 启动 |
| **关联产品** | myrm-agent-harness `toolkits/wiki/pipeline/`（`queue.py`、`queue_recovery.py`）；读同一个 `processing` 计数的 server `app/services/wiki/maintain/runner.py` 与前端 `WikiSection.tsx` |
| **根因** | 队列只记「这一行正在处理」，没有记「谁在处理」；进程死后没有路径把它改回去，只剩一个与进程无关的 300 秒阈值，且只在 worker 启动时才检查 |
| **修复** | 新增 `pipeline/queue_recovery.py::requeue_orphaned_processing`：一个队列库在本进程里第一次被打开时，把仍是 `processing` 的行放回 `pending`（它们是死进程留下的，没有任何东西在处理）；`queue.py:74` 在建表之后调用。同进程内再次打开不清扫：归档器缓存键含 `id(llm)`（server `app/services/wiki/vault/service.py:78-93`），同一个库会被多个队列对象打开，那时 `processing` 的行属于活的 worker；并发的首次打开靠模块级映射的 `setdefault` 令牌保证只清扫一次（`queue_recovery.py:30,43`）；清扫本身失败（例如库被锁）时撤销「已清扫」标记，下一次打开重试（`queue_recovery.py:51-54`）。不改表结构、提示词与工具 schema。放回 `pending` 之后不需要用户操作：归档器建好时已经启动后台 worker（`app/services/wiki/memory_to_wiki.py:181-183` → `compiler.py:290`），它每批最多取 5 个待处理条目接着编译（`compiler.py:311,327`），与本来就留在 `pending` 的条目同口径。多花的只是被杀那一批里已开始但没完成的原文的模型调用；改动前它们等满 300 秒后也会被 worker 启动时的 `reset_stale_processing` 放回并自动重编，所以不是新增的成本，只是不再多等 300 秒。没有为此加确认步骤：那会改变所有待处理条目在重启后的既有行为 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | ① 评估过给每行加「持有者进程」列并做迁移，过度设计：一个 vault 同时只有一个进程，进程内只需要知道「本进程是否已经清扫过这个库」，不用改表；② 并发用例第一版用 16 个线程、800 个库与极小的线程切换间隔去撞「先查后写」的竞态，变异检查里只在约 5 次里抓住 4 次，不能当证明；改为让注册表的每次读取都停到所有线程都读过之后，任何「先查后写」的写法每次都失败；③ 第一版在占到「已清扫」标记之后才去清扫：清扫本身抛错时标记已经留下。探测（连接第一次抛 `database is locked`）：第一次打开抛出，第二次打开清扫 0 行，行仍是 `processing`，本进程里只剩 300 秒的旧路径；改为失败时撤销标记 |
| **回归** | 新增 `tests/toolkits/wiki/test_queue_orphan_recovery.py` 5 例：真实被 `os._exit(137)` 杀掉的子进程遗留 3 个 `processing` 后，下一个进程的队列为 `{pending: 3, processing: 0, completed: 0, failed: 0}`；同一个库的第二个队列对象不动活 worker 的行（`processing == 1`）；8 个线程同时首次打开一个库只清扫一次；被杀之后 `compile_all` 把被中断的原文编译完（`completed: 1`）；第一次清扫因库被锁而失败后，下一次打开仍会清扫（`requeued == 1`）。变异检查（改一处、跑、写回，对 5 例）：整段清扫去掉，5 例里 4 例失败；每次打开都清扫，2 例失败；失败后不撤销标记，1 例失败（就是上面那一例）；「先查后写」的两种写法（`in`、`.get`）使并发用例每次失败（各 3/3），正确写法（原实现、`setdefault` 后回读）每次通过（各 3/3）。ruff 通过，mypy 对触及文件无错误 |
| **实测** | 隔离环境：临时数据目录、端口 18090 的后端、本地桩模型（每次调用延迟 20 秒），不碰常驻的 :3000 / :8080。① 真实 `kill -9`：编译进行中杀后端，库里遗留 `processing`（一次 4 个、一次 2 个）。② 改动前（把当前工作区的 harness 复制一份，只去掉清扫的 import 与调用）：重启后第一次读队列是 `{processing: 2, completed: 6}`，之后 19 秒内不变，桩模型没有收到新请求。这台机器负载很高（负载均值约 200），后端启动要 1 到 5 分钟，所以这一组在第一次读队列前用 sqlite 把这些行的 `updated_at` 改成当前时间，模拟「崩溃后 300 秒内重启」；另有一次没改时间戳，从被杀到第一次读队列隔了约 305 秒（这台机器上后端启动就要约 5 分钟），worker 启动时的 `reset_stale_processing` 已经把它们放回并重编（桩模型收到新请求），最终 `completed: 6`，说明改动前的行为是「等满 300 秒才恢复，然后自动重编」。③ 改动后（当前代码）：同样的状态，第一次读队列 `{pending: 2, processing: 0}`，约 8 秒后 `{processing: 2}`（既有 worker 接着编译，桩模型收到新请求），约 25 秒后 `{completed: 8, failed: 0}`；从真实 `kill -9` 遗留的 4 个条目开始的那一次，第一次读队列后约 80 秒内 `completed: 4`。④ 没验证：浏览器界面（桌面 / 390 像素、深浅色、点编译与停止）——常驻的 :3000 / :8080 是旧代码加真实数据，不能动，另起一份 Next 开发服务在负载约 200 的机器上不安全；真实模型供应商；同一个 vault 两个进程 |
| **局限** | ① 一个 vault 同时只有一个进程是假设，没有单实例锁（与看板启动恢复同口径：`app/lifecycle/schedulers.py:698,710-711`；`app/channels/storage/login_session_store.py:114` 也按单实例写）：两个进程共用一个 vault 时，后启动的进程会把先启动进程正在处理的行放回待处理，那个原文可能被编译两次（多花一次模型费用），没有测试这一情形；② 进程内 worker 卡住的情形仍靠 300 秒的 `reset_stale_processing`，本条不改；③ 没有线上数据说明进程被杀的真实频率；浏览器界面（桌面与 390 像素、深浅色下的忙碌标签与按钮）没有验证，原因见「实测」；④ 已评估后放弃（评分 4/10）：每批结束时 `save_metadata` 记录的是全部原文的哈希（`pipeline/postprocess.py:92-119`、`core/claims_contract.py:544-553`），所以一批里没轮到的原文（被取消、被停止）下次增量编译会被当作「未变更」而跳过；实测 8 个原文、批大小 5、全部取消后再点编译：入队 0 个，而有 3 个从未编译；用户可以用「重试全部」恢复（server `app/api/wiki/router.py:1729-1741`，前端 `WikiQueuePanel.tsx:189`），所以不改；⑤ 一个确定性地把进程弄死的原文会在每次重启时被放回并重跑，没有次数上限；改动前也是这样（只是要等 300 秒之后某次 worker 启动的清扫），没有观察到真实触发源，不处理；被杀落在概念抽取之后的情形，原先原文已被标成已完成而没有任何东西重跑，由 `BUG-HARNESS-2026-10-16-005` 把「已完成」改成全部产出写完之后，同样由本条的清扫接手 |
| **代码位置** | `toolkits/wiki/pipeline/queue_recovery.py::requeue_orphaned_processing` · `pipeline/queue.py::WikiIngestionQueue.__init__` |

### BUG-HARNESS-2026-10-15-009 · wiki 维护的模型一次都没答，结果与「没有可改进之处」无法区分，宿主也无法在运行中停下它；手动编译只能一次同步跑完整个编译，没有「只排队」的入口

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-15（#140 第七批复审，对 server 的「全量维护」与「手动编译」两个长请求追问宿主能拿到什么信号） |
| **修复时间** | 2026-10-15 |
| **症状** | ① `lint_and_maintain` 的模型阶段（漂移核对、链接发现）每次调用都返回空时，`LintResult` 与「模型看过、确实没有可改进之处」相同，宿主无从告诉用户「模型没有回答」；② 全量维护最多 25 次串行模型调用，宿主没有任何停止入口；③ `WikiCompiler.compile_all` 开头自己挑出要读的原文并入队、再整批处理完才返回，宿主想「只排队、让后台 worker 处理」时只能复制这段筛选逻辑；④ 这段筛选对每个原文算 SHA256，在事件循环上同步执行：合成库 5000 个约 195 KB 的原文使事件循环停顿 2809 ms（实测，3 次取中位数），宿主的 SSE 与其他请求都在等；⑤ 入队会把 worker 正在编译的条目写回待处理：队列写入是 upsert（`ON CONFLICT(file_path) DO UPDATE SET status='pending'`），手动编译连点时第二次入队使统计从 `{'pending': 1, 'processing': 1}` 变成 `{'pending': 2, 'processing': 0}`（实测），宿主用 `processing > 0` 判断「正在编译」的保护与界面指示随之失效 |
| **关联产品** | myrm-agent-harness `toolkits/wiki/maintenance/`（`ai_calls.py`、`drift_review.py`、`backlink_discovery.py`、`linter.py`）、`core/types.py`、`pipeline/compiler.py`；server `app/services/wiki/maintain/`、`app/api/wiki/router.py` 的 `/wiki/compile` |
| **根因** | 模型调用只被「用到」，没有被「数」：没有一个对象记录问过几次、答出几次；停止信号没有进入模型调用与阶段循环；`compile_all` 把「挑出要读的原文并入队」与「处理队列」写在同一个方法里 |
| **修复** | ① 新增每轮的 `AiCalls`（`maintenance/ai_calls.py`）：`ask()` 数问过与未应答的次数，`unavailable` 表示问过且一次都没答出来，`LintResult.ai_unavailable` 交给宿主；② `AiCalls` 持有宿主传入的 `asyncio.Event`，`ask()` 在调用前与等待中响应停止并抛 `MaintainStoppedError`，在途调用被取消（`ai_calls.py:92`，客户端不再等待，结果由完成回调取回）；两个模型阶段结束自己的阶段，从正常路径返回 `LintResult.stopped=True`，写入从不被打断，所以没有半写文件，被停止的链接发现批次从最后处理的页面之后续上游标；被停止的调用不计入问过次数；③ 新增 `WikiCompiler.enqueue_changed_sources()`（逻辑在 `pipeline/compiler_enqueue.py`：增量只排新增或变更的原文，全量排全部，返回入队数；worker 正在编译的原文不入队，筛选在最后一个 await 之后同步读取，同一事件循环里的 worker 无法在读取与写入之间认领），`compile_all` 复用同一方法；增量变更检查对每个原文算 SHA256，改在工作线程里执行（`asyncio.to_thread`），合成库 5000 个原文：事件循环最长停顿 1046 ms → 46 ms（每个约 9 KB）、2809 ms → 60 ms（每个约 195 KB），3 次取中位数，本机，页缓存已预热，不是线上数据。没有改任何提示词、工具 schema 与存储表；宿主不传 `stop` 时行为不变 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | ① 第一版在 `linter.py` 里多写了一个 `and not ai_calls.stopped` 守卫，变异检查显示去掉它后全部用例仍通过（行为冗余），代码已删；② 被丢弃的在途模型调用的结果没人读，要由完成回调取回，免得事件循环把它当作未取回的异常记录（`_discard_outcome`）；③ 停止后的链接发现游标不能推进到整批末尾，否则未问的页面会被永远跳过，改为从最后处理的页面之后续上；④ 入队里读取「正在处理」的条目必须放在最后一个 await 之后：第一版在变更检查之前读取，检查期间被 worker 认领的条目仍被写回待处理，只有「检查期间被认领」的用例能抓住它 |
| **回归** | 新增 `tests/toolkits/wiki/test_maintain_ai_calls.py`（17 例：计数含抛错的调用、取消不算未应答、全量维护的未应答与可用判定、未应答不拖住链接发现轮转、停止后不再发起调用、停止时丢弃在途调用且不计数、取消运行即取消在途调用、停止时保留已写链接并从最后处理的页面之后续上、模型挂起时及时返回、结构性维护不受停止影响）与 `test_compiler_enqueue.py`（13 例，后 5 例是变更检查的哈希筛选用例，从 `test_compiler_extended.py` 迁入并改测 `compiler_enqueue.filter_changed_files`；前 8 例：不调用模型地入队、第二次调用每个原文只排一次、增量只排上次之后变更的、变更检查的哈希不在事件循环线程上、全量重新排全部、没有原文时不排、正在编译的原文保持处理中、变更检查期间被 worker 认领的原文保持处理中）；变异检查：停止逻辑 4 个（3 个被抓住，1 个是行为冗余的守卫，已删除代码）、入队 5 个（含去掉「跳过正在编译的原文」的筛选：两个新增用例失败；把读取提前到 await 之前：只有「检查期间被认领」的用例失败）、线程化 1 个（换回内联执行，新增的线程用例失败），其余全部被抓住；入队逻辑拆到 `compiler_enqueue.py` 之后，对搬走的逻辑再做 4 个变异（哈希比较取反、不跳过处理中的条目、增量被忽略、读不了的文件当作未变更），每个都至少被 1 个用例抓住；`tests/toolkits/wiki` 965 例通过（此前一次全量运行里依赖真实模型的 `test_sidecar_integration.py::test_sidecar_build_index_query_pipeline` 失败过一次，`sidecar_hits` 为空，该例不经过队列与编译器；单独运行 3 例通过、其后三次全量均通过，没有定位到原因，按偶发失败记录），真实 LLM 的 `tests/integration/llm_extraction/test_wiki_compile_e2e.py` 3 例（含 `test_compile_all_full_pipeline_real_llm`）在入队重构后、线程化后与跳过处理中条目后各跑一次均通过，ruff 通过，mypy 对触及文件无错误（`toolkits/wiki` 整体另有 27 条分布在 13 个未触及的文件）；同批修掉 `pipeline/compiler.py` 里一处既有 mypy 错误（`serialize_frontmatter_block` 入参类型） |
| **局限** | 停止是协作式：只在两次模型调用之间与调用等待期间响应；维护用的模型是非流式（server `app/services/agent/llm_access.py:40-41` 的 `streaming=False`），客户端取消等待后服务商仍可能完成并计费那一次调用（没有对照服务商账单验证）；调用是串行的，所以一次停止最多多花一次调用；`compile_all` 与后台 `_worker_loop` 各有一份相近的流水线，本条没有合并；入队与变更检查拆到 `compiler_enqueue.py` 之后 `pipeline/compiler.py` 为 837 行，仍超出文件行数建议，行数基线上限已收紧到 837；入队只避开入队那一刻已被认领的条目，这建立在认领与入队同在一个事件循环上（`pipeline/compiler.py:506` 同步标记 `processing`）；两个进程共用同一个队列文件的情形没有测试（一个 vault 一个进程是假设，进程被杀后遗留的条目见 `BUG-HARNESS-2026-10-16-001`）；`add_batch` 的 upsert 会把待处理条目的重试计数与退避时间清零（既有行为，未改） |
| **代码位置** | `toolkits/wiki/maintenance/ai_calls.py::AiCalls/MaintainStoppedError` · `maintenance/linter.py::lint_and_maintain` · `maintenance/drift_review.py` · `maintenance/backlink_discovery.py` · `core/types.py::LintResult` · `pipeline/compiler.py::WikiCompiler.enqueue_changed_sources`（委托） · `pipeline/compiler_enqueue.py::enqueue_changed_sources/filter_changed_files` · `pipeline/queue.py::WikiIngestionQueue.list_processing_file_paths` |

### BUG-HARNESS-2026-10-15-008 · 泄漏检测的厂商前缀规则没有左边界：超过 48 个字符的连字符 URL slug（`/blog/task-management-…`）被当成 OpenAI 密钥，写入 wiki / 记忆的文本里这段 slug 被改成 `[REDACTED:openai_key]`

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-15（用 11,974 个真实代码 / 文档文件的语料核对「风险闸门拒绝」与「持久化脱敏」两条路径各自会误伤什么时发现） |
| **修复时间** | 2026-10-15 |
| **症状** | 文本里出现以 `task-`、`risk-`、`disk-`、`ask-` 等词收尾加 `sk-` 的长 slug（≥ 48 个字母数字和连字符，常见于博客 / 文档站 URL）时，`leak_detector` 的 `openai_key` 规则从词中间的 `sk-` 起匹配，`scan_persistable_content` 把 `https://example.com/blog/task-management-best-practices-for-remote-teams-in-2025` 存成 `https://example.com/blog/task-man***...2025 [REDACTED:openai_key]`，读者再也拿不回原链接；`scan_for_leaks` 对同一文本返回 `['openai_key']` |
| **关联产品** | myrm-agent-harness `core/security/detection/leak_detector.py`；`core/security/persistence/content_scan.py` 的三个档位（`MEMORY_WRITE` / `WIKI_RAW` / `WIKI_PUBLISH`）及其调用方 `toolkits/memory`、`toolkits/wiki`。server 的 `api_key_like` 风险规则读同一条起点片段 `TOKEN_START`（`app/services/risk/patterns.py`），闸门与脱敏对「token 从哪里起」的判定一致 |
| **根因** | `_API_KEY_PATTERNS` 里 33 条厂商前缀正则没有左边界，`sk-[a-zA-Z0-9_-]{48,}` 可以从任何单词的末尾两个字母起匹配；`DISTINCTIVE_KEY_PATTERNS` 的调用方（server）是在拼接时自己加边界，扫描 / 脱敏用的 `_ALL_PREFIX_STRUCTURAL` 没有 |
| **修复** | `_ALL_PREFIX_STRUCTURAL` 里的厂商前缀规则改用 `TokenStartPattern`（新模块 `token_start.py`）：前缀只在 token 起点生效。起点 `TOKEN_START` 指前面不是 ASCII 字母数字，或前面是 JSON 转义的 `\n` / `\r` / `\t`、百分号编码字节（`%20`、`%3D`）：它们以字母数字结尾，却是分隔符。以数字开头的 `telegram_bot` 用 `NUMBER_START`，只排除前面紧贴更长数字，因为令牌在 Telegram API URL 里写作 `bot<id>:…`。边界在每个匹配上检查，被拒绝的匹配之后从下一个字符继续找，所以落在被拒绝的连字符串里的真密钥仍被找到；边界不写成模式开头的后行断言，因为它会让正则引擎放弃按字面前缀跳读、逐位置尝试：写进 33 条模式时，前缀层在代码文本上每 2000 字符从 0.07 ms 变成 0.84 ms（约 12 倍）。`DISTINCTIVE_KEY_PATTERNS` 不带边界，由拼接它的 server 读同一个 `TOKEN_START` 加一次 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | 前缀型规则必须说明「前缀从哪里起算」；`sk-`、`hf_`、`AKIA` 这类短前缀都是常见单词或标识符的后缀。边界放在使用处，而不是塞进共享的正则。「前面不是字母数字」不够：粘贴的 JSON 转义文本里密钥前面是 `\n`（以 `n` 结尾），URL 编码里前面是 `%3D`，Telegram 令牌写在 `bot` 之后。只排除字母数字的第一版在 26 个形状样本上，转义换行、转义制表、`%3D`、`%20`、`%0A` 之后全部漏检，现行的粘贴形态用例会让它失败 7 例。模式开头的后行断言会关掉正则引擎的字面前缀优化，而 `redact_leaks` 每轮要扫全部上下文，所以先匹配再检查边界 |
| **回归** | 新增 `tests/core/security/detection/test_leak_detector_token_start.py`（30 例：4 个真实形状的 slug 不被标记也不被改写；17 种粘贴形态的密钥照样被遮蔽，含环境变量、JSON、`Bearer`、引号、括号、下划线之后、中文之后、转义换行 / 回车换行 / 制表之后、`%3D` / `%20` 之后、Telegram API URL 里的 `bot<id>`；6 个厂商前缀紧跟在单词后不算该厂商的密钥；前面紧贴更长数字的 Telegram id 不算令牌；以数字开头的形状恰好是 `_NUMBER_LED_KEY_NAMES`）、`test_token_start.py`（21 例：起点判定 15 例、数字起点 3 例、被拒绝的前缀吞掉整段连字符串后其后的真密钥仍被找到、33 条厂商模式对 1500 条随机拼接文本的 `search` / `finditer` / `sub` 与直接写后行断言的模式逐一一致且断言命中数大于 100、被拒绝数大于 50 以防空转、没有厂商模式匹配空串）、`test_content_scan.py` 的 slug 三档位用例 6 例、`test_distinctive_key_patterns.py` 的「共享形状不带边界」1 例；server `tests/services/risk/test_builtin_rule_precision.py` 的凭据用例增加转义换行与 `%3D` 之后的密钥。把 `_ALL_PREFIX_STRUCTURAL` 换回未加边界的表，`test_leak_detector_token_start.py` 与 `test_content_scan.py` 共 60 例中 18 例失败；换成只排除字母数字的第一版，7 例失败；现行实现 60 例通过。性能：`scan_for_leaks` / `redact_leaks` 新旧交替各跑 15 次取中位数（scan / redact）：代码 40000 字符 12.04 对 12.11 ms / 12.09 对 12.09 ms，英文文 40000 字符 10.12 对 10.12 ms / 10.19 对 10.16 ms，代码 40000 字符中夹一条 slug（有候选）12.12 对 12.11 ms / 12.41 对 12.75 ms，满是 slug 的 2000 字符 0.291 对 0.312 ms / 0.276 对 0.325 ms；前缀层单独在 1500 个 .py 文件（8.8 MB）上 31 次中位数 306.0 对 310.7 ms。引用泄漏检测 / 持久化扫描的 14 个测试文件加 `tests/core/security`、`tests/architecture` 共 7664 例通过，另有 16 例失败与本次改动无关：均为架构门，指向其他会话新增目录缺少 `_ARCH.md`、文件行数、清单与链接检查，另有 1 例因本机没有 `uv`；`core/security/detection` 目录的清单检查通过 |
| **局限** | 边界排除紧贴在 ASCII 字母数字之后的密钥（`mykeysk-…`、`123sk-…`）：厂商前缀规则不命中，熵检测与 ENV / JSON 上下文规则也不命中（实测 `mykey` 加 OpenAI 密钥，`scan_for_leaks` 返回空，`redact_leaks` 不遮蔽正文）；26 个形状样本相对旧表只在紧贴字母、紧贴数字这两种写法上漏检（`%20` 之后紧跟的 Telegram id 与 `20` 连成更长的数字，同样不命中）。没有现网日志证明用户存过被改写的链接，结论来自语料复现与读码 |
| **代码位置** | `core/security/detection/leak_detector.py::_ALL_PREFIX_STRUCTURAL` · `core/security/detection/token_start.py::TokenStartPattern` |

### BUG-HARNESS-2026-10-15-007 · 审批 / 澄清 / 目录授权的超时计时器到点后取消了自己的恢复回调，回合没有恢复；没有计时器的中断恢复后仲裁键无法重开；审批文字拦截探针对真实检查点永远判「不在等」

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-15（核对 server 一条前提「计时器到点会以 Auto-rejected 恢复回合」时，用真实调度器加会挂起的回调复现） |
| **修复时间** | 2026-10-15 |
| **症状** | ① 计时器到点认领仲裁键后，运行恢复回调；回调在第一个真正挂起的 `await` 处被取消，回合不恢复、不落库，而键已被认领，之后用户再手动答复被当成「已超时处理」拒绝；② 恢复后停在没有计时器的新中断（计划确认、浏览器接管）时，键保持「已认领」，之后的手动恢复被拒；③ `approval_interception` 的探针用 `aget_tuple` 的 `.tasks` 判断是否在等审批，真实 `CheckpointTuple` 没有该字段，探针永远返回 False，每次运行开始前白跑一次检查点读取 |
| **关联产品** | myrm-agent-harness `agent/middlewares/approval/scheduler.py`、已删除的审批文字拦截模块 `approval_interception`、`agent/_internals/agent_runtime.py`、`core/events`、`api/security.py`；server `streaming_support/hitl_timeout.py`；server 台账 `BUG-AGENT-2026-10-15-018` |
| **根因** | ① `resolve_if_first` 同时认领并取消键下登记的任务，计时器的 `_run` 也调它，此时登记的就是计时器自己，`await callback(...)` 在回调第一次挂起处收到 `CancelledError`，被「手动恢复取消」分支吞掉；原有测试的回调都不挂起；② 键只在 `schedule()` 时被清掉，没有出口；③ 测试 mock 出 `.tasks`，没有对照真实检查点的返回结构（`CheckpointTuple._fields` 为 `config, checkpoint, metadata, parent_config, pending_writes`） |
| **修复** | ① 拆成 `_claim`（只标记）与 `resolve_if_first`（标记并取消，只给手动路径）；计时器调 `_claim`，并在运行回调前把自己从登记表摘掉；② 新增 `reopen(key)`，对没有计时器的新中断重新接受一次手动答复，已有计时器时不动；③ 删除 `approval_interception` 模块、`agent_runtime.py` 里的调用点、`AgentEventType.APPROVAL_INTERCEPTED` 与 `ApprovalInterceptedEventData`，文档同步；④ `api/security.py` 新增 `MissingSemanticsBlockedError`、`PrivacyFailClosedViolationError` 的类型化再导出，server 经此导入，不再走会把类推成 `object` 的惰性顶层门面 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | 「认领」与「取消」要分开：同一个函数对手动路径取消计时器是对的，对计时器自己是自杀；链路测试要用会挂起的回调，同步 stub 暴露不了这一类问题 |
| **回归** | `tests/agent/middlewares/approval/test_scheduler.py` 20 例通过，新增 5 例；把计时器的认领临时换回旧的 `resolve_if_first`，其中 3 例失败（3 failed、17 passed），还原后 20 例通过；harness 相关目录（`tests/agent`、`core`、`api`、`architecture`、`unit`、`goals`、`sub_agents`、`integration`）在工作区 23380 通过、33 失败、15 跳过，33 例都不在本条的文件里（`test_skill_manage_lock` 3 例 HEAD 上同样失败；委派 / 子代理配置 / 隐私上下文 12 例由他人未提交的改动引起；架构门禁 18 例来自他人新增目录与行数基线）；把「HEAD + 本条改动」导出到独立目录跑 `tests/agent/middlewares`、`tests/core/events`、`tests/architecture`：7938 通过、10 失败，10 例都是架构门禁，原因是他人新增的目录缺 `_ARCH.md`、分发清单与行数基线，以及导出目录没有 `uv` 与虚拟环境 |
| **局限** | 没有现网日志证明计时器到点恢复从未成功过，结论来自读码与真实调度器复现；server 钉的 harness 版本是 `0.1.0rc5`，server 现在调用 `reopen` 并不再导入已删除的类型，两边必须一起发版并同步锁文件 |
| **代码位置** | `agent/middlewares/approval/scheduler.py::_run/_claim/resolve_if_first/reopen/_detach` · `agent/_internals/agent_runtime.py` · `core/events/types.py` |

### BUG-HARNESS-2026-10-16-002 · 更换嵌入模型后的「迁移」从没真正迁过任何记忆：孤儿集合检测打在没有该方法的包装对象上永远为空，对话集合读不出数量，迁移又走丢失身份与归属的导入通道，失败还被记成「跳过」

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-16（复核「重索引」的对外宣称时，把它在真实嵌入式 Qdrant 上从头跑一遍：旧模型写入记忆、换新模型、调 `reindex_from_orphans`；此前的用例全部是模拟存储，从未验证过迁完的记忆是不是原来那一条） |
| **修复时间** | 2026-10-16 |
| **症状** | 更换嵌入模型后，新模型的集合是空的，召回搜不到旧记忆；设置页的迁移入口在旧实现里要么不出现，要么点了返回 `migrated=0 skipped=0 failed=0`，没有任何报错 |
| **关联产品** | myrm-agent-harness `toolkits/memory/_manager/reindex.py`；`toolkits/vector/qdrant/store.py::_with_retry`；server 的迁移后台运行与状态接口、前端设置页的迁移提示见 `BUG-AGENT-2026-10-16-006` |
| **根因** | ① 检测打错对象：`MemoryManager._vector` 是 BM25 稀疏镜像包装（`BM25SparseIndexStore`），它只暴露协议面，没有 `list_collections` / `get_collection_info`；旧实现对它调用后抛 `AttributeError`，被 `except Exception` 吞成一条警告并返回空列表，于是永远检测不到孤儿集合（红灯运行的日志：`'BM25SparseIndexStore' object has no attribute 'list_collections'`）；② 对话集合读不出数量：该集合用命名向量（`raw` + `summary`），`get_collection_info` 对它返回空，数量被当成 0 而跳过；③ 迁移通道丢身份（读码结论，红灯用例被 ① 挡在前面，没有单独复现）：旧实现把每条文档去掉 `id` 与向量后交给 `import_memories`，后者再丢弃 `id`，按序列化模型解析、重新生成 id 并再过去重，迁出来的是一条新 id 的新记忆，而不是原来那一条；归属范围在载荷里是平铺的 `primary_namespace` / `namespaces` 键，模型解析要的却是 `scope` 对象，按读码判断归属带不过去（未单独复现）；语义 / 情景的类型转换器也不读 `tags`，经类型化往返标签会丢；④ 失败记账不诚实：读取失败吞掉异常后返回已读到的一部分，其余被算成「跳过」，前端据此照样清除提醒；⑤ 第一次迁移进新模型时，新模型的 `_bm25` 稀疏镜像集合还不存在（要等第一次 BM25 查询触发回填），每个批次的镜像写入都被 `_with_retry` 当成瞬时错误退避重试 0.5 s + 1.0 s 才失败开放，2000 条的迁移里有 40 次、共 30.0 s 白等 |
| **修复** | `_manager/reindex.py` 重写：包装对象先经 `unwrap_sparse_mirror` 取回真实存储作目录；数量用 `count()`（命名向量集合同样可读）；迁移按页读取旧集合，语义与情景记忆保持原载荷（id、归属、置顶、标签、重要性、访问次数、评分、创建 / 更新时间）逐字复制，只换成新模型从内容重新嵌入的向量，批量写入新模型集合；对话记忆经 `store_conversations_batch` 重嵌 `raw` 与 `summary` 两个命名向量；写入前按 id 过滤新集合里已存在的条目，所以重跑只补缺、不覆盖迁移之后用户新改的记忆；空内容跳过、不嵌入；读取失败时把尚未读到的部分计入失败（不再算跳过），嵌入或写入失败整页计入失败，其余类型 / 页不受影响，计数只在成功后累加；旧集合在这一版里原样保留作为退路（此后改为搬家，见 `BUG-HARNESS-2026-10-16-006`）；`_with_retry` 对「集合不存在」立即抛出，不再退避（等待不会让集合出现，包装层本来就把这类错误当作失败开放） |
| **反复次数** | 第 1 次发现 |
| **踩坑** | ① 「功能存在、接口通、前端有按钮」不等于它能用：此前的结论来自读码与模拟存储用例，我自己没有把迁移在真实向量库上跑过，才会把它写成已具备的能力；② 吞异常 + 返回空列表会把「打错对象」伪装成「没有需要迁移的数据」，三个计数全是 0 看上去就像成功；③ 余弦集合存的是单位向量，断言向量要和归一化后的期望比较，不能和原值比；④ 嵌入式 Qdrant 冷启动要十几秒，测试存储做成模块级共享、按集合前缀隔离；⑤ 重试原语对「确定性错误」也退避，会把任何先于回填的写入拖慢 1.5 s，这类等待只有统计重试日志才看得出，墙钟被机器负载淹没 |
| **回归** | `tests/toolkits/memory/test_reindex_migration.py`（现为 `tests/toolkits/memory/model_switch/test_reindex_migration.py`）16 例，全部跑在真实嵌入式 Qdrant（两种维度：旧模型 8 维、新模型 12 维）上：身份 / 归属 / 置顶 / 标签 / 重要性 / 创建时间原样保留；向量来自新模型、旧集合不动；重跑只补缺且不再嵌入；迁移之后用户改过的记忆不被覆盖；分页批次 `[100, 100, 30]`；空内容跳过；无孤儿时无操作；进度事件；经 BM25 包装的估算；嵌入失败 / 写入失败 / 读取中途失败的计数，失败的下一次重跑能补上；情景记忆不触图；对话记忆两个命名向量都重嵌且载荷保留；迁移期间没有任何「Retrying in」日志。红灯：对旧实现，迁移用例全部得到 `(0, 0, 0)`；去掉 `_with_retry` 的修复后「不退避」用例失败。`tests/toolkits/vector/test_qdrant_store.py` 新增 3 例（瞬时错误仍会重试并恢复；两种 Qdrant 的「集合不存在」文案立即抛出且不休眠，去掉修复后失败） |
| **实测** | 2000 条语义记忆、每次嵌入调用模拟 0.2 s（20 批）、真实嵌入式 Qdrant：修复 `_with_retry` 前一次迁移墙钟 40.9 s（嵌入下限 4.0 s + 40 次退避共 30.0 s + 其余），修复后 5.4 s（嵌入 4.0 s、退避 0 次、其余 1.4 s、CPU 0.67 s）；已全部存在时重跑 1.4 s、0 次嵌入调用。测量期间机器平均负载 70–170，墙钟绝对值偏高且波动（修复前另两次 57.4 s、72.7 s），确定的是退避次数与总时长：40 次 / 30.0 s → 0 次 |
| **局限** | ① 旧集合保留，重跑时它们全部显示为「已跳过」（已由 `BUG-HARNESS-2026-10-16-006` 解决：迁移改为搬家，旧集合清空后删除）；② 更换模型时不自动迁移，用户需在 设置 > 模型 > 嵌入 里点迁移；③ 对话集合只在嵌入式 Qdrant 上验证，没有连远程 Qdrant 跑；④ 旧的有问题的迁移如果在某些环境里曾写入过部分副本，本次没有清理；⑤ 「集合不存在」用文案里的 `not found` 判断，与 BM25 包装层已有的判断一致，换底层库后需要同步；⑥ 迁移前的新模型镜像缺失只是「不退避」，镜像本身仍由第一次 BM25 查询触发的回填补齐 |
| **代码位置** | `toolkits/memory/_manager/reindex.py::detect_orphan_collections/reindex_from_orphans/_migrate_orphan/_migrate_batch/_write_migrated` · `toolkits/vector/qdrant/store.py::_with_retry` |

### BUG-HARNESS-2026-10-15-004 · 体检页的两条红色是假的：网络探针被一个被屏蔽的地址拖到 5 秒上限后报「没有网络」，macOS 上交换区用满就报「系统即将抖动」；向量库探针的异常原文也从技术详情里丢了

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-15（逐项核对 `/api/v1/health/doctor` 实际返回，对 HEAD 的探针逐个计时 / 对照系统计数器，不靠读代码推断） |
| **修复时间** | 2026-10-15 |
| **症状** | ① 网络探针按顺序请求三个地址、每个等 5 秒，而管理器给每个探针的上限也是 5 秒：第一个地址（`cloudflare-dns.com`）在这台机器上不通，探针还没走到备用地址就被管理器截断，体检显示「Internet is not available」，实际网络是通的；② `SystemExhaustion` 只看交换区占用，macOS 的交换文件按需增长，占用接近 100% 是常态，体检却报红色「Swap/Pagefile is critically saturated. System thrashing imminent.」；③ 超时 / 崩溃的兜底报告写着「component may be deadlocked」「Try restarting the application」，一次超时并不能说明死锁，也不该劝人重启；④ 向量库探针的 `detail` 在上一轮被改成固定句子，异常原文只进日志，支持包里看不到失败原因 |
| **关联产品** | myrm-agent-harness `observability/diagnostics`（`probes.py`、`manager.py`、`system_exhaustion.py`、`vector_probe.py`、`desktop_probe.py`） |
| **根因** | ① 备用地址按顺序尝试，总预算没有和管理器的单探针上限对齐；② 把「交换区占用高」直接等同于「内存紧张」，没有第二个独立证据；③ 兜底文案按「最坏情况」写，没有区分「没得出结论」和「确认损坏」；④ 上一轮把「用户可见文案不带技术细节」和「技术详情字段」混为一谈，连 `detail` 一起改掉了 |
| **修复** | ① `check_network_health` 改为错峰竞速：第一个地址先发，慢于 1 秒才开下一个，前一个失败则立刻开下一个，第一个成功即取消其余；单请求 2.5 秒，探针自己的预算为 `DIAGNOSTIC_HOOK_TIMEOUT_S - 1`（4 秒），保证由探针自己给出结论；健康网络仍只发 1 个请求；② 交换区 ≥90% 的失败需要同时满足可用内存 <10%（读不到可用内存时仍按严格结论），否则落入原有的「交换区使用率高」警告，原因文案改为与证据一致；快照改成 `TypedDict`（同时消掉 8 个 `float(object)` 的 mypy 错误）；③ 超时报告改为「A system check did not finish in time.」，不再断言死锁、不再建议重启；④ 向量库探针的异常原文回到 `detail`（`message` / `fix_suggestion` 仍不带后端名与异常），`desktop_probe` 与 `_ARCH.md` 里指向具体产品路由 / 界面的措辞改为宿主无关 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | ① 单看「探针单独跑 2.7 秒能通过」会得出「网络探针本来就没问题」的错误结论，必须在管理器的 5 秒限制下并发跑；② 在全新进程里第一次跑体检会得到一堆「没有在时限内完成」，原因是 `check_hook_health` 在探针里同步导入 `agent.hooks.executor`（约 5.5 秒，同一事件循环被阻塞，所有探针的挂钟超时一起走完），不是本条的网络问题，要先预热模块再测；③ 把 `memory_short` 的默认值写成「内存充足」会让读不到内存的机器静默降级，所以默认取严格结论 |
| **回归** | 新增 `tests/observability/test_network_probe.py`（6 例：首个地址挂起时备用地址仍通过；首个地址立刻失败时不等错峰间隔；健康网络只发 1 个请求；全部失败；全部过慢时在自己的预算内给出结论且不留任务；预算低于管理器上限的不变式）；`test_diagnostics_manager.py` 钉住超时报告不含「deadlock」「restart」；`test_system_exhaustion_diagnostics.py` 新增「交换区用满 + 内存充足 → 警告」「交换区用满 + 内存读不到 → 仍为失败」，原有失败用例改为显式给出短缺内存并钉住 `measured`；`test_vector_probe.py` / `test_probes.py` 钉住异常原文只在 `detail` 与日志里 |
| **实测** | 网络（同一台机器，管理器 5 秒限制下）：改前体检为失败，改后预热进程里连续 2 次完整体检 Network 均通过，整套体检 1.35 / 1.56 秒；单探针 1.70–2.71 秒（gstatic 在错峰 1 秒后接手）。交换区：改前 `SystemExhaustion` 红色失败，改后同一台机器上为警告（交换区 93.6%，24.9/26.6 GB，可用内存 26.0%）；8 秒内 `vm_stat` 换出计数 +0、换页计数 +24（累计 1066 万），没有抖动迹象 |
| **局限** | ① 全新进程第一次体检仍会因探针里的同步导入被阻塞而出现「没有在时限内完成」（实测 11.7 秒，随后几次 1.4 秒）：服务进程启动时已加载这些模块，不受影响，只有「新进程里直接调 `run_all_diagnostics`」的宿主会遇到，本条未改；② 交换区与可用内存的判据只在这一台 macOS 机器上取证，Linux / Windows 沿用同一规则，没有实机数据；③ 网络探针在被降级到更慢地址时最长要 1–2 秒，换来的是不再误报；④ 运行中的服务进程需要重启才会加载新代码，本条的实测来自同一批函数的进程内调用，没有重启共享的开发服务做在线复测 |
| **代码位置** | `observability/diagnostics/probes.py::check_network_health/_first_reachable_url` · `manager.py::DIAGNOSTIC_HOOK_TIMEOUT_S/_safe_execute_hook` · `system_exhaustion.py::check_system_exhaustion/SystemExhaustionSnapshot` · `vector_probe.py::check_qdrant_health` |

### BUG-HARNESS-2026-10-15-003 · wiki 的两个「相关概念」写入方互不相认：编译后的反向链接把 `## Related Concepts` 之后的整段内容删掉，维护期的链接发现把草稿 / 已拦截页面改回已发布，并且每次只问同样的前 20 页

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-15（#140 链接图谱专项，对 HEAD 两个写入方用桩 LLM 逐条做探针，不靠读代码推断） |
| **修复时间** | 2026-10-15 |
| **症状** | ① `postprocess.generate_backlinks` 用 `\n+## Related Concepts\n[\s\S]*$` 整段替换，该标题之后的所有章节（手写的「来源」「时间线」等）被一并删除；② `BacklinkDiscoveryMixin._discover_connections` 经 `publish_concept_article` 回写，`ensure_published_frontmatter` 把 `draft` / `blocked` 页面改成 `published`，等于绕过人工审核；③ 候选页固定取 `list_concepts()[:20]`，30 页的库每次都只问同样的 20 页，后 10 页永远没有机会；④ 候选与建议只用裸文件名，`rust/overview` 与 `go/overview` 撞名，建议按小写字符串去重，条目追加到文件末尾（而不是 Related 章节），计数还把 lint 之后会判为断链的链接算进去；⑤ 摘录 `content[:1500]` 把 frontmatter 算在内，带长 frontmatter 的页面几乎看不到正文；⑥ 读文件到写文件之间隔着 `await llm.ainvoke`，期间人手编辑的内容被覆盖；⑦ 只读的联邦公共挂载页面与模板页也被当作候选改写；⑧ 手写的非规范文件名（`Alpha Notes.md`）经发布路径落到 `alpha-notes.md`，原文件不变、多出一份副本；⑨ `related_concepts` 来自读取不可信原文的模型输出，名字里带换行或 `]]` 时被原样写进页面，可以植入章节（红灯用例里植入的标题真的出现在页面里），模型把页面自己列为相关概念时也照写；⑩ vault 里只要有一页不是合法 UTF-8，链接解析器的整库扫描（`core/link_resolver.py::scan_concept_pages` 只捕获 `OSError`）就抛 `UnicodeDecodeError`，经它的调用整体失败（本批的合并与发现已复现；边提取与 lint 也经同一解析器，按代码路径判断，未单独复现） |
| **关联产品** | myrm-agent-harness `toolkits/wiki`（`core/related_links.py`、`maintenance/backlink_discovery.py`、`pipeline/postprocess.py`、`pipeline/cognitive_map/writer.py`、`core/frontmatter_contract.py`、`retrieval/fts_write.py`）；server `/api/v1/wiki/maintain` 的 `backlinks_created` 语义 |
| **根因** | 同一个章节有两个互不知情的写入方，各自手写一套「找章节 / 去重 / 追加」：一个用贪婪正则、一个用文件末尾追加；链接身份各自按字符串比较，没有走已有的 `WikiLinkResolver`；发现流程没有范围概念（谁能被改写、谁能被推荐），也没有覆盖进度，取前 20 页当作「全库」 |
| **修复** | ① 新增 `core/related_links.py::merge_related_links`，成为 `## Related Concepts` 的唯一写入方（基于已有的 `section_contract` 取 / 换章节正文，`WikiLinkResolver` 判同一页面，只并集、不删除、无新增则不写）；`generate_backlinks` 与发现流程都走它，`cognitive_map/writer.py` 的私有 `_concept_wikilink_name` 改用 `link_resolver.concept_link_name`；② `frontmatter_contract.resolve_publish_status` 成为页面状态的唯一读取方（`fts_write` 的索引闸门同源），发现流程只处理 `published` 的本地非模板页面；③ 覆盖轮转：游标 `link_discovery_cursor` 存在 `.metadata.json`（`save_metadata` 改为合并写，编译不会冲掉它；该文件本就被 vault_git 忽略、不进 vault 归档；一个只含游标的文件对各读取方等同于没有该文件：`pipeline/compiler.py:526` 的变更筛选得到空哈希表、全部算变更，`maintenance/stale_summary.py:48` 与 `pipeline/cognitive_map/snapshot.py:53` 缺字段时返回空结果，逐个读代码核对，未单独加用例），每轮仍然只问 20 页，下一轮接着问，页数 ≤ 20 时不留游标；模型一页都没答出来（宕机）不推进，页面自身写不进去（frontmatter 无效）不拖住轮转；④ 候选改用库内相对路径（`rust/overview`），摘录取去掉 frontmatter 的正文，计数改为实际新增且发布结果为 `PUBLISHED` 的链接数（`backlinks_created` 同步改为新增链接数，原先是写入的全部相关名）；⑤ 写之前重读页面并在同一事件循环里不 await 地合并写出，保住 LLM 调用期间的人手编辑，页面被删则不重建；⑥ 发布路径与原文件不是同一个文件时只被链接、不被改写（`samefile` 判断，大小写不敏感文件系统上仅大小写不同的名字仍就地改写）。⑦ `merge_related_links` 丢弃不可能是单行 `[[...]]` 目标的名字（带换行、方括号）并且不把页面列为自己的相关概念；⑧ `scan_concept_pages` 与发现的页面扫描一并跳过无法解码的页面；⑨ 游标写盘失败只记警告、下一轮重问同一批，不让维护整体失败；⑩ 「发布路径是否就是原文件」的检查只计算路径、不创建目录（`get_concept_file_path` 会 `mkdir`，扫描手写文件夹 `Work Notes/` 时会凭空多出 `work-notes/`）。系统提示词文本一字未改，只是数据词汇变了（候选是路径键、标题是 `## Article: {key}`） |
| **反复次数** | 第 1 次发现 |
| **踩坑** | ① 第一版把「每个批次全部失败」都当成宕机、不推进游标，结果一批 frontmatter 无效的页面会让轮转永远停在第一批，改为只统计「模型没有答出来」；② 第一版的越界保护用 `Path ==`，macOS / Windows 上 `Beta.md` 对 `beta.md` 会被误跳过，改为 `samefile`，并让测试在两类文件系统上都有判别力（拿掉保护、改回 `==` 各让一条用例失败）；③ 先写的模板页用例对旧代码也能通过（空转），加了「只问 alpha、beta」「提示里没有 note」之后才真正卡住旧行为；④ 一次突变检查中用了错误的 `git show` 路径（harness 是独立仓库，应为 `HEAD:src/...`），重定向把两份工作文件截断，靠事先备份恢复并重做，之后一律在临时副本上做突变；⑤ 首次提交后的对抗式复核又用红灯用例复现并修掉三处自己引入的缺陷：无法解码的页面让整轮发现抛出（旧版逐页 `try/except` 能扛过去）、越界检查为了算路径创建了多余目录、游标写盘失败会让整个维护失败；第四处（解析器扫描不吞 `UnicodeDecodeError`）是既有缺陷，因为新代码依赖解析器才暴露 |
| **回归** | 新增 `tests/toolkits/wiki/test_related_links.py`（14 例：合并语义 6 例、不可作链接目标的名字 5 例、自指 1 例、`generate_backlinks` 2 例）、`test_backlink_discovery.py`（20 例）与 `test_backlink_discovery_rotation.py`（6 例，共用 `discovery_support.py`；覆盖：Related 章节落点与后续章节保留、人手文本保留、同名页面无断链、拼写不同只算一条、已链接不算、被发布闸门拒绝不算、草稿 / 拦截页不被改写也不被推荐、模板与公共挂载在范围外、非规范文件名只被链接、大小写文件名不生副本、轮转 30 页两轮覆盖全库、小库不留游标、游标在 `save_metadata` 后保留、宕机不推进、写不进去的页面不拖住轮转、游标写盘失败不让维护失败、摘录不含 frontmatter、调用期间的编辑与删除、无法解码的页面被跳过、单页库不问模型、非列表回复只加有效名字、手写文件夹不产生新文件夹）；`test_link_resolver.py` 增加无法解码页面被扫描跳过一例；`test_frontmatter_contract.py` 增加 `resolve_publish_status` 参数化用例；旧用例按新语义调整（`[[Concept Beta]]` 变为 `[[concept-beta]]`、发布结果的桩改为 `ArticlePublishOutcome.PUBLISHED`、`extract_and_upsert_edges` 的桩由 `AsyncMock` 改为 `MagicMock`，它本来就是同步函数）。突变检查：把两个生产写入方换回 HEAD 版，当时已有的 25 条新用例中 15 条失败；之后追加的三条各自拿掉对应保护后失败。`tests/toolkits/wiki` 除真实 LLM 的 `test_sidecar_integration.py` 外 931 项通过；ruff、mypy 对触及文件通过；三个触及模块（`related_links`、`backlink_discovery`、`postprocess`）行覆盖率 100%（复核补用例前为 97%；`backlink_discovery` 里一段永远走不到的 `except (TypeError, ValueError)` 已删，`parse_llm_json_list` 的契约是失败返回 `None`）；server `tests/api/wiki` 与 `tests/services/wiki`（不含真实 LLM）409 项通过、3 项失败，与 roadmap 第六批记录的三个既有安全拦截失败是同名用例（`test_wiki_clip_security_blocked_job_response`、`test_import_folder_blocks_credential_content`、`test_import_urls_security_blocked`），未在 HEAD 基线上重跑 |
| **实测** | 桩 LLM、每轮调用次数 20 不变；提示总量（字符 / 4 估算）30 页 7592→7355、100 页 12142→11905、1000 页 70642→70405，略降；1000 页的库每轮多出的页面扫描约 10 ms→82 ms，相对 LLM 往返可忽略；`generate_backlinks` 每批多一次解析器的整库扫描：100 页 3→10 ms、1000 页 5→57 ms、5000 页 2→294 ms，相对编译 LLM 往返可忽略；提示缓存前缀不受影响（发现调用是两条消息的独立 `ainvoke`）；真实 LLM（`.env.test` 的基础模型）对 14 页合成库连跑 3 轮的健全性检查：旧版新增链接 22 / 4 / 1 条，新版 21 / 1 / 1 条，增量都收敛，抽查 4 页的链接合理（`llm-prompt-caching` 与其余主题无关，两版都没有给它加链接）；每个版本各跑一次、模型输出非确定，不构成统计结论 |
| **局限** | ① 候选名单仍是全库列表，随页数线性增长（每轮仍然只有 20 次调用）；② 根因在 `publish_concept_article` 写到规范化路径，本条只在发现流程里挡住，其他调用方不变；③ Related 章节只并集：过期链接不会被清除，旧版本写在别处的条目不迁移；④ 没有跨进程锁（调用期间的编辑保护只覆盖同一事件循环）；⑤ 标题变体（大小写、CRLF、文件末尾无换行的标题）按既有的章节契约处理，未单独放宽；`replace_section_inner` 会吃掉被替换块前后的空行，仅影响排版；⑥ claims / methods 页面仍在发现范围内，没有实证危害所以未排除；⑥′ 每次 FULL 维护只问 20 页：200 页的库要 10 次 FULL 维护才走完一轮（按周执行即 10 周）；⑦ `test_sidecar_integration.py` 是真实 LLM 用例，依赖 LLM 输出，同一份 HEAD 代码上 7 次中也有 2 次失败，与本条无关；`tests/integration/llm_extraction/test_wiki_compile_e2e.py` 未跑 |
| **代码位置** | `toolkits/wiki/core/related_links.py::merge_related_links` · `maintenance/backlink_discovery.py::_discovery_pages/_next_batch/_publishes_in_place/_suggest_links/_add_links` · `pipeline/postprocess.py::generate_backlinks/save_metadata` · `core/frontmatter_contract.py::resolve_publish_status` |

### BUG-HARNESS-2026-10-15-001 · 只读研究租约的默认白名单是 7 个没有任何内置工具使用的名字，挂租约的运行里所有真实工具一律被拒；撤销后租约记录永远留在管理器里；围栏只有整轮开关，宿主没法只给常驻循环派生的任务打标

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-14（核对 server 定时任务挂租约之后的运行时绑定时，直接对 HEAD 的租约管理器做探针） |
| **修复时间** | 2026-10-15 |
| **症状** | ① `ReadOnlyLeaseRecord.allowed_tools` 与 `ReadOnlyLeaseManager.grant_lease` 各存一份默认白名单（`read_file`、`web_search`、`read_web_page`、`fetch_doc`、`grep_search`、`list_dir`、`view_image`），没有一个是内置工具名，租约又是默认拒绝，所以挂了租约的运行里 `file_read_tool`、`grep_tool`、`glob_tool`、`web_search_tool`、`web_fetch_tool` 全部被拒；② `blocked_side_effects` 的 10 个名字（`write_file`、`run_shell`、`database_execute`、`send_webhook` 等）多数不是真实工具名，拒绝本身来自默认拒绝，这张表只决定拒绝文案；③ `revoke_lease` 把记录改成 REVOKED 后仍留在字典里，每个结束的会话留下一条；④ 宿主想把「某段代码里派生的任务」标为不可信时，只有 `set_untrusted_ingress(True)` 这种整轮开关，用在常驻的消费循环里会连循环自己一起打上 |
| **关联产品** | myrm-agent-harness `core/security/readonly_research_sandbox` · `agent/security/guards`（`untrusted_ingress_fence.py`、`taint_tracker.py`）· `api/security`；server `BUG-AGENT-2026-10-15-002` |
| **根因** | ① 白名单按想象中的通用工具名手写，测试里用的是同一批名字，所以一直通过，没人对照过安全注册表；② 拒绝文案用的第二张手写表，与注册表的 `is_destructive` 重复；③ 撤销被当成「改状态」而不是「忘记」；④ 围栏只提供了整轮开关，没有按块限定的版本 |
| **修复** | ① `types.py` 新增单一常量 `DEFAULT_READ_ONLY_TOOLS`（`file_read_tool`、`grep_tool`、`glob_tool`、`web_search_tool`、`web_fetch_tool`），记录类型与管理器共用，门面导出；② 删除 `blocked_side_effects`，拒绝文案改看 `resolve_safety_metadata(tool).is_destructive`（注册表标为破坏性的工具显示「physically stripped」，其余显示「not in the safe read-only whitelist」，文案本身未改）；③ `revoke_lease` 弹出记录；④ 新增 `untrusted_ingress_scope()` 上下文管理器：只标记块内及块内派生的任务，退出（含抛异常）时还原先前状态，经 `api.security` 导出；`taint_tracker.record_ingress_taint` 的 docstring 写明运行开始时跟踪器会被重建，回合前登记不会保留 |
| **反复次数** | 第 1 次发现 |
| **踩坑** | ① 手写的放行清单必须有一个把它钉在注册表上的测试，否则改名或改标志不会有人发现；② 默认拒绝的策略下，白名单写错的后果不是「漏拦」而是「全拒」，只断言「写工具被拒」的测试发现不了；③ 回合前的污点登记会被运行开始时的 `reset_all_guards()` 清掉，围栏的 ContextVar 不会，所以不可信标记只能走围栏 |
| **回归** | `tests/unit/test_readonly_research_sandbox_suite.py` 新增 `test_default_read_only_tools_stay_in_sync_with_the_safety_registry`（五个名字都是内置工具、只读、非破坏性），生命周期用例改用真实工具名，覆盖「五个默认工具放行、注册表标为破坏性的工具按 physically stripped 文案拒绝、其余非白名单工具按白名单文案拒绝、撤销后记录被忘记、自定义白名单替换默认值」；`tests/agent/middlewares/approval/test_approval_readonly_research_lease.py` 改用真实工具名；`tests/agent/security/guards/test_untrusted_ingress_fence.py` 新增 `untrusted_ingress_scope` 四例（退出还原、块抛异常也还原、整轮已标记时块内外都保持、块内派生的任务带围栏而派生者不带）与 `test_run_start_clears_ingress_taint_but_keeps_the_fence`（`reset_all_guards()` 清掉回合前登记的污点、围栏保留）；这三个文件所在的 `tests/unit/test_readonly_research_sandbox_suite.py`、`tests/agent/middlewares/approval`、`tests/agent/security/guards` 共 371 通过；触及文件 `ruff check` 无问题 |
| **局限** | 租约的拒绝是否生效依赖宿主把 `approval_session_key` 绑到租约键上（server 在 `BUG-AGENT-2026-10-15-002` 绑定）；租约到期后默认放行（既有行为，TTL 由宿主按运行超时加余量设置）；CoW 临时层与快照在生产代码里没有调用方（`facade.py` 只被测试使用），本条未涉及；`readonly_research_sandbox` 下的 `facade.py`、`ephemeral_cow_overlay.py` 与 `readonly_lease_manager.py::get_lease` 的签名没有按 `ruff format` 折行，属本条之前的状态，未动 |
| **代码位置** | `core/security/readonly_research_sandbox/types.py::DEFAULT_READ_ONLY_TOOLS` · `readonly_lease_manager.py::grant_lease/revoke_lease/evaluate_tool` · `agent/security/guards/untrusted_ingress_fence.py::untrusted_ingress_scope` · `agent/security/guards/taint_tracker.py::record_ingress_taint` · `api/security.py` |

### BUG-HARNESS-2026-10-15-002 · 体检的向量库探针每次都拿一份临时内存库自检：真实的嵌入式库因数据目录被锁、不可写或磁盘满而退化成纯内存后，体检、运维快照、支持包仍报「向量库健康」，之后写入的记忆重启即丢

| 字段 | 内容 |
| --- | --- |
| **状态** | FIXED |
| **发现时间** | 2026-10-15（审计默认挂载的记忆栈时，把探针与 `create_embedded_store` 的退化分支对读，两者没有任何联系） |
| **修复时间** | 2026-10-15 |
| **症状** | ① `create_embedded_store` 打不开数据目录时退化成 `:memory:` 库，只记一条 ERROR 日志；② `check_qdrant_health` 固定初始化 `local_path=":memory:"` 的一次性库、从不碰真实目录，所以这种状态下 `VectorDB` 一律返回 pass 与 `Vector database is healthy.`；③ 用户在 `/api/v1/health/doctor`、`/api/v1/ops/snapshot` 与支持包里看到的是「健康」，记忆其实只在内存里，下次启动消失 |
| **关联产品** | myrm-agent-harness `observability/diagnostics`（`vector_probe.py`、`probes.py`）· `toolkits/vector/qdrant`（`factory.py`）；server 三个读取方：`app/api/health/router.py::system_doctor`、`app/services/ops/snapshot_service.py`、`app/services/system/support_bundle_service.py`，均经 `collect_health_snapshot` / `run_all_diagnostics`，无需改动 |
| **根因** | 探针只验证「库能不能初始化」，没有验证「真实的库是不是正在用」；每个 store 能读自己的 `is_persistent`（`MemoryManager.vector_is_persistent` 据此透出，记忆指挥中心据此告警，但该面板只在 Memory Labs 打开时可见），而体检探针手里没有真实 store，只有自己新建的一次性库，工厂也没有按目录列出退化库的接口 |
| **修复** | ① `factory.py` 新增 `embedded_fallback_paths()`（只列退化库的数据目录，显式要求的 `:memory:` 不算退化；后缀提成 `_FALLBACK_KEY_SUFFIX` 常量，读写同源），`qdrant/__init__.py` 导出；② 探针迁到新文件 `vector_probe.py`（`probes.py` 行数预算），先查退化表：有退化库就直接 FAIL，文案面向用户（「新记忆没有被永久保存」+ 退出其他副本、检查可写与磁盘空间、重启应用），带 `code=ERR_VECTOR_STORE_ON_MEMORY_FALLBACK`，体检页按 code 取 `settings.systemHealth.doctor.errors` 下六个语言文件的译文，`measured` 写退化库个数，原有的一次性库自检保留在后面；③ `probes.py` 仍按原顺序注册同一个函数，对外名字不变；④ 探针通过 / 失败文案不再出现后端名与原始异常（异常写日志），同批删除永远通过的 `GraphEmbedding` 探针（提交 `441f874fc`） |
| **验证** | `tests/observability/test_probes.py` + `test_probes_extended.py` + `tests/toolkits/vector/test_qdrant_factory.py` 共 89 项通过（2026-10-15）；新增两条：`TestCheckQdrantHealth::test_fallback_store_returns_fail_even_when_the_throwaway_probe_would_pass`（有退化库时 FAIL，且不再创建一次性库）、`test_embedded_fallback_paths_lists_only_fallback_stores`（正常落盘库与显式 `:memory:` 都不列出，evict 后清空）；另在真实被锁目录上做过端到端复现：另一个 `QdrantClient` 持有数据目录的文件锁、工厂退化为内存库时，修复前的探针返回 pass 与 `Vector database is healthy.`，修复后返回 fail、`measured` 为 `1 vector store(s) on the in-memory fallback`，该场景已入库为 `tests/observability/test_vector_probe.py::test_probe_fails_while_another_client_holds_the_data_directory_lock`（工厂与探针都不打桩） |
| **局限** | ① 体检 / 运维快照 / 支持包只在被请求时才检查；默认库退化时 Web UI 另有常驻 toast（server 的 `system_status.vector_degraded`，只覆盖默认库，不覆盖 harness 为隔离运行自建的库）；② 退化表是本进程的，别的进程里的退化看不到；③ 退化记录随进程存在，目录恢复后要重启应用（或宿主调用 `evict_embedded_store`）才会消失，与文案里的「重启应用」一致；④ 远程 Qdrant（`create_remote_store`）仍不被探测，探针对它仍只做库可初始化的自检；⑤ 体检页只按 code 翻译 `message`，同一条报告的 `detail` 与 `fix_suggestion` 在页面上仍是英文原文（体检页对所有探针都是这样） |
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
