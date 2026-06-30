# Myrm Agent Harness - 架构文档

> **许可**: Proprietary（见 [LICENSE](LICENSE) 与 `pyproject.toml`）。框架层不与业务逻辑耦合，类似 LangChain，供 `myrm-agent-server` 等业务项目引用。

> 📐 本项目采用分形自文档结构，通过 INPUT/OUTPUT/POS 三元组和文件夹架构文档形成自组织系统。

> 📖 **框架设计原则**：请参考根目录的 [FRAMEWORK_DESIGN_PRINCIPLES.md](FRAMEWORK_DESIGN_PRINCIPLES.md)。  
> 📁 **子目录职责表**：见 [_ARCH.md](_ARCH.md)。

---

## 📑 目录

- [架构概览](#️-架构概览)
- [模块导航](#-模块导航)
- [核心依赖](#-核心依赖)
- [核心依赖关系](#-核心依赖关系)
- [文档导航](#-文档导航)
- [AI 工作流程](#-ai-工作流程)
- [项目状态](#-项目状态)

---

## 🏗️ 架构概览

Myrm Agent Harness 是一个**GUI-first 通用 AI 工作助手运行时框架**（WebUI / Tauri / 云沙箱嵌入），基于 LangChain/LangGraph 构建，提供：

- 完整的技能系统（Skill System），支持**自动技能提炼与补丁进化引擎 (Auto-Skill Extraction & Patching)**，并通过 `SkillFailureEvent` 将运行时技能失败以框架 DTO 非阻塞抛给业务层
- Agent-in-Sandbox 沙箱执行（LocalExecutor，业务层可扩展云端沙箱）
- 智能上下文管理（Filtering/Compression/Summarization），支持**Prompt 记忆快照与绝对预算锁定 (Strict Prompt Budgeting)**
- Protocol-backed `conversation_search` 历史会话召回工具：框架只处理 DTO、格式化、引用事件，不依赖数据库、Server 或产品身份语义
- **Task-Adaptive Context (任务自适应执行边界)**：JIT 证据注入，通过历史 Trace 提取防错经验（Anti-patterns/Hotspots），严格保护 Prompt Prefix Cache
- **Smart Concurrency Router**：基于资源指纹和 O(1) 路径互斥判断的智能并发引擎，无论并发读写还是读读，均实现绝对安全的文件级操作调度
- **Myrm-Guard (AI Diagnostic & Self-Healing)**：主动式熔断、错误脱敏、前端一键修复与 Tool Integrity Guard
- **动态重规划纠错引擎 (Dynamic Replan Loop)**：拦截工具执行错误并交由 LLM 自我纠错
- **Harness 引擎参数化 (Engine Parameterization)**：中间件核心参数（如 `max_tool_calls`, `max_replan_attempts`）完全数据化，支持按 Agent 实例动态配置，为未来的 Agentic 自进化奠定基础
- Claude Code 兼容的 Hook 系统
- 高性能存储和缓存系统
- **真正的零阻塞后台守护进程 (Zero-Blocking Background Worker)**：将记忆落盘和复盘任务转移到后台，保证零延迟响应

它的定位是**可复用的单机 Agent 运行时框架**：既可被 `local web` / `tauri` 形态直接嵌入，也可被 `SaaS / enterprise` 的每用户沙箱复用；但它本身**不定义最终产品形态**，也**不承接多租户身份、控制平面编排或 GUI 交互语义**。

**核心特性**：

- **框架-业务分离**：框架层不依赖业务层，通过 [自动化检测与修复](scripts/_ARCH.md) 保护架构完整性；`toolkits/` 禁止 import `agent/`（`tests/architecture/test_toolkits_agent_boundary.py`）；`toolkits/` 禁止 vendor 工具包/浅层 vendor 模块名（`tests/architecture/test_toolkits_vendor_boundary.py`；见 [toolkits/_ARCH.md](src/myrm_agent_harness/toolkits/_ARCH.md)、[TOOL_DESIGN_STRATEGY.md](src/myrm_agent_harness/agent/tool_management/TOOL_DESIGN_STRATEGY.md) §1.2）
- **子智能体预算硬终止 (Subagent Budget Hard-Stop)**：基于 `TokenTracker` 和底层事件转发器实施严格预算审查拦截，杜绝无限自愈或死循环导致用户余额击穿。
- **子智能体跨层异步审批 (Asynchronous Escalation)**：基于 LangGraph 原生 `NodeInterrupt` 的穿透式中断架构，实现自主体级高危操作前端 GUI 拦截。父子双图协同挂起，完全释放服务器并发资源，避免网关强制超时，并 100% 保护大模型前缀缓存。
- **防宕机全双工终端流 (Safe Full-Duplex Terminal)**：从底层 PTY 拦截并流式下发数据，内置 10FPS 节流与 500KB 流量熔断阀门，物理阻绝 SSE 瀑布流 DDOS 攻击导致的浏览器白屏
- **协议驱动**：3 个核心协议（`SandboxExecutor`, `StorageProvider`, `SkillBackend`）
- **性能优先**：智能缓存（7x 加速）、异步 I/O、高效算法
- **类型安全**：100% 类型覆盖，禁止 `Any` 类型

---

## 📦 模块导航

| 模块       | 路径                                | 职责                                                                                                                                                                                                                               |
| ---------- | ----------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Core 层** | `myrm_agent_harness/core/`         | **框架无关基础能力层**。提供 security（安全检测/审计/防护）、config（LLM 配置）、events（事件类型/流式枚举）、hooks（Hook 类型定义/生命周期事件）、artifacts（工件类型/映射常量）。同时被 `agent/` 和 `toolkits/` 引用，消除二者间的耦合 |
| **Public API** | `myrm_agent_harness/api/`       | **闭源分发公开接口**。第三方框架与 server 的唯一推荐 import 路径（factory、Protocol、DTO）。详见 [DISTRIBUTION_SYSTEM.md](harness_packaging/DISTRIBUTION_SYSTEM.md) |
| Agent 核心 | `myrm_agent_harness/agent/`         | BaseAgent / SkillAgent 运行时；模块导航见 [agent/_ARCH.md](src/myrm_agent_harness/agent/_ARCH.md) |
| SDK 入口   | `myrm_agent_harness/client.py`      | SDK Facade — `AgentClient` 便利层；**PyPI 稳定契约**见 `api/`                                                                                                                                                          |
| ACP 薄入口 | `myrm_agent_harness/agent/acp/`    | 独立 ACP Server 的 default factory 与 CLI 入口；完整 ACP runtime 在 `toolkits/acp/`                                                                                                                                                |
| 后端抽象层 | `myrm_agent_harness/backends/`      | Profile / Secret / Skill 三类存储后端的 Protocol 与 Local/Memory/Storage 实现；Skill 热重载失效信号持久化于 `MYRM_DATA_DIR/.skill_config_version`（server re-export）；公开扩展点见 `api/protocols`                                                                                                                      |
| 基础设施层 | `myrm_agent_harness/infra/`         | 提供通用机制：统一文件锁、消息投递队列（StorageProvider + 弹性机制 + Metrics）、链路追踪、增量状态监控                                                                                                                             |
| 运行时层   | `myrm_agent_harness/runtime/`       | Agent 单实例运行时基础设施，管理 Agent 生命周期与执行环境                                                                                                                             |
| 功能标志   | `myrm_agent_harness/core/features/` | Feature Flag 引擎，支持功能生命周期管理与运行时动态配置查询                                                                                                                                                                        |
| 诊断自检   | `myrm_agent_harness/observability/diagnostics/` | Diagnostic Protocol — 健康探针、benchmark probes，暴露各组件“为什么不能工作”的原因                                                                                                                                    |
| 观测监控层 | `myrm_agent_harness/observability/` | 提供全局 Prometheus 监控基建，记录 Agent 运行时关键指标（执行耗时、工具调用、Token 消耗等）                                                                                                                                        |
| 评估测试层 | `myrm_agent_harness/eval/`          | 提供 Agent 行为评估与自动化测试框架，支持并发执行与沙箱原生断言                                                                                                                                                                    |
| 工具包集合 | `myrm_agent_harness/toolkits/`      | **通用工具模块集，不与 Agent 框架耦合，可独立使用**。`__init__.py` 为通用能力导出入口，`xx_agent_tools.py` 导出 Agent 工具。提供沙箱执行、存储缓存、检索系统、知识库、网络搜索、浏览器自动化、agentic 工作区 grep/glob、ContextBundle、MCP 集成、定时任务、多平台通道、语音生成 (TTS) 等能力 |
| 工具函数库 | `myrm_agent_harness/utils/`         | 提供通用工具函数（错误处理、日志、文本处理、Token 追踪、URL 工具）                                                                                                                                                                 |
| 测试套件   | `tests/`                            | 单元测试、集成测试、沙箱测试、性能测试；公开 API 冒烟见 `tests/api/`                                                                                                                                               |
| 性能基准   | `benchmarks/`                       | CI 回归基准（startup、boundary）；`archive/` 存放非门禁历史脚本                                                                                                                                                                    |
| **分发构建** | `harness_packaging/`              | 闭源分发：`codegen.py`、`assemble.py`、core manifest（`directories` SSOT）、Nuitka 编译、release wheel 源码剥离。详见 [DISTRIBUTION_SYSTEM.md](harness_packaging/DISTRIBUTION_SYSTEM.md) |

### 跨层概念映射

同名概念分布在不同层级，职责不同；**不要合并目录**。

| 概念 | 目录 | 职责 |
|------|------|------|
| **Security** | `core/security/` | 框架无关安全原语（path policy、redact、tool registry、detection/guards、credential vault） |
| | `agent/security/` | Agent 安全引擎（HITL、rate limiter、transcript classifier）；多数模块 re-export `core/security/` |
| | `infra/security/` | 基础设施层安全辅助（与 delivery/locks 协同） |
| **Events** | `core/events/` | 框架级事件类型与流式枚举（agent/ 与 toolkits/ 共享） |
| | `runtime/events/` | 单实例运行时事件分发与生命周期 |
| | `infra/events/` | 基础设施事件（delivery 队列等） |
| **Observability** | `observability/` | 全局 Prometheus metrics + Diagnostic Protocol |
| | `agent/observability/` | Agent 运行时 EventBus 订阅与业务可观测性桥接 |
| | `infra/tracing/` | OpenTelemetry 链路追踪与 tracing metrics |
| **ACP** | `agent/acp/` | 独立 Server 场景的 default factory + `__main__` CLI |
| | `toolkits/acp/` | ACP runtime、server、toolchains 完整实现 |

---

## 🔧 核心依赖

### 语言与框架

- **Python**: >= 3.13（见 `pyproject.toml`）
- **LangChain**: >= 1.3.4（Agent 框架，见 `pyproject.toml`）
- **LangGraph**: >= 1.2.4（流程编排，见 `pyproject.toml`）

### 核心库

| 类别         | 库                                | 用途                          |
| ------------ | --------------------------------- | ----------------------------- |
| **类型系统** | Pydantic >= 2.0.0                 | 数据验证和类型定义            |
| **异步 I/O** | aiofiles, httpx, aiosqlite        | 文件、网络、SQLite 异步操作   |
| **HTML**     | beautifulsoup4, lxml              | 网页剪枝与 DOM 解析           |
| **Checkpoint** | langgraph-checkpoint-sqlite, dill | 会话状态持久化与序列化      |
| **沙箱执行** | Docker SDK                        | 容器化代码执行                |
| **存储**     | aiofiles                          | 本地文件系统存储              |
| **检索**     | rank-bm25, jieba, tenacity (`[retrieval]`) | BM25、分词与云 embedding 重试 |
| **浏览器**   | patchright                        | Playwright 超集，浏览器自动化 |
| **文件解析** | pdfplumber（core）                | PDF 文本+表格提取（默认安装） |
| **工具**     | nanoid                            | 唯一 ID 生成                  |

### 可选依赖（extras）

- **`[web]`**: scrapling[fetchers]（L1 HTTP / L3 stealth 爬取）, youtube-transcript-api（YouTube 字幕快路径；缺失时 fallback HTML）
- **`[file-parsers]`**: pypdfium2, python-docx, openpyxl, python-pptx（Office 与 PDF 页面渲染；pdfplumber 已在 core）
- **`[retrieval]`**: numpy, jieba, rank-bm25, tenacity（云 embedding 重试）
- **`[browser]`**: patchright, orjson（浏览器自动化与会话持久化 JSON）
- **`[observability]`**: opentelemetry-sdk, opentelemetry-exporter-otlp-proto-grpc, openinference-instrumentation-langchain（Phoenix / OTLP 追踪；`opentelemetry-instrumentation` 由 openinference 传递依赖）
- **`[compiled-core]`** / **`[compiled-core-musl]`**: 平台 native 扩展 wheel（8 平台，见 `harness_packaging/DISTRIBUTION_SYSTEM.md`）
- **`[all]`**: 包含上述全部 extras（含 `[web]`）
- **E2B / S3 / ripgrep**: 由业务层或运行时可选接入

---

## 🔗 核心依赖关系

### 层次依赖（纵向）

```
SkillAgent (技能 Agent)
  ↓ 继承
BaseAgent (基础 Agent)
  ↓ 编排
├─ runtime/ (运行时基础设施)
│   ├─ MessageBuilder (消息构建)
│   ├─ StreamExecutor (流式执行)
│   ├─ EventHandlers (事件处理)
│   ├─ SourceTracker (引用追踪)
│   ├─ ArtifactEvents (工件事件)
│   ├─ compression (文件压缩工具)
│   ├─ storage_monitor (存储监控)
│   ├─ quota_protocol (配额检查协议)
│   ├─ quota_errors (配额异常定义)
│   ├─ sandbox_paths (路径管理)
│   └─ context_metrics (实例级监控指标)
│
├─ context_management/ (上下文工程)
│   ├─ ContextPipeline (上下文管道)
│   ├─ strategies/ (过滤/压缩/摘要策略)
│   └─ tracking/ (压缩、归档、恢复 outcome 与读取成本指标)
│
├─ hooks/ (Hook 系统)
│   ├─ HookMiddleware (生命周期钩子)
│   └─ HookOutputSpiller (超大输出磁盘溢写)
│
├─ file_snapshot/ (文件快照)
│   ├─ FileSnapshotProtocol (快照协议)
│   ├─ LocalFileSnapshotStore (本地文件快照存储)
│   └─ AutoSnapshotInterceptor (自动快照拦截器)
│
├─ middlewares/ (中间件)
│   ├─ ContextPipelineMiddleware (上下文管道)
│   ├─ ToolApprovalMiddleware (工具审批)
│   └─ SecurityGuardrailMiddleware (安全护栏)
│
├─ goals/ (目标引擎与状态机)
│   ├─ GoalManager (目标生命周期)
│   ├─ GoalStorage (持久化)
│   └─ check_continuation (续跑检查)
│
├─ meta_tools/ (Agent 元工具)
│   ├─ bash/ (Bash 执行)
│   ├─ file_ops/ (文件操作)
│   ├─ http/ (HTTP 请求)
│   └─ skills/ (技能发现/搜索/选择)
│
├─ skills/ (技能系统)
│   ├─ SkillLoader (技能加载)
│   └─ mcp/ (MCP 集成)
│
└─ security/ (安全系统 — re-export from core/security)
    ├─ ContentBoundary (内容边界)
    ├─ LeakDetector (泄露检测)
    └─ PromptGuard (注入防护)
```

### 协议依赖（横向）

```
Agent 层
  ↓ 依赖协议
├─ SandboxExecutor (toolkits.execution)
│   └─ 实现：LocalExecutor（内置），E2BExecutor（业务层）
│
├─ StorageProvider (toolkits.storage)
│   └─ 实现：LocalBackend, SmartCachedStorage
│
└─ SkillBackend (backends.skills)
    └─ 实现：LocalSkillBackend, StorageSkillBackend, CompositeSkillBackend
```

### 模块依赖（整体）

```
core/ (框架无关基础层 — 被 agent/ 和 toolkits/ 共享)
  ├─ security/   (安全类型、检测、防护、审计)
  ├─ config/     (LLMConfig 等通用配置)
  ├─ events/     (AgentEventType、流式事件定义)
  ├─ hooks/      (HookEvent、HookResult 等类型定义)
  └─ artifacts/  (ArtifactType、扩展名映射常量)

agent/ (运行时核心层)
  ↓ 依赖 core/ + 下列模块
├─ backends/ (抽象层)
├─ toolkits/ (工具层 — 仅依赖 core/，不依赖 agent/)
│   ├─ code_execution/ (沙箱代码执行)
│   ├─ storage/ (存储缓存)
│   ├─ web_fetch/ (网页抓取)
│   ├─ retriever/ (检索系统)
│   ├─ browser/ (浏览器自动化)
│   ├─ computer_use/ (Semantic Desktop Control — AX @dref + vision fallback)
│   ├─ mcp/ (MCP 集成)
│   ├─ cron/ (定时任务)
│   ├─ memory/ (记忆系统)
│   └─ llms/ (LLM 管理)
└─ utils/ (基础层)
```

---

## 📋 文档导航

### 项目文档

- [README.md](README.md) - 项目说明、快速开始、API 使用指南、安装说明

### 技术方案文档（L2 索引）

| 文档 | 模块 |
|------|------|
| [MEMORY_SYSTEM.md](src/myrm_agent_harness/toolkits/memory/MEMORY_SYSTEM.md) | 记忆系统 |
| [BROWSER_SYSTEM.md](src/myrm_agent_harness/toolkits/browser/BROWSER_SYSTEM.md) | 浏览器自动化 |
| [DESKTOP_SYSTEM.md](src/myrm_agent_harness/toolkits/computer_use/DESKTOP_SYSTEM.md) | Semantic Desktop Control |
| [EXECUTION_SYSTEM.md](src/myrm_agent_harness/toolkits/code_execution/EXECUTION_SYSTEM.md) | 沙箱代码执行 |
| [STORAGE_SYSTEM.md](src/myrm_agent_harness/toolkits/storage/STORAGE_SYSTEM.md) | 存储与缓存 |
| [RETRIEVER_SYSTEM.md](src/myrm_agent_harness/toolkits/retriever/RETRIEVER_SYSTEM.md) | 检索系统 |
| [CONTEXT_BUNDLE_SYSTEM.md](src/myrm_agent_harness/toolkits/context_bundle/CONTEXT_BUNDLE_SYSTEM.md) | ContextBundle |
| [COMMITMENT_SYSTEM.md](src/myrm_agent_harness/toolkits/memory/proactive/COMMITMENT_SYSTEM.md) | Proactive follow-up tracking |
| [SKILL_SYSTEM.md](src/myrm_agent_harness/agent/skills/SKILL_SYSTEM.md) | 技能系统 |
| [META_TOOLS_SYSTEM.md](src/myrm_agent_harness/agent/meta_tools/META_TOOLS_SYSTEM.md) | Agent 元工具层 |
| [SUB_AGENT_SYSTEM.md](src/myrm_agent_harness/agent/sub_agents/SUB_AGENT_SYSTEM.md) | 子智能体 |
| [CONTEXT_MANAGEMENT_SYSTEM.md](src/myrm_agent_harness/agent/context_management/CONTEXT_MANAGEMENT_SYSTEM.md) | 上下文管道实现 |
| [MIDDLEWARE_SYSTEM.md](src/myrm_agent_harness/agent/middlewares/MIDDLEWARE_SYSTEM.md) | 中间件栈 |
| [STREAMING_SYSTEM.md](src/myrm_agent_harness/agent/streaming/STREAMING_SYSTEM.md) | 流式事件管道 |
| [GOAL_SYSTEM.md](src/myrm_agent_harness/agent/goals/GOAL_SYSTEM.md) | 目标系统 |
| [ERROR_SYSTEM.md](src/myrm_agent_harness/agent/errors/ERROR_SYSTEM.md) | 错误系统 |
| [HITL_SYSTEM.md](src/myrm_agent_harness/agent/security/HITL_SYSTEM.md) | HITL 审批 |
| [SECURITY_SYSTEM.md](src/myrm_agent_harness/agent/security/SECURITY_SYSTEM.md) | Agent 安全引擎 |
| [CONTEXT_ENGINEERING.md](src/myrm_agent_harness/agent/context_management/CONTEXT_ENGINEERING.md) | 上下文工程（行业理论） |
| [ACP_SYSTEM.md](src/myrm_agent_harness/toolkits/acp/ACP_SYSTEM.md) | ACP 协议 |
| [TRACE_STORAGE_SYSTEM.md](src/myrm_agent_harness/infra/tracing/TRACE_STORAGE_SYSTEM.md) | Trace 存储 |
| [DISTRIBUTION_SYSTEM.md](harness_packaging/DISTRIBUTION_SYSTEM.md) | 闭源分发 |
| [EVENT_LOG_SYSTEM.md](src/myrm_agent_harness/agent/event_log/EVENT_LOG_SYSTEM.md) | 事件日志 |
| [DYNAMIC_WORKFLOW_SYSTEM.md](src/myrm_agent_harness/agent/dynamic_workflow/DYNAMIC_WORKFLOW_SYSTEM.md) | 动态工作流 |
| [DEEP_RESEARCH_SYSTEM.md](src/myrm_agent_harness/agent/deep_research/DEEP_RESEARCH_SYSTEM.md) | 深度研究 |
| [TOOL_MANAGEMENT_SYSTEM.md](src/myrm_agent_harness/agent/tool_management/TOOL_MANAGEMENT_SYSTEM.md) | 工具管理 |
| [TOOL_DESIGN_STRATEGY.md](src/myrm_agent_harness/agent/tool_management/TOOL_DESIGN_STRATEGY.md) | 工具设计策略 |

> 命名后缀 `*_SYSTEM.md` / `*_DESIGN.md` / `*_STRATEGY.md` 均属 L2；新文档优先 `*_SYSTEM.md`。

### 公开 API 与 SDK 入口

- **PyPI 稳定契约**：`from myrm_agent_harness.api import ...`（factory、Protocol、DTO）
- **SDK 便利层**：`myrm_agent_harness.client.AgentClient` — 简化配置，**不**保证与 release wheel 公开面同步

### 模块架构文档

各模块 `_ARCH.md` 描述文件清单与职责。跨模块技术方案见 `xxx_SYSTEM.md` / `xxx_DESIGN.md`。

---

## 🔄 AI 工作流程

当你进行任何代码分析或修改时，必须遵循以下顺序：

### 阅读顺序（自顶向下）

1. **先阅读 ARCHITECTURE.md** — 理解项目整体架构、模块划分和架构约束
2. **（可选）阅读相关的 xxx_SYSTEM.md** — 如果涉及跨模块的技术方案，阅读对应的技术方案文档
3. **再阅读目标模块的 `_ARCH.md`** — 理解模块文件清单、职责和依赖
4. **再阅读目标文件的头部注释** — 理解 INPUT / OUTPUT / POS

### 更新顺序（自底向上）

当你修改代码时，**必须**按以下顺序更新文档：

1. **修改代码文件**
2. **更新文件头的 I/O/P 注释**（如果依赖或输出变化）
3. **更新目标模块的 `_ARCH.md`**（如果文件新增/删除/职责变化）
4. **更新相关的 `*_SYSTEM.md` / `*_DESIGN.md`**（如果设计/职责变化）
5. **更新技术方案文档 `xxx_SYSTEM.md`**（如果技术方案变化）
6. **更新本文档 `ARCHITECTURE.md`**（如果顶层架构变化）

### 编码原则

**INPUT 必须引用 POS**：

- ✅ 正确：`module_x::ClassName (POS: 数据库连接管理器)`
- ❌ 错误：`module_x::ClassName` 或 `依赖 module_x.py`

**OUTPUT 必须说明能力**：

- ✅ 正确：`DatabaseClient: 提供数据库连接和查询能力`
- ❌ 错误：`DatabaseClient`

**POS 必须清晰**：

- ✅ 正确：`数据库客户端。为业务层提供统一数据库访问接口。`
- ❌ 错误：`处理数据库`

**连锁更新**：当 POS 改变时，必须检查所有引用该 POS 的 INPUT，如果不一致必须更新引用。

### 实际示例

假设有两个文件：`user_service.py` 和 `user_repo.py`

**user_repo.py**：

```python
"""
[INPUT]
无外部依赖

[OUTPUT]
UserRepository: 提供用户 CRUD 操作

[POS]
用户数据访问层。负责用户数据的增删改查操作。
"""
class UserRepository:
    ...
```

**user_service.py**：

```python
"""
[INPUT]
user_repo::UserRepository (POS: 用户数据访问层。负责用户数据的增删改查操作。)

[OUTPUT]
UserService: 用户业务逻辑服务

[POS]
用户服务层。封装注册、登录、信息更新等业务逻辑。
"""
class UserService:
    def __init__(self, repo: UserRepository):
        ...
```

**语义链接**：`user_service.py` 的 INPUT 直接引用了 `user_repo.py` 的 POS，形成语义网络。

**自愈触发**：如果 `user_repo.py` 的 POS 从"用户数据访问层"改为"用户持久化层"，AI 必须同步更新 `user_service.py` 的 INPUT 引用。

---

## 📊 项目状态

### 范围与验证

- **代码**：以 `myrm_agent_harness/` 与 `tests/` 为真源；模块职责见各目录的 `*_SYSTEM.md` / `*_DESIGN.md` 技术方案文档。
- **测试**：默认 `pytest`（串行 + 安全 marker 过滤，见 `tests/_ARCH.md`）；覆盖率策略见 `pyproject.toml` 的 `[tool.coverage.*]`；CI 见 `.github/workflows/test.yml`。
- **性能**：对外宣称延迟、吞吐或加速比时，须附带可复现命令、环境与数据。

### 性能数据（实测）

#### 场景化并发编队与 JIT 架构 (agent/meta_tools/spawn_subagent)

**Prompt Cache 静态免疫保护**：

- 缓存命中率：频繁切换不同 JIT 虚拟阵容时，首轮对话的前缀缓存命中率从 0% 提升至 100%
- 成本节约：单次首轮对话 Token 成本下降约 90%（基于大模型静态 Prefix Cache 计费规则）
- 实现机制：Tool Schema 彻底静态化，动态名册改为 User Message 尾缀 XML 隐式注入

**大并发委派限流防崩**：

- 错误率控制：在单次委派 5-10 个并发子任务时，大模型 API 429 限流崩溃率降至 0%
- 实现机制：底层基于 `asyncio.Semaphore(3)` 进行并发收束与平滑排队

#### 消息投递队列（infra/delivery）

**批处理并发化**：

- 吞吐量：19.0 msg/s → 187.9 msg/s (**9.88x提升**)
- 批处理延迟：500ms → 50ms (batch_size=10)
- 测试命令：`uv run python benchmarks/bench_batch_performance.py`

**紧急消息优先处理**：

- 延迟降低：305ms → 51ms (**83.4%**)
- 用户体验：紧急消息不受批处理影响

**文件锁开销**：

- 单次开销：~0.14ms
- 影响：1000 msg/s时占用14% CPU

#### LLM降级管理（toolkits/llms/fallback）

**ManagedLLM集成**：

- 透明集成：对LangChain/LangGraph完全透明
- 多级降级：支持>2个模型的降级链（FallbackModel dataclass配置）
- 自动降级：主模型失败时自动切换到备用模型
- 冷却期管理：可配置（默认30s-60s，根据错误类型）
- 自动恢复：错误驱动探测机制自动恢复到主模型

**可配置探测策略（ProbeConfig）**：

- cooldown_ms：冷却期时长（默认30000ms）
- probe_interval_ms：探测间隔（默认5000ms）
- max_probe_attempts：最大探测次数（默认10次）
- global_throttle_ms：全局探测限流（默认60000ms）
- 预设配置：default、aggressive、conservative、balanced
- 验证机制：自动检查参数有效性

**预设降级策略（开箱即用）**：

- 6种最佳实践策略（gpt-4-standard、gpt-4-high-availability、cost-optimized等）
- create_managed_llm_from_preset()：一行代码完成配置
- FallbackStrategy dataclass：封装完整策略（主模型、降级链、场景、探测配置）
- 跨项目复用：标准化配置，降低门槛

**降级与恢复事件通知**：

- FailoverEvent：完整的降级事件数据
  - 基础信息：from_model、to_model、reason、error_message
  - 扩展上下文：session_id、request_id、available_candidates、scenario
- RecoveryEvent：完整的恢复事件数据
  - model：恢复的模型名称
  - downtime_ms：故障持续时长
  - probe_count：恢复前的探测次数
  - was_in_cooldown：是否处于冷却期
- 使用场景：用户实时通知、运营监控、故障追踪、恢复分析

**智能Fallback推荐**：

- recommend_fallback()：根据主模型智能推荐最佳fallback
- 覆盖15个主流模型（GPT-4系列、Claude 3系列、Gemini系列、Mistral系列）
- generate_quantified_reason()：生成量化推荐理由
  - 示例："Lower cost (90% cost reduction, 30% quality trade-off)"
- 推荐依据：模型能力相似性、替代提供商、成本特性
- 降低配置门槛，减少配置错误

**丰富化运营指标（OpenTelemetry）**：

- model_fallback_failover_total：降级次数（维度：from_model、to_model、reason）
- model_fallback_recovery_total：恢复次数（按模型）
- model_fallback_recovery_duration_ms：故障持续时长分布
- model_fallback_probe_success_rate：探测成功率
- 支持运营分析：故障模式、恢复时长、模型可用性、成本归因

**ModelMetrics缓存**：

- 缓存效果：0.835ms / 10000次
- 平均耗时：0.083μs/次
- 性能提升：避免重复对象创建，提升场景选择性能

### Fractal Self-Documentation System (四层文档体系)

| Layer | File                                     | Scope                                                 | Update Trigger             |
| ----- | ---------------------------------------- | ----------------------------------------------------- | -------------------------- |
| L1    | `ARCHITECTURE.md`                        | System-wide architecture, module map, constraints     | Major architecture changes |
| L2    | `xxx_SYSTEM.md` / `xxx_DESIGN.md`        | Cross-module technical designs (e.g. MEMORY, BROWSER) | Technical design changes   |
| L3    | `_ARCH.md`                               | Per-module file index, responsibilities, dependencies | File add/delete/rename     |
| L4    | File header `[INPUT] / [OUTPUT] / [POS]` | Single-file contract — inputs, outputs, positioning   | Any code change            |

- **Semantic network**: INPUT references POS, forming a self-healing dependency graph.
- **Module docs**: `_ARCH.md` replaces README.md at module level. No module-level README files.
- **CI gate**: `scripts/check_fractal_docs.py` — every directory under `src/myrm_agent_harness/` that contains `*.py` must have `_ARCH.md` (pre-commit + `boundary-check.yml`). Pure data/config directories (JSON/YAML/SQL only) are excluded.

---

## 🎯 文档系统目标

让代码、文档和架构形成一个**自指、自愈、自组织的分形系统**：

- **自指**：每个文档都声明"一旦我所描述的内容变化，请更新我"
- **自愈**：POS 变化时，所有引用该 POS 的 INPUT 必须同步更新
- **自组织**：通过 INPUT/OUTPUT/POS 三元组形成语义网络，局部影响整体，整体影响局部

### 核心信念

> **文档是地图，代码是证据。**
>
> 文件名 ≠ 内容，目录结构 ≠ 结论。
>
> 所有结论必须包含：[文件:行号]

### 文档系统与代码质量

分形自文档系统不仅是文档工具，更是**代码质量保障机制**：

1. **强制模块化**：每个文件必须有清晰的 POS，促使开发者思考单一职责
2. **显式依赖**：INPUT 必须引用 POS，使依赖关系显式化，避免隐式耦合
3. **接口契约**：OUTPUT 声明对外能力，形成清晰的接口契约
4. **影响分析**：通过 INPUT/POS 链接快速定位变更影响范围
5. **变更影响分析**：借助 INPUT/POS 链接定位依赖面，配合评审与测试降低回归风险
6. **自动化门禁**：`check_fractal_docs.py` + `boundary_check.py` + `validate_arch_inventory.py`（`_ARCH.md` 文件表 vs 磁盘 `.py`）在 pre-commit 与 CI 阻断文档/层边界回归；inventory CI 当前 scope 为 `agent/` 全量（`toolkits/`、`core/` 等待后续扩展）

**实践约定**：

- 单文件体量过大时优先拆分模块，保持可读性与可测性
- 依赖关系通过文档链接显式化，避免隐式耦合
- 文档与代码变更应在同一变更集中审阅

---

**⭐ 这是一个活文档，随着代码演化而演化。请严格遵守更新规则，保持文档和代码的一致性。**
