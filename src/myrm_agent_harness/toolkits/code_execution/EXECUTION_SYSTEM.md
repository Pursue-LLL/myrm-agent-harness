# Execution System 系统设计

## 设计目标

为 AI Agent 提供安全、高性能的代码执行环境。采用 **Agent-in-Sandbox** 架构：Agent 与代码在同一容器内执行，消除远程执行的延迟和复杂性。

---

## PTC 家族（Programmatic Tool Calling）

**PTC** = 用 Python 脚本在沙箱里程序化调用工具/能力，**中间结果不灌回 LLM context**。

Myrm 有两个 PTC 分支（同族、不同实现路径）：

```
PTC（程序化工具调用）
├── MCP PTC — MCP schema 超出 Turn1 预算时，脚本批量调 MCP
│     路径：skill_select → file_read(/mcp/...) → bash_code_execute → skills.*/tools.* IPC
│     触发：普通聊天（用户无感）
│
└── DW PTC — 单会话大任务，脚本并行 spawn 子 agent
      路径：Dynamic Workflow → inject_ptc → ptc/ Workflow RPC（spawn_subagent + notify + llm_query）
      触发：用户开「工作流」模式
```

| 分支 | 脚本调什么 | 实现 | 代码锚点 |
|------|-----------|------|----------|
| **MCP PTC** | MCP 工具（经 Skill 文档） | bash 沙箱 + `skills.*/tools.*` IPC | `mcp_routing.py`, `bash_code_execute` |
| **DW PTC** | 子 agent 编排 + 进度 | `ptc/` Workflow RPC 桥 | `dynamic_workflow/`, `inject_ptc_for_python_execution` |

**实现边界**：

- `bash_code_execute` Turn1 **不** inject `myrm_tools` stub（CI：`test_bash_native_ptc_removed.py`）。
- `ptc/` RpcServer **仅**服务 DW PTC（`inject_ptc_for_python_execution`）。
- MCP PTC 与 DW PTC 同族，实现路径分离。

**产品对外**：仅暴露 **动态工作流（DW PTC）**；MCP PTC 为引擎内部能力。

详细 RPC 设计见 [ptc/_ARCH.md](ptc/_ARCH.md)。

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                    myrm-control-plane                       │
│            容器生命周期管理（创建/休眠/唤醒/销毁）              │
└──────────────────────────┬──────────────────────────────────┘
                           │ 容器边界
┌──────────────────────────▼──────────────────────────────────┐
│                  myrm-agent-harness (容器内)                │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                   Agent 层                            │   │
│  │  BaseAgent / SkillAgent → tools (bash/file_ops/...)   │   │
│  └──────────────────────┬───────────────────────────────┘   │
│                         │ ContextVar (get_executor)          │
│  ┌──────────────────────▼───────────────────────────────┐   │
│  │              toolkits/code_execution                        │   │
│  │                                                        │   │
│  │  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐ │   │
│  │  │ config  │  │ factory  │  │ platform │  │code_detector │ │   │
│  │  └────┬────┘  └────┬─────┘  └──────────┘  └──────┬───────┘ │   │
│  │       │            │                                   │   │
│  │  ┌────▼────────────▼─────────────────────────────┐    │   │
│  │  │              executors/                         │    │   │
│  │  │  CodeExecutor (ABC)                            │    │   │
│  │  │    └─ LocalExecutor                            │    │   │
│  │  │         ├─ execute() — Python 子进程           │    │   │
│  │  │         ├─ execute_bash() — 持久化 Bash 会话   │    │   │
│  │  │         └─ read_file/write_file/list_files     │    │   │
│  │  └────────────────────────────────────────────────┘    │   │
│  │       │                                                │   │
│  │  ┌────▼────────────────┐  ┌───────────────────────┐   │   │
│  │  │    security/         │  │    workspace/          │   │   │
│  │  │  ┌─ analyzer        │  │  Workspace + Service   │   │   │
│  │  │  ├─ blacklist       │  │  (会话文件空间管理)     │   │   │
│  │  │  ├─ validator       │  └───────────────────────┘   │   │
│  │  │  ├─ ast_parser      │                               │   │
│  │  │  └─ sanitizer       │                               │   │
│  │  └─────────────────────┘                               │   │
│  │       │                                                │   │
│  │  ┌────▼────────────────┐                               │   │
│  │  │    session/          │                               │   │
│  │  │  PersistentSession  │                               │   │
│  │  │  (长驻 Bash 进程)   │                               │   │
│  │  └─────────────────────┘                               │   │
│  └────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

---

## 核心组件

### 1. CodeExecutor（执行器协议）

统一的代码执行抽象接口，定义了 Agent 执行代码所需的全部操作：

| 方法 | 类型 | 说明 |
|------|------|------|
| `execute(context)` | 抽象 | Python 代码执行 |
| `execute_bash(context)` | 抽象 | Bash 命令执行 |
| `execute_bash_stream(context)` | 虚拟 | 流式 Bash 输出（逐行） |
| `read_file(path)` | 默认实现 | 读取文件内容（经 shell 分片读取十六进制，字节无损，不受输出脱敏与截断影响） |
| `write_file(path, content)` | 默认实现 | 写入文件（32 KiB 分片 base64，大文件不触及单参数上限，失败抛 `OSError`） |
| `list_files(path)` | 默认实现 | 列出目录文件 |
| `bind_workspace(path)` | 具体 | 绑定工作目录 |
| `close()` | 虚拟 | 异步资源清理（级联释放 Bash 会话与沙箱句柄，支持 `async with`） |

**生命周期**：`bind_workspace(path)` → 执行操作 → `close()`

**ContextVar 管理**：所有工具通过 `get_executor()` / `set_executor()` / `require_executor()` 共享 executor 实例，避免 LangGraph checkpoint 序列化问题。

### 2. LocalExecutor（本地执行器）

`CodeExecutor` 的本地实现，直接在当前进程环境中执行代码：

- **Python 执行**：每次调用创建独立子进程，通过 wrapper script 注入模块黑名单。内置 **Actionable Diagnostic Hints** 机制，拦截 `ModuleNotFoundError` 并追加 `python -m pip install` 修复建议，引导大模型自主纠错。
- **Bash 执行**：通过 `PersistentSession` 维护长驻 Bash 进程，环境变量和工作目录跨命令保持
- **文件操作**：直接使用 `pathlib` 本地 IO，零网络开销
- **只读工作区**：当前运行绑定的 OCap 句柄不含 WRITE（如 Verifier 的 READ+EXECUTE 句柄）时，`LocalExecutor` 把该次执行视为 `readonly_workspace`：原生写/删/`mkdir` 被拒绝，Python 子进程的写入守卫与 Bash 会话的 OS 沙箱（`SandboxPolicy.writable_paths` 为空，`/tmp` 草稿目录仍可写）同时生效。只读运行使用独立的 Bash 会话（会话键带 `_readonly` 标记），不复用也不污染可写会话。Bash 工具的后台作业（`run_in_background`）同样如此：`_background_spawn.py` 默认按句柄收窄为只读并以空 `writable_paths` 生成沙箱策略。MCP 服务器等 harness 自有进程显式声明 `ExecutionContext.harness_owned=True`，不继承任何 agent 的句柄。容器内部署没有嵌套 OS 沙箱，Shell 写入不被 OS 阻止。
- **执行证据**：每次真正启动进程前（Python、Bash、Bash 流式，以及非 harness 自有的后台作业），执行器向当前 `track_execution()` 作用域写入证据（`execution_evidence.py`，ContextVar）；Verifier 的 PASS 闸门读取该证据（无证据的 PASS 不构成结论），被命令校验器拒绝的命令不计入，MCP 服务器启动不计入。证据只证明“启动过进程”，不证明验证充分：Verifier 跑一条无关命令即可满足闸门，验证质量仍取决于 Verifier 的提示词与模型。

#### Language routing (`code_detector` + `python_extractor`)

`toolkits/code_execution/code_detector.py` classifies incoming shell input as Python or Bash before execution. It delegates ``python -c`` quote-aware extraction to `python_extractor.py` (SSOT). `agent/meta_tools/bash/BashExecutor` consumes the detector and routes to `CodeExecutor.execute()` or `execute_bash()`; syntax pre-check uses the same `python_extractor.validate_python_syntax`.

#### Matplotlib 内联图表捕获（Jupyter 级）

Python wrapper 在用户代码运行前注入一个 import 钩子，惰性拦截 `matplotlib.pyplot` 首次导入并强制 `Agg` 无头后端，随后接管图表呈现：

- **捕获全部图**：`plt.show()` 被替换为遍历 `plt.get_fignums()` 的例程，将**每一张**打开的 figure 存为 WebP，并以零拷贝 `vault://.myrm_plots/<id>` 指针经 APC 转义序列写入真实 stdout（前端 `LiveTerminal` 逐行渲染为内联 `<img>`）。emit 后即 `close`，使「打开的图」成为单一真相源，从根本上避免漏渲染或重复渲染。
- **结束兜底 flush**：在 `finally` 块中对仍打开（即未调用 `plt.show()`）的 figure 再 flush 一次。无论用户代码成功还是异常退出，已建好的图都会展示——对齐 Jupyter 的行为（cell 报错不吞掉已渲染的图）。
- **零拷贝**：传递 `vault://` 指针而非图字节，遵循框架「不用长字符串拼接大数据」原则，不污染 LLM 上下文与提示词缓存。

> 相比依赖整套 Jupyter 内核的方案（如 open-webui 经 websocket 连 Jupyter server 取 `display_data` 的 base64 PNG），本实现仅用轻量 import 钩子即达到等价的多图正确性，无内核生命周期与额外进程开销，契合 Agent-in-Sandbox 架构。WebP 字体保真依赖镜像内置的 `fonts-noto-cjk` 与 `matplotlibrc`（见 myrm-agent-server 镜像）。

### 3. PersistentSession（持久化会话）

长驻 Shell 进程管理，支持 macOS/Linux（bash）和 Windows（cmd.exe）：

- 通过 stdin 发送命令，stdout 使用**每次命令随机生成**的唯一标记分隔输出（`secrets.token_hex`），杜绝用户输出与固定标记文本碰撞导致的截断/误判退出码
- 命令发送前对 bash 命令做 `bash -n` **语法预检**，畸形多行命令（裸 `}`、未闭合的 `if`/heredoc）被前置拒绝，避免语法错误杀死长驻 Shell
- 注入 `exit()` 拦截函数（`builtin return`），LLM 生成的尾部 `exit N` 从命令块返回而非终止长驻 Shell，cwd/env 状态不丢失；嵌套 `bash -c "exit N"` 不受影响
- 命令包装为**块内捕获 rc** 的多行结构（`{ <command>; __myrm_rc__=$?; }`），注释行/空命令/heredoc/续行均不会使花括号块悬挂，rc 语义与退出状态零变化
- 包装命令前置 **`EXIT` trap**，当 `set -e` 等 errexit 崩溃导致 Shell 进程终止时仍输出完整标记对与真实退出码，使流式解析正常收尾而非误报「意外崩溃」触发无谓恢复；正常命令下 trap 静默，标记恰好输出一次
- 实时输出（SSE）经 **PII 脱敏**（主机路径 + 凭证 token 掩码），`execute` 与 `execute_stream` 双路径一致；tee 日志保留原始供排查
- 环境变量注入使用 **ANSI-C quoting**（`$'…'`）:值内 `$`、反引号、双引号保持字面（不二次展开），`\n`/`\t` 等控制字符转义为单行序列，注入命令永不破坏初始化批次（曾出现过 `"` 转义成 `\\"` 导致引号错配、长驻 Shell 卡死等续行的故障）
- **卡死自愈**：阻塞型命令（`sleep 9999`/`tail -f`）超时、或 stdin 吞噬型命令（`cat`/`ssh`/`python -c input()`）把 marker 回显导致边界损坏时，直接 kill 进程组并置 TERMINATED，下一次 execute/stream 透明重建会话，避免永久毒化
- 进程意外退出时自动重启并重试
- POSIX 进程组隔离 / Windows 进程树终止
- `asyncio.shield()` 保护子进程清理，防止异步取消导致僵尸进程
- `check_health()` 健康检查

### 4. Security（安全框架）

5 层纵深防御，全部自包含于 execution 模块内：

| 层 | 组件 | 防护目标 |
|----|------|---------|
| 1 | `shell_command_analyzer` | Shell 注入检测、危险命令识别、可疑模式分析 |
| 2 | `blacklist` | Python 模块黑名单（核心危险 + 网络模块）、环境变量黑名单 |
| 3 | `validator` | 路径白名单、域名白名单、命令验证 |
| 4 | `sanitize_env` | 环境变量过滤（57 个危险变量 + 3 个前缀：链接器注入、模块注入、代理注入、TLS 绕过、包管理器重定向、Git/编译器劫持） |
| 5 | `archive_sanitizer` | 压缩包解压安全增强（防止 zip bomb、路径遍历） |

### 5. Workspace（工作空间）

代码执行会话的文件空间管理：

- **Workspace**：工作空间数据模型，绑定到 `session_id`
- **WorkspaceService**：生命周期管理（CRUD），支持 `StorageProvider` 后端注入（默认 `LocalStorageBackend`）
- **路径安全**：`validate_path_component()` 防止路径遍历攻击

### 6. ExecutionMetrics（执行指标）

每个 executor 实例自动累计执行统计：

- 执行次数（总数、成功、失败）
- 执行时间（总计、平均、最大）
- 错误分布（按 `ErrorCategory` 分类）
- 支持 `.to_dict()` 结构化导出

### 7. ExecutionInterceptor（执行拦截器）

提供在「文件回滚无法完全撤销」的操作执行前的 Hook 机制：文件改写（写入、删除、`rm`、`sed -i`），以及触达工作区之外的 Shell 命令（数据库、容器/云、网络写入、`git push`/包发布）。

- **协议**：`ExecutionInterceptor.before_destructive_action(workspace_path, action_type, payload)`；`bash` 的 payload 携带 `destructive`（命令改写文件）与 `external_effects`（`security/external_effect_detector.py` 判定的外部影响类别，无则为空），由拦截器各自决定处置。
- **触发点**：`LocalExecutor.execute_bash`（命令改写文件或有外部影响时）和 `LocalFileOpsMixin.write_file` / `delete_file`。
- **安全保证**：拦截器调用被包裹在严格的 `asyncio.wait_for` 超时和 `try...except` 块中，**绝不阻塞**核心代码执行。
- **业务集成**：`myrm-agent-server` 通过此 Hook 实现基于 Git 的底层文件系统自动快照（Auto-snapshot）。

---

## Agent-in-Sandbox vs Agent-outside-Sandbox

| 维度 | Agent-in-Sandbox（本模块） | Agent-outside-Sandbox |
|------|---------------------------|----------------------|
| **执行延迟** | 本地子进程，微秒级 | Docker exec / SSH，毫秒级 |
| **会话状态** | PersistentSession 跨命令保持 | 每次 spawn 新进程，状态丢失 |
| **文件操作** | 直接 pathlib IO | 需要 FsBridge 抽象层 |
| **流式输出** | 逐行实时 | 等命令结束后一次性返回 |
| **安全深度** | 5 层纵深防御 | 仅 Docker 配置级 |
| **架构复杂度** | 无桥接层 | 需要文件同步、远程执行、路径安全三层桥接 |

---

## 配置

### ExecutionConfig

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `mode` | `LOCAL` | 执行模式（当前仅支持 LOCAL） |
| `local.max_execution_time` | 60 | 单次执行超时（秒） |
| `local.max_output_bytes` | 5 MiB | 输出缓冲上限，防止内存溢出 |
| `local.max_memory_mb` | 2048 | 单次执行内存上限（0 = 禁用） |
| `mcp_proxy.enabled` | `true` | MCP IPC 开关 |
| `network` | `NetworkConfig()` | 网络访问配置 |

### NetworkConfig

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `allow_network` | `false` | 是否允许网络访问（默认关闭） |
| `allowed_hosts` | `None` | `allow_network=true` 时生效：`None` = 内置默认白名单；空集合 = 不限制；非空 = 仅这些域名 |

配置参数：`ExecutionConfig.local.*`、`ExecutionConfig.mcp_proxy.*`、`ExecutionConfig.network.allow_network`、`ExecutionConfig.network.allowed_hosts`

---

## 依赖关系

```
toolkits/code_execution/
  ├─ executors/ → config, security, session, platform
  ├─ security/ → (自包含，无外部依赖)
  ├─ session/ → platform
  ├─ workspace/ → security (validate_path_component), toolkits/storage (StorageProvider)
  └─ utils/ → (自包含)

外部依赖：
  └─ myrm_agent_harness.utils.text_utils (文本截断)

零 agent 层依赖 — 可被任何框架独立使用
```

---

## 使用方式

### 方式 1：通过工厂函数

```python
from myrm_agent_harness.toolkits.code_execution import ExecutionConfig, ExecutionContext, create_executor

executor = create_executor(ExecutionConfig())
executor.bind_workspace("/path/to/workspace")
result = await executor.execute_bash(ExecutionContext(code="ls -la"))
```

### 方式 2：通过 ContextVar（Agent 集成）

```python
from myrm_agent_harness.toolkits.code_execution import require_executor, set_executor

set_executor(executor)  # 初始化时绑定
# ... 在 Agent 工具中 ...
executor = require_executor()  # 获取当前 executor
```

### 方式 3：统一导出

```python
from myrm_agent_harness.toolkits.code_execution import (
    CodeExecutor, LocalExecutor, create_executor,
    Workspace, WorkspaceService, create_workspace_service,
)
```

---

## 沙箱架构决策

### 系统组成

| 组件 | 定位 |
|------|------|
| **myrm-agent-server** | 完整 FastAPI 应用（Agent + 全部业务逻辑） |
| **myrm-control-plane** | 沙箱生命周期管理（创建/Sleep/唤醒/回收） |
| **myrm-agent-harness** | Agent 框架层（工具集、运行时、ACP 协议） |

### 沙箱策略：Agent 专用云电脑

每个用户一台 **Agent 专用云电脑**：**agent-in-sandbox** —— harness（Agent 运行时 / 执行循环）、浏览器、终端、文件系统、代码执行全部在同一台云电脑内运行；文件、已装软件、浏览器状态跨会话保留，可 7×24 常驻与接续工作。

| 维度 | 我们的形态 |
|------|-----------|
| 粒度 | per-user（每用户一台，专属，不与他人共享） |
| Harness 位置 | 云电脑内（与执行同机，无桥接层） |
| 状态 | 持久：文件系统 + 已装软件 + 浏览器 profile |
| 常驻 | 7×24 可常驻；空闲按套餐休眠，唤醒即续 |
| 外部凭据 | 无外部数据库凭据；数据在云电脑内的 SQLite + 嵌入式 Qdrant，LLM 走 CP 中继/虚拟密钥 |

竞品同构参考见 [竞品 Harness 运行位置](#竞品-harness-运行位置2026-10-核验)。

### 部署模式

所有沙箱模式（LOCAL / SANDBOX）统一使用 SQLite + 嵌入式 Qdrant + 本地文件存储（`deploy_mode.py`）；控制平面自身的平台数据使用 PostgreSQL。

| 模式 | 数据库 | 向量库 | 场景 |
|------|--------|--------|------|
| LOCAL | SQLite | 嵌入式 Qdrant | 桌面客户端 / 本地 WebUI |
| SANDBOX | SQLite（持久化卷） | 嵌入式 Qdrant（持久化卷） | 云端 Sandbox |

### 架构决策：沙箱内 SQLite + 持久化卷

**核心问题**：在 per-user 沙箱模式下，业务服务层（认证、对话管理、知识库、记忆、订阅、配额）应该放在控制平面还是沙箱内？

**决策**：myrm-agent-server 完整应用在云电脑内，所有沙箱模式统一使用 SQLite + 嵌入式 Qdrant；Sandbox 模式下数据存储在云电脑持久化卷上，无外部数据库凭据。

```
控制平面（独立部署）
  ├── 网关级 JWT 认证
  ├── HTTP 反向代理 → 路由到用户的沙箱
  ├── 沙箱生命周期（创建/Sleep/唤醒/回收）
  ├── 持久化卷管理（创建/挂载/备份）
  ├── 计费 webhook 接收
  └── 监控 + 告警
  │
  PostgreSQL（平台数据 + 企业治理）：
  cp_users / cp_subscriptions / cp_quota_usage / sandboxes / cp_wake_triggers
  cp_orgs / cp_org_members / cp_org_oidc_configs / cp_org_mcp_servers / ...

沙箱（per-user）
  └── myrm-agent-server 完整应用
      ├── 认证、对话管理、知识库、记忆
      ├── 订阅、配额（本地副本）
      ├── Agent 执行（Plan → Execute → Reflect）
      ├── SQLite（持久化卷上）← 业务表
      ├── 嵌入式 Qdrant（持久化卷上）← 向量检索
      └── 无外部数据库凭据

持久化卷目录（`MYRM_DATA_DIR=/persistent/data`）：
  /persistent/
    ├── home/                 ← HOME（CLI 配置/缓存）
    └── data/                 ← MYRM_DATA_DIR（Server 状态根）
        ├── data.db           ← SQLite 业务库
        ├── checkpoints.db    ← LangGraph checkpoint 库
        ├── qdrant/           ← 嵌入式 Qdrant
        └── harness/          ← harness 状态
```

**为什么不拆分到控制平面**：

Agent 执行循环需要实时访问业务数据（检查配额、读取记忆、检索知识库、管理对话、保存结果），每次循环 10+ 次数据访问。

| Agent 操作 | 拆分到控制平面（RPC） | 沙箱内本地访问 |
|-----------|---------------------|--------------|
| 检查配额 / 读取记忆 / 检索知识库 | 50-300ms/次 | <5ms/次 |
| 单次循环总额外延迟 | **500ms-3s** | **无** |

此外，本地模式没有控制平面，拆分方案需要启动本地控制平面或维护两套代码路径。行业实践中，2026 年的 Personal Agent（Grok Bot / Muse / dots 等）都把用户状态放在各自的云电脑内，而非拆分到平台侧数据库。

**选择当前方案的理由**：

1. **Agent 自循环零延迟**：所有业务数据通过本地 SQLite 访问（<5ms），不受网络延迟影响
2. **无外部数据库凭据**：沙箱不连接外部数据库，即使沙箱被突破也无外部数据库凭据可泄露
3. **代码路径统一**：所有沙箱模式使用相同的 SQLite + 嵌入式 Qdrant，无条件分支
4. **行业最佳实践**：与 2026 主流 Personal Agent 一致（云电脑内运行完整应用，状态留在本机）
5. **结构化数据管理**：SQLite 提供 SQL 查询、事务、索引，配合嵌入式 Qdrant 实现向量检索，per-user 数据量下功能充足

### 数据分层

判断标准：控制平面在沙箱不存在/Sleep 时是否需要访问？

**控制平面 PostgreSQL（平台数据 + 企业治理，非穷举）**：

| 分类 | 主要表 | 为什么在控制平面 |
|---|---|---|
| 用户/订阅 | `cp_users`、`cp_subscriptions` | 创建沙箱前验证身份；处理支付 webhook |
| 配额/计费 | `cp_quota_usage`、`cp_work_unit_*`、`cp_billing_webhook_events` | 跨设备/会话统计 |
| 沙箱/唤醒 | `sandboxes`、`cp_wake_triggers`、`cp_channel_bindings` | 生命周期与定时唤醒 |
| 企业治理 | `cp_orgs`、`cp_org_members`、`cp_org_oidc_configs`、`cp_org_mcp_servers`、`cp_org_model_policies`、`cp_org_approval_policies` | 组织、SSO、MCP/模型/审批策略 |
| 其他 | `secrets`、`cp_volume_handoff_logs`、`cp_tunnel_registrations`、`security_alerts` | 密钥、卷交接、隧道与安全告警 |

**沙箱 SQLite（用户个人数据，主要表，非穷举）**：

| 分类 | 主要表 |
|---|---|
| 对话 | `chats`、`messages`、`conversation_forks`、`interrupted_turn_markers` |
| Agent/任务 | `agents`、`agent_profile_history`、`agent_profile_snapshots`、`cron_jobs`、`cron_runs`、`monitor_states` |
| 记忆 | `profile_attributes`、`procedural_rules`、`pending_memories`、`memory_operation_events` |
| 工件/FAQ | `artifacts`、`artifact_versions`、`artifact_audit_logs`、`faq_corpus`、`faq_entries` |
| 配置/权限 | `user_configs`、`user_tool_allowlist`、`agent_secrets`、`vault_credentials`、`api_keys` |
| 渠道 | `channel_pairings`、`channel_messages` |
| 安全/审计 | `approvals`、`risk_hits`、`security_profiles`、`config_audit_logs` |

### 同步机制

| 方向 | 触发时机 | 内容 |
|------|---------|------|
| 控制平面 → 沙箱 | 创建沙箱时 | User + Subscription + Quota 初始数据 |
| 控制平面 → 沙箱 | 运行期间（WebSocket） | 订阅升级/降级通知 |
| 沙箱 → 控制平面 | 「下一次必须运行时间」变化时（目标额度窗口到点续跑 / cron 下次运行 / 看板改期任务到点） | HTTP `PUT /api/internal/sandboxes/{id}/wake-schedule`；控制平面到点唤醒已被回收器暂停的沙箱，之后由沙箱自身定时器接管 |
| 沙箱 → 控制平面 | Agent 执行消耗 token 时 | QuotaUsage 增量更新 |
| 沙箱 → 控制平面 | Sleep 前强制同步 | 配额最终一致性保证 |

### 本地模式兼容

| 环境变量 | 本地模式 | Sandbox 模式 |
|---------|---------|----------|
| `DEPLOY_MODE` | `local` | `sandbox` |
| 数据库 | SQLite（本地文件） | SQLite（持久化卷） |
| 向量库 | 嵌入式 Qdrant | 嵌入式 Qdrant（持久化卷） |
| 控制平面 | 不需要 | 独立部署 |
| SQLite 路径 | `~/.myrm/data.db` | `/persistent/data/data.db`（`MYRM_DATA_DIR=/persistent/data`） |

所有沙箱模式代码路径完全一致，仅通过环境变量切换存储路径。

### 竞品 Harness 运行位置（2026-10 核验）

| 产品 | Harness / Agent 运行时位置 |
|------|---------------------------|
| Grok Bot | 用户专属 persistent cloud VM（官方 "per user, not per Bot"，含浏览器 / 文件系统 / 终端） |
| Meta Muse | Muse Secure VM（per person 的专属云电脑） |
| OpenAI Dots | 每个 Dot 自己的云电脑（官方 "Each dot works on its own cloud computer"） |
| Google Gemini Spark | 远程执行环境（官方确认远程浏览器 + 远程代码执行，未公开 VM 细节） |
| Instinct | 持久 cloud computer（第三方复刻项目文档，非官方） |
| Manus Cue | 每个 Agent 自有身份 + 云电脑（官方 "Each agent gets its own ... computer"） |
| Today AI | 24 小时在线 Cloud Computer（媒体报道，无官方文档） |
| 腾讯 LightVela | 腾讯轻量云专属实例（官方 "We host Hermes Agent in the cloud"） |
| 蚂蚁灵光 | 架构未公开（无云电脑披露） |
| **Myrm** | **每用户 Agent 专用云电脑（agent-in-sandbox）** |

**结论**：2026 年 Personal Agent 的标准架构是 **harness 跑在云电脑内**，本地设备只是客户端（聊天入口、审批、看屏幕）；平台侧只有控制面（创建 / 回收 / 计费 / 网关 / 恢复），不跑 agent loop。逐项证据（官方文档 / 媒体）由维护者的竞品核验记录承载，不随本仓库分发。

**差异化优势**：本地模式（SQLite）与开源产品层自托管（主流云端 Personal Agent 均不支持）、结构化数据管理（SQL + 向量库）、无外部凭据。

**2026 行业趋势验证**：
- [RisingWave](https://risingwave.com/blog/stateful-sandboxes-for-ai-agents)：Stateful sandbox 需要嵌入式数据库
- [PingCAP](https://www.pingcap.com/blog/local-first-rag-using-sqlite-ai-agent-memory-openclaw/)：local-first + zero-ops 嵌入式数据库是 2026 趋势
- [Fly.io: Code And Let Live](https://fly.io/blog/code-and-let-live)（Annie Ruygt）："we're calling it: ephemeral sandboxes are obsolete"、"They don't want containers. They don't want 'sandboxes'. They want computers." — 推出 Sprites（持久化 Firecracker microVM + 100GB ext4 + Checkpoint/Restore），专为 per-user 持久化 Agent 场景设计
- 沙箱内 SQLite + 嵌入式 Qdrant 的方案与 Sprites 的 stateful sandbox 理念高度一致

### 云电脑供给（2026-10）

> 完整调研与来源（含逐项核验与修正记录）由维护者的竞品核验记录承载，不随本仓库分发。

**SaaS 最终选型：Fly Sprites 作为唯一云供给**（E2B 支持已移除；Machines 仅作为 Sprites 适配完成前的过渡实现，随后删除）。

**企业私有化**：单 VM Docker Compose（CP + PostgreSQL + Redis + 每用户 Docker 沙箱）。**本地**：OS 进程沙箱（sandbox-exec / bwrap / AppContainer）。两者都不使用 Sprites。

| 项 | 方案 |
|----|------|
| 云供给 | **Fly Sprites**：8 vCPU、100GB ext4、内存按负载自动伸缩 |
| 休眠 | 空闲约 30s 自动进入 warm（内存冻结，100–500ms）→ cold（进程重启，1–2s）；空闲不计 compute 费 |
| 常驻 | Service 随开机 / 崩溃 / cold wake 自动拉起；请求命中 Sprite URL 自动唤醒 |
| 计费 | CPU $0.0385/CPU-h；RAM $0.021875/GB-h；热存储 ≈$0.50/GB-月；冷存储 $0.02/GB-月（空闲仅计存储） |
| 迁移状态 | 当前 `flyio` 适配器仍是 Machines（`auto_stop = "stop"`）；Sprites 适配尚未实现，完成后删除 Machines 代码 |

- **不采用 Modal**：默认寿命 5 分钟、最长 24 小时，不适合常驻个人云电脑。
- **不接外部任务沙箱**：一台用户云电脑已覆盖隔离、执行、持久化；不可信第三方代码、GPU、大规模并行等场景在 Sprites 内以进程级隔离处理，必要时再评估独立供给。
- **终态**：自建 Firecracker / microVM 平台，掌握成本与体验上限。

## Bash Execution Resilience & Command Rewriting

The `BashExecutor` automatically injects a `resilience_init.sh` script into every bash execution context. This script defines shell functions (like `git()` and `npm()`) that intercept specific commands to provide:

1.  **Transparent Fallbacks**: For example, if `git clone` times out, it automatically falls back to shallow clone (`--depth 1`) or zipball download. If `npm install` fails, it falls back to `bun install` or retries with a clean cache.
2.  **GitHub Credential & Identity Injection**: When `GITHUB_TOKEN` is present (injected by the credential pipeline), `git push` to HTTPS `github.com` remotes gets an inline credential helper when the sandbox has no existing credentials, and `git commit` resolves a `user.name`/`user.email` from the GitHub account (cached, with a local fallback) when the sandbox has no global git identity. The credential helper is **host-scoped**: it only answers for `github.com`/`www.github.com` hosts, so the token is never handed to third-party HTTPS git servers the agent pushes to (e.g. a self-hosted GitLab remote or a raw HTTPS URL).
3.  **Pre-execution Command Rewriting**: For commands that produce highly verbose or human-centric output (which wastes LLM tokens and breaks parsing in non-English locales), the script intercepts and rewrites them into machine-readable formats.
    *   `git status` is rewritten to `git status --porcelain -b -uall`.
    *   `git diff` (without specific formatting flags) is rewritten to first show a `--stat` summary, followed by the actual diff.
    
This approach uses native Bash function interception, which is extremely lightweight, cross-platform, and avoids the risks of static string replacement in Python. It ensures the LLM receives clean, predictable output while maintaining 100% compatibility with user-provided scripts.
