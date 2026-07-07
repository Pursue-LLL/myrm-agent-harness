# Execution System 系统设计

## 设计目标

为 AI Agent 提供安全、高性能的代码执行环境。采用 **Agent-in-Sandbox** 架构：Agent 与代码在同一容器内执行，消除远程执行的延迟和复杂性。

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
| `read_file(path)` | 默认实现 | 读取文件内容 |
| `write_file(path, content)` | 默认实现 | 写入文件 |
| `list_files(path)` | 默认实现 | 列出目录文件 |
| `bind_workspace(path)` | 具体 | 绑定工作目录 |
| `cleanup()` | 虚拟 | 资源清理 |

**生命周期**：`bind_workspace(path)` → 执行操作 → `cleanup()`

**ContextVar 管理**：所有工具通过 `get_executor()` / `set_executor()` / `require_executor()` 共享 executor 实例，避免 LangGraph checkpoint 序列化问题。

### 2. LocalExecutor（本地执行器）

`CodeExecutor` 的本地实现，直接在当前进程环境中执行代码：

- **Python 执行**：每次调用创建独立子进程，通过 wrapper script 注入模块黑名单。内置 **Actionable Diagnostic Hints** 机制，拦截 `ModuleNotFoundError` 并追加 `python -m pip install` 修复建议，引导大模型自主纠错。
- **Bash 执行**：通过 `PersistentSession` 维护长驻 Bash 进程，环境变量和工作目录跨命令保持
- **文件操作**：直接使用 `pathlib` 本地 IO，零网络开销

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

- 通过 stdin 发送命令，stdout 使用唯一标记分隔输出
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
- **WorkspaceService**：生命周期管理（CRUD），支持 `StorageProvider` 后端注入（本地/S3）
- **路径安全**：`validate_path_component()` 防止路径遍历攻击

### 6. ExecutionMetrics（执行指标）

每个 executor 实例自动累计执行统计：

- 执行次数（总数、成功、失败）
- 执行时间（总计、平均、最大）
- 错误分布（按 `ErrorCategory` 分类）
- 支持 `.to_dict()` 结构化导出

### 7. ExecutionInterceptor（执行拦截器）

提供在破坏性操作（如文件写入、高危 Shell 命令）执行前的 Hook 机制。

- **协议**：`ExecutionInterceptor.before_destructive_action(workspace_path, action_type, payload)`
- **触发点**：`LocalExecutor.execute_bash`（仅高危命令）和 `LocalFileOpsMixin.write_file` / `delete_file`。
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
| `timeout_seconds` | 60 | 单次执行超时 |
| `max_output_size` | 50000 | 输出最大字符数 |
| `network` | `NetworkConfig()` | 网络访问配置 |

### NetworkConfig

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `allow_network` | `true` | 是否允许网络访问 |
| `allowed_hosts` | `None`（使用默认白名单） | 域名白名单 |

配置参数：`ExecutionConfig.network.allow_network`、`ExecutionConfig.network.allowed_hosts`

---

## 依赖关系

```
toolkits/execution/
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
from myrm_agent_harness.toolkits.execution import create_executor, ExecutionConfig

executor = create_executor(ExecutionConfig())
executor.bind_workspace("/path/to/workspace")
result = await executor.execute_bash(ExecutionContext(code="ls -la"))
```

### 方式 2：通过 ContextVar（Agent 集成）

```python
from myrm_agent_harness.toolkits.execution import set_executor, require_executor

set_executor(executor)  # 初始化时绑定
# ... 在 Agent 工具中 ...
executor = require_executor()  # 获取当前 executor
```

### 方式 3：统一导出

```python
from myrm_agent_harness.toolkits.execution.execution_tools import (
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

### 沙箱策略

采用 **per-user** 模式（每个用户一个持久化沙箱），参考 Happycapy 架构。

| 策略 | 代表产品 | 特点 |
|------|---------|------|
| per-task | Manus | 每个任务一个临时沙箱，执行完销毁 |
| **per-user** | Happycapy / **Myrm** | 每个用户一个持久沙箱，跨任务保留状态 |

**选型依据**（2026 行业基准，[Computer Agents Benchmarks](https://computer-agents.com/blog/persistent-vs-ephemeral-agents-2026)）：

| 指标 | per-task | per-user | 差距 |
|------|---------|---------|------|
| 多日任务自动化率 | 22% | **87%** | +295% |
| 错误自恢复率 | 41% | **78%** | +90% |
| 幻觉/偏移率 | 29% | **11%** | -62% |
| 每 100 复杂任务成本 | $18-42 | **$9-21** | -50% |

25 维度完整对比见 [CODE_EXECUTION_SYSTEM_REFERENCE.md § 3.6.3.5](CODE_EXECUTION_SYSTEM_REFERENCE.md)。

**注**：Credits 浪费率 72.4% 是 Manus 当前实现的实测数据，非 per-task 固有缺陷。per-task 可通过完善的外部记忆系统降低浪费，但需要额外工程（共享数据库 + API 调用）。per-user 天然避免上下文丢失——数据在沙箱内自然存在。

### 部署模式

所有部署模式统一使用 SQLite + 嵌入式 Qdrant + 本地文件存储（`deploy_mode.py`）。

| 模式 | 数据库 | 向量库 | 场景 |
|------|--------|--------|------|
| LOCAL | SQLite | 嵌入式 Qdrant | 桌面客户端 / CLI WebUI |
| SANDBOX | SQLite（持久化卷） | 嵌入式 Qdrant（持久化卷） | 云端 Sandbox |

### 架构决策：沙箱内 SQLite + 持久化卷

**核心问题**：在 per-user 沙箱模式下，业务服务层（认证、对话管理、知识库、记忆、订阅、配额）应该放在控制平面还是沙箱内？

**决策**：claw-server 完整应用在沙箱内，所有模式统一使用 SQLite + 嵌入式 Qdrant，Sandbox 模式下数据存储在沙箱持久化卷上，无外部数据库凭据。

```
控制平面（独立部署）
  ├── 网关级 JWT 认证
  ├── HTTP 反向代理 → 路由到用户的沙箱
  ├── 沙箱生命周期（创建/Sleep/唤醒/回收）
  ├── 持久化卷管理（创建/挂载/备份）
  ├── 计费 webhook 接收
  └── 监控 + 告警
  │
  PostgreSQL（平台数据，4 个表）：
  User, UserSubscription, UserQuotaUsage, WakeTrigger

沙箱（per-user）
  └── claw-server 完整应用
      ├── 认证、对话管理、知识库、记忆
      ├── 订阅、配额（本地副本）
      ├── Agent 执行（Plan → Execute → Reflect）
      ├── SQLite（持久化卷上）← 业务表
      ├── 嵌入式 Qdrant（持久化卷上）← 向量检索
      └── 无外部数据库凭据

持久化卷目录：
  /persistent/
    ├── data/myrm.db        ← SQLite
    ├── data/qdrant/          ← Qdrant 数据
    ├── files/knowledge/      ← 知识库文件
    ├── files/artifacts/      ← Agent 生成文件
    └── workspace/            ← 用户工作空间
```

**为什么不拆分到控制平面**：

Agent 执行循环需要实时访问业务数据（检查配额、读取记忆、检索知识库、管理对话、保存结果），每次循环 10+ 次数据访问。

| Agent 操作 | 拆分到控制平面（RPC） | 沙箱内本地访问 |
|-----------|---------------------|--------------|
| 检查配额 / 读取记忆 / 检索知识库 | 50-300ms/次 | <5ms/次 |
| 单次循环总额外延迟 | **500ms-3s** | **无** |

此外，本地模式没有控制平面，拆分方案需要启动本地控制平面或维护两套代码路径。行业实践中 Manus/Happycapy 均选择将状态放在沙箱内（file-based），而非拆分到控制平面。

**选择当前方案的理由**：

1. **Agent 自循环零延迟**：所有业务数据通过本地 SQLite 访问（<5ms），不受网络延迟影响
2. **无外部凭据**：沙箱不连接外部数据库，即使沙箱被突破也无外部凭据可泄露
3. **代码路径统一**：所有部署模式使用相同的 SQLite + 嵌入式 Qdrant，无条件分支
4. **行业最佳实践**：与 Happycapy（持久化卷 + 沙箱内完整应用）一致
5. **结构化数据管理**：SQLite 提供 SQL 查询、事务、索引，配合嵌入式 Qdrant 实现向量检索，per-user 数据量下功能充足

### 数据分层

判断标准：控制平面在沙箱不存在/Sleep 时是否需要访问？

**控制平面 PostgreSQL（4 个表，平台数据）**：

| 表 | 用途 | 为什么在控制平面 |
|---|------|----------------|
| User | 用户账户 | 创建沙箱前验证身份 |
| UserSubscription | 订阅状态 | 沙箱 Sleep 时处理支付 webhook |
| UserQuotaUsage | 配额使用量 | 跨设备/会话统计 |
| WakeTrigger | 唤醒触发器 | 沙箱 Sleep 时触发唤醒（定时任务/外部消息） |

**沙箱 SQLite（用户个人数据）**：

| 分类 | 表 |
|------|---|
| 对话 | Chat, Message |
| Agent | Agent, AgentTurn, AgentEvent |
| 记忆 | ProfileAttribute, ProceduralRule, PendingMemory |
| 知识库 | KnowledgeBaseModel, KnowledgeFileModel |
| 配置 | UserConfig, UserToolAllowlist |
| 任务 | CronJobModel, CronRunModel, MonitorStateModel |
| 渠道 | ChannelPairingModel |
| 认证 | User（本地副本）, DeviceSession |
| 订阅 | UserSubscription（本地副本）, UserQuotaUsage（本地副本） |

### 同步机制

| 方向 | 触发时机 | 内容 |
|------|---------|------|
| 控制平面 → 沙箱 | 创建沙箱时 | User + Subscription + Quota 初始数据 |
| 控制平面 → 沙箱 | 运行期间（WebSocket） | 订阅升级/降级通知 |
| 沙箱 → 控制平面 | 创建/更新 CronJob 时 | WakeTrigger（next_run_time） |
| 沙箱 → 控制平面 | 创建/更新 ChannelPairing 时 | WakeTrigger（channel 路由信息） |
| 沙箱 → 控制平面 | Agent 执行消耗 token 时 | QuotaUsage 增量更新 |
| 沙箱 → 控制平面 | Sleep 前强制同步 | 配额最终一致性保证 |

### 本地模式兼容

| 环境变量 | 本地模式 | Sandbox 模式 |
|---------|---------|----------|
| `DEPLOY_MODE` | `local` | `sandbox` |
| 数据库 | SQLite（本地文件） | SQLite（持久化卷） |
| 向量库 | 嵌入式 Qdrant | 嵌入式 Qdrant（持久化卷） |
| 控制平面 | 不需要 | 独立部署 |
| SQLite 路径 | `~/.myrm-agent/data.db` | `/persistent/data/myrm.db`（`SQLITE_PATH` 配置） |

所有部署模式代码路径完全一致，仅通过环境变量切换存储路径。

### 与竞品对比

| 维度 | Manus | Happycapy | **Myrm** |
|------|-------|-----------|------------|
| 沙箱策略 | per-task | per-user | **per-user** |
| Agent 运行位置 | 沙箱内 | 沙箱内 | **沙箱内** |
| 状态存储 | 沙箱文件系统（临时） | 沙箱文件系统（持久卷） | **SQLite + 嵌入式 Qdrant（持久卷）** |
| Memory 机制 | file-based（glob/grep） | file-based（持久化卷） | **数据库 + 向量库** |
| 外部凭据 | 无 | 无 | **无** |
| 本地模式 | 不支持 | 不支持 | **支持（SQLite）** |
| 自托管（开源产品层） | 不支持 | 不支持 | **支持** |

**差异化优势**：结构化数据管理（SQL + 向量库）、无外部凭据、本地模式支持、开源产品层自托管。

**2026 行业趋势验证**：
- [RisingWave](https://risingwave.com/blog/stateful-sandboxes-for-ai-agents)：Stateful sandbox 需要嵌入式数据库
- [PingCAP](https://www.pingcap.com/blog/local-first-rag-using-sqlite-ai-agent-memory-openclaw/)：local-first + zero-ops 嵌入式数据库是 2026 趋势
- [Fly.io/Sprites](https://fly.io/blog/sprites)（CEO Kurt Mackey, 2026.01）："Ephemeral sandboxes are obsolete. Claude doesn't want a stateless container. Claude wants a computer." — 推出 Sprites（持久化 Firecracker microVM + 100GB NVMe + Checkpoint/Restore），专为 per-user 持久化 Agent 场景设计
- E2B 持久化上限 14 天（Session-scoped），Fly.io Sprites 永久持久化（Indefinite），两者底层均为 Firecracker 但持久化哲学完全不同
- 沙箱内 SQLite + 嵌入式 Qdrant 的方案与 Sprites 的 stateful sandbox 理念高度一致

## Bash Execution Resilience & Command Rewriting

The `BashExecutor` automatically injects a `resilience_init.sh` script into every bash execution context. This script defines shell functions (like `git()` and `npm()`) that intercept specific commands to provide:

1.  **Transparent Fallbacks**: For example, if `git clone` times out, it automatically falls back to shallow clone (`--depth 1`) or zipball download. If `npm install` fails, it falls back to `bun install` or retries with a clean cache.
2.  **Pre-execution Command Rewriting**: For commands that produce highly verbose or human-centric output (which wastes LLM tokens and breaks parsing in non-English locales), the script intercepts and rewrites them into machine-readable formats.
    *   `git status` is rewritten to `git status --porcelain -b -uall`.
    *   `git diff` (without specific formatting flags) is rewritten to first show a `--stat` summary, followed by the actual diff.
    
This approach uses native Bash function interception, which is extremely lightweight, cross-platform, and avoids the risks of static string replacement in Python. It ensures the LLM receives clean, predictable output while maintaining 100% compatibility with user-provided scripts.
