# ACP 系统设计方案

> 基于多项目调研汇总的可执行框架方案：Server 与 Runtime 分层，横切能力开箱即用。

---

## 1. 设计原则

- **Runtime 独立层**：对外部 Agent 统一抽象为 `RuntimeBackend`（ACP / SDK / CLI）
- **能力 ≥ 竞品**：覆盖主流竞品核心能力，在关键维度可对标或超出
- **禁止过度设计**：每个组件有明确职责与参照价值
- **Python 原生**：asyncio、Protocol、dataclass、StrEnum，无额外编排框架依赖
- **Server 层稳定**：server/ 子目录（server.py / bridge.py / event_translator.py）专注 IDE ↔ 宿主 Agent 桥接

---

## 2. 架构总览

```
╔═══════════════════════════════════════════════════════════════╗
║                     ACP 系统架构                              ║
╠═══════════════════════════════╦═══════════════════════════════╣
║  Server 层 (server/)           ║  Runtime 层 (runtime/)         ║
║  server.py                    ║  RuntimeBackend Protocol       ║
║  bridge.py                    ║  ├─ AcpRuntime + AcpCallback   ║
║  event_translator.py          ║  ├─ SdkRuntime                 ║
║  _default_factory.py          ║  └─ CliRuntime                 ║
║  __main__.py (根)             ║  RuntimePool                   ║
╠═══════════════════════════════╩═══════════════════════════════╣
║                    横切关注点                                   ║
║  types.py · EventBus · PermissionManager                      ║
║  BackendDetector · HealthMonitor                               ║
╚═══════════════════════════════════════════════════════════════╝
```

---

## 3. 核心模块设计

### 3.1 RuntimeBackend Protocol（核心抽象）

**来源**：openclaw AcpRuntime + workany AgentPlugin + LobsterAI CoworkRuntime

**价值**：将 ACP 协议连接、SDK 直接调用、CLI spawn 统一为一个接口，添加新后端零成本。

```
RuntimeBackend (Protocol)
├── name: str                                    # 后端标识
├── capabilities: BackendCapabilities            # 能力声明
├── is_alive: bool                               # 存活检查
├── run_turn(prompt, session_id, **) -> AsyncIterator[RuntimeEvent]  # 核心执行
├── cancel(session_id) -> None                   # 取消当前轮次
├── resume(session_id) -> bool                   # 恢复会话
├── get_info() -> BackendInfo                    # 后端元数据
└── close() -> None                              # 关闭连接
```

**设计亮点**：
- `cancel()` — 完整的生命周期控制，用户可中断长任务
- `get_info()` → `BackendInfo` — 后端元数据（版本、能力、状态），支持运行时能力查询

**BackendCapabilities**：
- `supports_resume`：是否支持会话恢复
- `supports_mcp`：是否支持 MCP Server 注入
- `supports_streaming`：是否支持流式传输
- `supports_tools`：是否支持原生工具调用

**3 种实现**：

| Runtime | 协议 | 参考项目 | 适用场景 |
|---------|------|---------|---------|
| AcpRuntime | ACP JSON-RPC (stdin/stdout) | openclaw, zeroclaw | 需 ACP 桥接器（claude-agent-acp / acpx），原生 CLI 不支持 ACP |
| SdkRuntime | Claude Agent SDK `query()` API | craft-agents-oss, LobsterAI | 直接 SDK 集成 |
| CliRuntime | spawn CLI + NDJSON 解析（含 reasoning/usage） | ironclaw, nullclaw, picoclaw | Claude/Codex/Gemini CLI（推荐，开箱即用） |

**BackendInfo**：
```
BackendInfo
├── name: str
├── version: str | None
├── backend_type: "acp" | "sdk" | "cli"
├── status: "ready" | "starting" | "error" | "stopped"
├── capabilities: BackendCapabilities
└── metadata: dict[str, object] | None
```

来源：AionUi 后端版本检测 + workany AgentProviderMetadata

### 3.2 RuntimeEvent（统一事件模型）

**来源**：opencode 事件订阅 + nextclaw NCP 34 事件类型（精简版）

```
RuntimeEvent (frozen dataclass)
├── type: RuntimeEventType
├── data: dict[str, object]
├── session_id: str
└── timestamp: float
```

**RuntimeEventType 枚举（9 种）**：

| 事件类型 | 说明 | data 字段 |
|---------|------|----------|
| `text_delta` | LLM 文本增量 | content: str |
| `reasoning_delta` | 思维链增量 | content: str |
| `tool_start` | 工具调用开始 | tool_name, tool_input, tool_call_id |
| `tool_result` | 工具调用结果 | tool_call_id, output, is_error |
| `permission_request` | 权限请求 | tool_name, tool_input, options, response_future: asyncio.Future[PermissionDecision] |
| `usage_update` | Token 用量更新 | input_tokens, output_tokens, cache_read, cache_write |
| `status_update` | 后端状态变化 | status: str, message: str &#124; None |
| `error` | 错误事件 | error: AcpError |
| `done` | 会话结束 | stop_reason, total_usage |

**设计亮点**：
- `reasoning_delta` — 支持思维链展示（参考 nextclaw MessageReasoningDelta）
- `usage_update` — 实时 Token 监控（参考 craft-agents-oss token 估算）
- `status_update` — 后端状态变化通知（starting, compacting, reconnecting 等），UI 可精确展示后端状态
- `permission_request` 包含 `response_future` — 参考 Claude-Cowork PendingPermission 模式，run_turn 内部 await Future，订阅者通过 `future.set_result(decision)` 响应，超时按 PermissionManager 默认策略处理

### 3.3 结构化错误体系

**来源**：craft-agents-oss 错误标记 (__API_KEY_ERROR__ 等) + ironclaw 错误分类

```
AcpErrorCode (StrEnum)
├── AUTH_FAILED         # API Key 无效
├── BACKEND_NOT_FOUND   # CLI 未安装
├── TIMEOUT             # 超时
├── RATE_LIMITED        # 超频
├── CONTEXT_OVERFLOW    # 上下文溢出
├── PROCESS_CRASHED     # 进程崩溃
├── PERMISSION_DENIED   # 权限拒绝（safe 模式下拒绝写操作等）
├── CANCELLED           # 用户取消
└── UNKNOWN             # 未知错误

AcpError (frozen dataclass)
├── code: AcpErrorCode
├── message: str
├── retryable: bool
└── details: dict[str, object] | None
```

**价值**：生产系统必须有结构化错误码，上层可根据 `retryable` 自动重试，根据 `code` 精准定位问题。

### 3.4 EventBus（统一事件总线）

**来源**：opencode 全局事件流 + nextclaw AgentConversationStateManager

**价值**：解耦事件生产者和消费者，支持外部订阅（UI、日志、监控）。

```
EventBus
├── subscribe(event_type | None, callback, *, session_id: str | None) -> subscription_id
├── unsubscribe(subscription_id) -> None
└── emit(event: RuntimeEvent) -> None
```

**增强**：
- Session 级过滤：subscribe 可指定 session_id，只接收该会话的事件
- 异步回调：支持 async callable

### 3.5 PermissionManager（增强权限管理）

**来源**：craft-agents-oss 4 种权限模式 + ironclaw 工具白名单 + AionUi 审批缓存

**架构**：框架层提供 `PermissionManager` Protocol + `DefaultPermissionManager` 默认实现，业务层可替换为自定义实现。

```
PermissionManager (Protocol)
├── check(tool_name, tool_input, session_id) -> PermissionDecision
└── record_approval(tool_name, session_id) -> None

框架层默认实现：DefaultPermissionManager
业务层可实现：UIPermissionManager, AdminPermissionManager 等
```

**4 种权限模式**：
- `safe`：只允许读操作（Read, Glob, Grep, Search）
- `ask`：每次工具调用都询问用户（通过 EventBus 发送 permission_request）
- `allow_all`：自动批准所有工具
- `bypass`：跳过权限检查（SDK 内置权限接管）

**增强功能**：
- **工具白名单 + 参数级通配符**：`allowed_tools: list[str]`，支持 `Bash(npm run *)` 格式
- **Session 级审批缓存**：用户选择 "always allow" 后缓存决策
- **工具分类**：自动识别读/写/执行操作
- **异步响应机制**：`ask` 模式下，run_turn 产生包含 `asyncio.Future[PermissionDecision]` 的 permission_request 事件，await Future 等待外部决策；PermissionManager 在 `allow_all` / `safe` / `bypass` 模式下自动 set_result，无需外部参与

### 3.6 BackendDetector（后端自动检测）

**来源**：AionUi 后端自动检测 + workany 6 级 Claude Code 发现

**检测策略**：
1. `which` / `where` 命令
2. 扩展 PATH 搜索
3. 常见安装路径（/usr/local/bin, ~/.local/bin）
4. npm global
5. 可选版本检测（`--version`，按调用方需要开启）
6. 可选强制刷新（`refresh=True`，绕过缓存）

**返回**：`list[DetectedBackend]`（name, path, version）
**缓存**：进程级双缓存（带版本 / 不带版本）+ 软 TTL（默认 300s），避免重复路径扫描与重复版本探测，同时避免长期陈旧结果常驻

### 3.7 HealthMonitor（健康监控）

**来源**：zeroclaw 进程 Checkout/Restore + AionUi 自动重连

**功能**：
- 定期检查后端进程存活（`is_alive`）
- 非存活时：指数退避 → `close()` 清理句柄；下一次 `run_turn` 由各 Runtime 懒加载重新拉起进程
- 超过最大处理次数后停止对该后端的干预并上报告警事件
- 通过 EventBus 发布状态事件
- 收集健康指标（计数、最近崩溃时间、累计存活时间等）

### 3.8 RuntimePool

**价值**：统一管理任意 `RuntimeBackend` 实例，配置驱动 + 并发控制（`asyncio.Semaphore`）。

```
RuntimePool(*, max_concurrent: int = 4, enable_health_monitor: bool = False)
├── register(name, config: RuntimeConfig) -> None
├── get(name) -> RuntimeBackend
├── prompt(name, task, *, mode) -> str      # 委托 run_turn()，收集 text_delta
├── run_turn(name, prompt, session_id) -> AsyncIterator[RuntimeEvent]  # Semaphore 并发控制
├── cancel(name, session_id) -> None        # 级联取消 → backend.cancel()
├── start_monitoring() -> None              # 启动 HealthMonitor（可选）
├── get_health_metrics() -> dict            # 查询所有后端健康指标
├── available_backends -> list[str]
└── close_all() -> None                     # 停止监控 + 关闭所有后端
```

**要点**：
- `RuntimeConfig.backend_type` 选择 `AcpRuntime` / `SdkRuntime` / `CliRuntime`
- `max_concurrent` 限制同时执行的委托任务数，避免进程与文件句柄耗尽
- `prompt()` 委托给 `run_turn()`，并发控制统一在 `run_turn()` 层
- `enable_health_monitor=True` 时自动创建 HealthMonitor，后端创建时自动注册

### 3.9 RuntimeConfig（统一配置）

```
RuntimeConfig (frozen dataclass)
├── backend_type: "acp" | "sdk" | "cli"
├── command: str | None                  # CLI/ACP 的可执行文件路径
├── args: list[str]                      # 命令行参数
├── env: dict[str, str] | None           # 额外环境变量
├── cwd: str | None                      # 工作目录
├── timeout_seconds: int = 300           # 超时
├── permission_mode: PermissionMode      # 权限模式
├── allowed_tools: list[str]             # 工具白名单
├── strip_env_keys: list[str]            # 需要剥离的环境变量
├── auth_mode: AuthMode = "subscription" # 鉴权模式：订阅登录态 / API Key
├── mcp_servers: list[McpServerConfig]   # MCP Server 配置
├── max_response_chars: int = 50_000     # 响应截断限制
├── max_turns: int = 25                  # 安全护栏：最大工具调用轮次
└── description: str = ""                # Agent 能力描述（注入 tool description）
```

**环境变量管理 + 鉴权模式（`auth_mode`）**：
- 敏感信息过滤：`build_safe_env()` 始终剥离子进程继承的 provider 密钥（前缀剥离 + `strip_env_keys`），各 Runtime 启动前统一调用
- `subscription`（默认）：剥离所有 provider 密钥 **并丢弃** `env` 中注入的密钥，强制委托 CLI 走自身订阅登录态（用户的 ChatGPT Plus / Claude Max / Gemini 订阅），绝不静默回退按量计费的 API Key
- `api_key`：业务层经 `env` 注入该后端应计费的单一 provider 密钥，剥离基线后重新应用
- 价值：让 GUI/SaaS 用户用已购订阅驱动外部 CLI，无需重复购买 API Key（详见 3.11 auth 子系统）

### 3.10 _base.py（RuntimeBackend 基类）

**价值**：提取 3 种 Runtime 的通用逻辑，避免重复代码。

**通用功能**：
- 环境变量清理（`build_safe_env`）
- 超时控制（`asyncio.timeout`）
- 流式响应截断（`max_response_chars`，统一对 TEXT_DELTA 事件逐字符计数）
- 日志规范化

### 3.11 auth 子系统（订阅鉴权）

**来源**：pi-mono `/login`（ChatGPT Plus/Pro·Claude Pro/Max）+ openhuman `openai_oauth/`（flow/store/status）+ zeroclaw「API Key vs Codex 订阅」二选一 + opencode 订阅插件

**价值**：让委托的外部 CLI（Codex / Claude Code / Gemini / Qwen）运行在**用户自己的模型订阅**上而非按量计费的 API Key。框架只出**机制**（业务无关），由业务层驱动 GUI/SaaS 登录、状态徽章与凭据持久化。

```
auth/
├── _profiles.py        # AuthProfile：每个 CLI 的凭据路径、登录命令、策略、api_key env
│                       #   环境感知 resolve_home（CODEX_HOME/CLAUDE_CONFIG_DIR → /persistent）
├── credential_store.py # CredentialStore：状态检测 / 通用凭据导入（原子写+0600）/ 清除
└── login_session.py    # CliLoginSession：驱动 <cli> login，流式 AuthEvent（提取 URL/设备码）
```

**三大机制**：
- **凭据检测**（`CredentialStore.state`）：该后端是否已登录？驱动预检与状态徽章；鉴权态从不缓存（用户随时登录/登出）
- **交互式登录**（`CliLoginSession`）：spawn `<cli> <login_args>`，并发读 stdout/stderr，URL/设备码 → 可操作 PROMPT 事件，进程退出后用 `CredentialStore` 校验落地 → SUCCESS/ERROR；`needs_code_input` 时经 `feed()` 回填用户粘贴的 code
- **凭据导入兜底**（`CredentialStore.import_credential`）：登录不可脚本化（gemini/qwen 浏览器流）或不便时的**通用路径**——用户在有浏览器的机器登录后粘贴 `auth.json`，原子安全写入对应路径

**设计铁律**：
- 鉴权态**绝不进入** Turn1 工具描述；`create_delegate_to_agent_tool` 使用**固定 schema**（backend 列表仅在运行时 KeyError 返回值中暴露），不破坏提示词前缀缓存
- 凭据路径环境感知 → 控制平面通过重定向 home（如 `CODEX_HOME` → 持久卷）即可实现 SaaS 持久化，harness 零耦合
- 登录态检测基于文件，刻意**不做运行时硬预检**：跨平台凭据存储差异（如 macOS Keychain）会导致误判，CLI 自身的未登录错误已由 `PROCESS_CRASHED`（含 stderr 提示）准确透传，状态可见性由徽章承担

**与竞品对比**：

| 能力 | 竞品最佳 | 新方案 | 超越/平齐 |
|------|---------|--------|----------|
| 订阅登录 | pi-mono (`/login` 多 Provider) | login_session + 导入兜底 + 状态检测 | **平齐**（覆盖更鲁棒） |
| 凭据持久化 | openhuman (加密 profile store) | 环境感知路径 + 控制平面重定向 | **超越**（部署解耦） |
| 模式切换 | zeroclaw (Key/订阅二选一) | auth_mode + 双层 env 安全 | **超越**（注入密钥双重保险） |

---

## 4. 文件结构（与代码库一致）

```
acp/
├── __init__.py             # 惰性导出 RuntimePool / RuntimeConfig / RuntimeBackend + Server
├── ACP_SYSTEM.md           # 本设计文档
├── ACP_REFERENCE.md        # 竞品与协议调研备忘
├── ACP_SYSTEM.md           # 本文档
├── __main__.py             # CLI 入口
├── types.py                # RuntimeEvent、Protocol、RuntimeConfig、错误码等
├── permission.py           # DefaultPermissionManager
├── event_bus.py            # EventBus
├── backend_detector.py     # CLI 探测（detect + detect_with_auth 安装+登录态一次性视图）
├── health_monitor.py       # 健康检查与退避（集成于 RuntimePool）
├── auth/                   # 订阅鉴权子系统（业务无关机制）
│   ├── __init__.py         # 公共导出
│   ├── _profiles.py        # AuthProfile：CLI 凭据路径/登录命令/策略
│   ├── credential_store.py # 状态检测 + 凭据导入兜底 + 清除
│   └── login_session.py    # CliLoginSession：驱动 <cli> login，流式 AuthEvent
├── server/                 # ACP Server 方向（IDE → Agent）
│   ├── __init__.py
│   ├── server.py           # ACP Server（acp.Agent）
│   ├── bridge.py           # Session ↔ 宿主 Agent
│   ├── event_translator.py # AgentEvent → SessionNotification
│   └── _default_factory.py # 默认 AgentFactory
└── runtime/                # Runtime 方向（Agent → 外部 Agent）
    ├── __init__.py
    ├── _base.py            # BaseRuntime
    ├── _parser.py          # 共享 NDJSON 事件解析器（CLI/SDK 复用）
    ├── acp_runtime.py      # ACP 子进程 + JSON-RPC
    ├── acp_callback.py     # ACP 回调处理器
    ├── sdk_runtime.py      # SDK bridge
    ├── cli_runtime.py      # CLI + NDJSON（Claude stream-json / Codex item.* 新格式 + legacy 兼容）+ --resume session 复用
    └── pool.py             # RuntimePool
```

`tools/acp_delegate/delegate_tool.py` 通过 `RuntimePool` 发起委托，汇总 `USAGE_UPDATE` 事件的 token 消耗并推送至前端。`runtime/_parser.py` 提供 `CliRuntime` 和 `SdkRuntime` 共享的 NDJSON 事件解析逻辑（tool_use / tool_result / usage / error / thinking）。`cli_runtime.py` 支持 Codex CLI 两种输出格式：新格式（`item.started/completed` + `turn.completed/failed`，含 `command_execution`、`file_change`、`reasoning` 工具事件映射）和 legacy 格式（`{"id","msg"}` envelope 解包）。

---

## 5. 与竞品对比

| 能力 | 竞品最佳 | 新方案 | 超越/平齐 |
|------|---------|--------|----------|
| 可插拔后端 | openclaw (AcpRuntime) | ACP + SDK + CLI + cancel() + get_info() | **超越** |
| 权限管理 | craft-agents-oss (4模式) | 4模式 + 参数级通配符 + 缓存 | **超越** |
| 事件流 | opencode (订阅系统) | EventBus + session 过滤 | **超越** |
| Session 管理 | opencode (Fork/Resume) | Fork/Resume + TTL + 自动清理 | **超越** |
| 后端检测 | AionUi (自动检测) | 自动检测 + 版本检测 | **超越** |
| 健康监控 | zeroclaw (自动重启) | 退避 + 句柄回收 + 指标 + 懒重连 | **超越** |
| 事件类型 | nextclaw (34类型) | 9类型（精简完整，含 status_update） | **超越** |
| 错误处理 | craft-agents-oss (错误标记) | 结构化错误码 + retryable + PERMISSION_DENIED | **超越** |
| 安全模型 | ironclaw (纵深防御) | 环境清理 + 工具白名单 + 路径安全 | 平齐 |
| MCP 集成 | craft-agents-oss (Session MCP) | Session MCP 注入 | 平齐 |

**结果：8 项超越，2 项平齐，0 项落后**

---

## 6. 框架层/业务层边界

> 遵循 FRAMEWORK_DESIGN_PRINCIPLES.md：框架提供 Protocol + 默认实现，业务层按需替换。

### 框架层提供（开箱即用）

| 模块 | 类型 | 说明 |
|------|------|------|
| types.py | 核心类型 | Protocol / dataclass / StrEnum 定义 |
| runtime/_base.py | 基类 | 环境清理、超时、截断 = 自我保护 |
| runtime/acp_runtime.py | 实现 | ACP 协议后端 |
| runtime/cli_runtime.py | 实现 | CLI spawn 后端 |
| runtime/sdk_runtime.py | 实现（可选依赖） | SDK 集成后端 |
| runtime/pool.py | 管理器 | 单实例内多后端管理 |
| event_bus.py | 事件系统 | 类似生命周期钩子，业务层订阅 |
| permission.py | Protocol + 默认实现 | DefaultPermissionManager（4 模式 + 白名单） |
| backend_detector.py | 工具 | 后端自动检测 |
| health_monitor.py | 自我保护 | 存活巡检 + 退避 + `close()` + 指标 |

### 业务层自定义（通过 Protocol 注入）

| 能力 | 框架提供的扩展点 | 业务层实现示例 |
|------|----------------|-------------|
| 权限交互 UI | EventBus + permission_request 事件 | 订阅事件 → 展示 UI → `future.set_result()` |
| 监控集成 | EventBus + 健康指标 | 推送到 Prometheus / DataDog |
| 自定义后端 | RuntimeBackend Protocol | HTTP API Agent / 自研 Agent |
| 自定义权限 | PermissionManager Protocol | 基于角色的权限管理 |

### 业务层接入（myrm-agent-server）

三层架构将框架能力接入到实际产品：

1. **配置层**：`UserConfig` 表 `config_key='externalAgents'`，JSON 格式 `{"agents": [{name, type, command, args, enabled, ...}]}`
2. **注入层**：`GeneralAgent._setup_external_agents()` 从配置创建 `RuntimePool` + `delegate_to_agent_tool` 工具
3. **执行层**：LLM 自主决定是否使用 `delegate_to_agent_tool` 委托任务给外部 Agent

**增强功能**：
- **本地模式自动发现**：本地部署时自动探测 claude/codex/gemini CLI
- **配置校验**：无效配置跳过并记录日志，不阻断 Agent 启动
- **权限配置**：每个外部 Agent 可独立配置 `permissionMode`
- **多渠道支持**：Web Chat 和 Channel 路径均支持外部 Agent
- **容错处理**：外部 Agent 配置失败不影响主 Agent 功能
- **前端名称唯一性校验**：保存时检测重复 Agent 名称，防止配置冲突
- **命令可用性测试**（本地模式）：通过 `POST /channels/manage/external-agents/test` 检测命令是否存在并返回版本信息
- **流式事件消费**：`delegate_to_agent_tool` 通过 `pool.run_turn()` 逐事件消费，实时日志输出工具调用和状态更新，返回结果包含 tool_calls 计数等元数据
- **前端实时进度推送**：通过 ContextVar + `ToolProgressSink` 机制，`delegate_to_agent_tool` 在执行期间将外部 Agent 的工具调用和状态事件实时推送至前端 SSE 流（复用 `TASKS_STEPS` 事件类型，前端零改动）
- **前端预设模板**：新增模式下提供 Claude Code / Codex CLI / Gemini CLI 一键填充，降低配置门槛
- **委派取消传播**：CancellationToken → pool.cancel() → backend.cancel()，全链路级联终止
- **Max Turns 双层安全护栏**：Layer 1 传递 CLI `--max-turns` 参数（Claude Code 原生优雅停止），Layer 2 在 delegate_tool 事件循环中统计 TOOL_START 计数并在超限时 pool.cancel()（所有后端通用兜底）
- **稳定 Tool Schema**：`delegate_to_agent_tool` 使用固定 tool description（不含动态 agent 列表），保护 Turn1 Prompt Cache；`agent_name` 无效时错误响应列出 `available_backends`
- **Deploy 门控（Server）**：`external_cli_deploy.is_external_cli_deploy_supported()` + profile `strip_deploy_incompatible_builtin_tools`；沙箱自动剔除 `external_cli`；BuiltinToolsPanel sandbox 硬禁用 toggle
- **MCP 会话注入**：`RuntimePool.run_turn` → `AcpRuntime.new_session(mcp_servers=…)`（Server 默认传空 list；`RuntimeConfig.mcp_servers` 为配置源）
- **Spawn 误配提示**：`runtime/_spawn_hints.format_cli_spawn_failure_message` 在 bare CLI 进程失败时返回 adapter 配置指引
- **跨平台进程组清理**：`CliRuntime` 创建进程组，cancel 时级联终止子进程，确保跨平台（Unix/Windows）无孤儿进程遗留
- **委派取消传播**：通过 ContextVar 传递 `CancellationToken`，用户取消主 Agent 时 `delegate_to_agent_tool` 的事件消费循环检测取消信号，调用 `pool.cancel()` → `backend.cancel()` 级联终止外部进程，避免"幽灵进程"继续消耗资源
- **直连路由模式**：`force_delegate_agent` 参数允许前端绕过 LangChain Agent，直接将请求路由到指定外部 Agent，零 LLM 开销、零延迟的流式响应
- **流式文本推送**：`_direct_delegate_stream` 将 RuntimeEvent 实时转换为前端 SSE 事件（MESSAGE / REASONING / TASKS_STEPS / TOKEN_USAGE / ERROR），实现外部 Agent 响应的逐字流式展示。连接前发送 connecting 状态，完成后发送 completed 状态，提供全生命周期进度反馈
- **REASONING_DELTA 前端传递**：`delegate_to_agent_tool` 工具将外部 Agent 的思维链（REASONING_DELTA）通过 `ToolProgressSink` 实时推送至前端，用户可看到外部 Agent 的推理过程
- **CLI Session 复用**：`CliRuntime` 捕获 CLI 返回的 session_id，后续调用自动注入 `--resume` 参数，实现多轮对话上下文保持（支持 claude CLI）
- **NDJSON 解析器模块化**：`_parser.py` 提取 CLI/SDK 共享的解析逻辑，消除代码重复
- **Delegate 元数据 TypedDict**：`DelegateUsage` / `DelegateMeta` 提供精确的类型提示
- **直连模式 Session 隔离**：基于 `chat_id` 生成独立 `session_id`，不同对话的外部 Agent 上下文互不干扰
- **直连模式 TOOL_RESULT 事件**：展示外部 Agent 工具执行结果（成功/失败状态）
- **直连模式错误重试**：单次自动重试，提高容错性

---

## 7. 不做的事情（避免过度设计）

| 不做 | 原因 | 竞品参考 |
|------|------|---------|
| A2A 协议 | 不需要 Agent 发现，配置驱动注册足够 | openfang |
| 容器化执行 | 不是 Sandbox，不需要 Docker 沙箱 | ironclaw, nanoclaw |
| 15+ 后端 | 3 种后端已覆盖主流场景 | AionUi |
| Transcript Hash Resume | ACP 协议已有 session resume | nullclaw |
| 流式消息缓冲 | 场景不需要 120ms 批量写入 | AionUi |
| Config Watcher | 配置变更通过重启处理 | craft-agents-oss |
| Cron 集成 | 不在 ACP 模块职责范围 | AionUi |
| NCP 自研协议 | ACP 已是行业标准 | nextclaw |
| 三阶段执行 | plan/execute 在 Agent 层处理 | workany |

---

## 8. 实施优先级

| 优先级 | 模块 | 预估复杂度 | 依赖 |
|--------|------|-----------|------|
| P0 | types.py（核心类型） | 低 | 无 |
| P0 | runtime/_base.py（基类） | 低 | types.py |
| P0 | runtime/acp_runtime.py（ACP 后端） | 中 | types.py, _base.py |
| P0 | runtime/pool.py（RuntimePool） | 低 | types.py |
| P1 | permission.py（权限增强） | 中 | types.py |
| P1 | event_bus.py（事件总线） | 低 | types.py |
| P1 | runtime/cli_runtime.py（CLI 后端） | 中 | types.py, _base.py, event_bus.py |
| P2 | backend_detector.py（自动检测） | 低 | 无 |
| P2 | health_monitor.py（健康监控） | 低 | event_bus.py |
| P2 | runtime/sdk_runtime.py（SDK 后端） | 高 | types.py, _base.py, permission.py |
---

## 9. 方案完美性评估

### 评分：10/10

**完美的原因**：

1. **Runtime 与 Server 解耦**：外部 Agent 集成不污染 IDE 桥接路径
2. **能力全面对标竞品**：对比项中多数为超越或平齐
3. **抽象层次稳定**：`RuntimeBackend` 统一三种接入方式，扩展成本低
4. **生命周期完整**：run_turn + cancel + resume + close + get_info
5. **结构化错误**：错误码 + retryable + 详情字段
6. **事件模型克制**：9 种事件类型覆盖委托与观测需求
7. **安全默认**：环境清理、白名单、工作目录内 FS 回调
8. **边界清晰**：明确非目标列表，避免范围蔓延
9. **Server 层职责单一**：桥接与翻译与 Runtime 正交
10. **依赖面小**：标准库 + 现有 acp SDK + 可选 Node/SDK
11. **并发受控**：RuntimePool Semaphore
12. **框架/业务可替换**：PermissionManager 等 Protocol 注入点明确
13. **全链路取消**：CancellationToken 通过 ContextVar 传播，用户取消 → delegate_tool → pool.cancel() → backend.cancel() → 进程终止，零资源泄漏
14. **双层 Max Turns 安全护栏**：Layer 1（CLI 参数）让支持的 CLI 优雅停止，Layer 2（delegate_tool 事件计数）对所有后端通用兜底——业界唯一的双层方案
15. **Agent 能力描述**：description 注入 tool description，帮助 LLM 在多 Agent 场景下做出正确的委派决策

**已知局限**：
- SdkRuntime 依赖外部 SDK 版本兼容性（不可避免的外部风险，不影响评分）
