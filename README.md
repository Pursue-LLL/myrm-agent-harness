# Myrm Agent Harness

**生产级 Agent 框架** - 基于 LangChain 构建，提供高级技能系统、MCP 集成和生产就绪的沙箱执行。

> **许可**: Proprietary（见 [LICENSE](LICENSE) 与 `pyproject.toml`）。框架层不与业务逻辑耦合，类似 LangChain 定位，供 `myrm-agent-server` 等业务项目引用。  
> **定位**: GUI-first 通用 AI 工作助手运行时框架（对标 LangChain / LangGraph），面向 WebUI / 桌面端 / 云沙箱嵌入；**不是** CLI 产品或专业编码 IDE。技能系统、MCP、沙箱、记忆与工件等能力按模块可选启用。  
> **版本**: 以 `pyproject.toml` 中 `version` 为准。  
> **验证**: 运行 `pytest tests/` 查看当前测试状态；性能结论以可复现实验（如 `tests/performance`）为准，本文档不承诺固定加速比。

---

## 📑 目录

- [核心特性](#-核心特性)
- [安装](#安装)
- [快速开始](#快速开始)
- [架构概览](#️-架构概览)
- [核心协议](#核心协议仅-3-个)
- [1.0.0 新特性](#-100-新特性)
- [文档导航](#-文档导航)
- [设计原则](#-设计原则)
- [项目状态](#-项目状态)
- [贡献指南](#-贡献指南)

---

## ✨ 核心特性

### 核心能力
- ✅ **完整 LangChain 兼容**：全面支持 `astream()`, `ainvoke()`, `abatch()`
- ✅ **高级技能系统**：渐进式披露、MCP 集成、基于文件的技能
- ✅ **LLM-Wiki Knowledge Base**：Karpathy 架构，LLM 作为编译器维护结构化 Markdown Wiki（见 Wiki Toolkit）
- ✅ **生产就绪代码执行**：Agent-in-Sandbox 模式（LocalExecutor），可选 `SmartCachedStorage` 等缓存层
- ✅ **统一路径解析**：`WorkspacePathResolver` 实现本地 ↔ 容器路径一致性转换
- ✅ **Claude Code 兼容**：完整支持 Hooks、allowed-tools 和技能生命周期
- ✅ **独立工具设计**：专用工具（Read/Write/Edit/Glob/Grep）；若系统安装 `ripgrep`，文件搜索可走外部实现

### 架构亮点
- ✅ **框架-业务分离**：纯框架层，零业务逻辑（[自动化检测与修复](scripts/_ARCH.md)）
- ✅ **智能缓存系统**：文件缓存与 LRU 等策略（行为依赖负载与配置）
- ✅ **多沙箱支持**：Local（开发）、Docker（生产）、E2B（云端）统一 API
- ✅ **类型安全**：包内代码以严格类型约束为目标（见 `pyproject` / `mypy` 配置）
- ✅ **测试**：`tests/` 下单元、集成与性能等用例；以本地 `pytest` 结果为准
- ✅ **分形自文档**：自组织、自愈的四层文档系统

---

## ⚠️ 重要：框架边界

> **单实例设计**：每个 Agent 实例为单用户服务。多用户场景请创建多个实例（多进程/容器）。

### 框架不做什么

| 特性 | 说明 |
|-----|------|
| ❌ **用户身份感知** | 框架不知道"谁"在使用，无 `user_id` 概念 |
| ❌ **多租户管理** | 隔离由业务层负责（多进程/容器/prefix注入） |
| ❌ **跨用户并发** | 单实例设计，并发靠横向扩展（创建多个实例） |
| ❌ **Agent 配置读环境变量** | `LLMConfig`、`AgentConfig` 等运行时配置通过 API 显式传入，不由环境变量注入 |
| ✅ **基础设施 opt-in env** | 存储路径（`MYRM_DATA_DIR`）、诊断 i18n 目录（`MYRM_LOCALES_DIR`）、统一网关（`MYRM_GATEWAY_*`）、诊断探针等基础设施允许可选环境变量 |

### 错误 vs 正确用法

```python
# ❌ 错误：一个实例处理多个用户
agent = create_skill_agent(...)
await agent.run(user_a_message)  # 数据泄露风险！
await agent.run(user_b_message)

# ✅ 正确：每个用户独立实例
agent_a = create_skill_agent(storage_prefix="user_a/")
agent_b = create_skill_agent(storage_prefix="user_b/")
await agent_a.run(user_a_message)
await agent_b.run(user_b_message)
```

**详见**：[FRAMEWORK_DESIGN_PRINCIPLES.md](./FRAMEWORK_DESIGN_PRINCIPLES.md)

---

## 安装

```bash
pip install myrm-agent-harness

# 安装可选能力（浏览器、检索、网页抓取、文件解析等）
pip install "myrm-agent-harness[browser,retrieval,web,file-parsers]"

# 🚀 可选：安装 ripgrep，由工具层在可用时优先走 ripgrep 实现
# macOS
brew install ripgrep

# Ubuntu/Debian
apt-get install ripgrep

# Windows
choco install ripgrep

# 系统会自动使用 ripgrep（如果可用），否则回退到内置实现
```

## 快速开始

### 简单示例（开箱即用）

```python
from myrm_agent_harness.api import create_skill_agent, LLMConfig

# Just provide config - no need to know about ChatOpenAI or BaseChatModel!
agent = await create_skill_agent(
    llm_config=LLMConfig(
        model="gpt-4",
        api_key="sk-...",
    )
)

# Run agent
async for event in agent.run("Hello, how are you?"):
    print(event)
```

### 从环境变量创建

```python
# 设置环境变量：
# export MODEL_NAME="gpt-4"
# export API_KEY="sk-..."

agent = await create_skill_agent(
    llm_config=LLMConfig.from_env()
)
```

### 使用技能后端

```python
from myrm_agent_harness.backends.skills import SkillBackend

# 创建技能后端（业务层）
skill_backend = SkillBackend.local("./skills")

agent = await create_skill_agent(
    llm_config=LLMConfig(model="gpt-4", api_key="sk-..."),
    skill_backend=skill_backend,  # 动态技能加载
)
```

### 高级：自定义上下文管理

```python
from myrm_agent_harness.agent.middlewares import create_context_pipeline_middleware
from langchain_openai import ChatOpenAI

# 使用更便宜的 LLM 进行上下文管理（过滤/压缩/摘要）
cheap_llm = ChatOpenAI(model="gpt-3.5-turbo", api_key="sk-...")
context_middleware = create_context_pipeline_middleware(
    llm=cheap_llm,
    compress_batch_rounds=10,  # 自定义配置
    keep_recent_calls=5,
)

# 创建带自定义中间件的 Agent
agent = await create_skill_agent(
    llm_config=LLMConfig(model="gpt-4", api_key="sk-..."),
    middlewares=[context_middleware],  # 完全控制
)
```

### 使用业务工具

```python
from myrm_agent_harness.toolkits.web_search.web_search_agent_tools import create_web_search_tool
from myrm_agent_harness.agent.meta_tools.progress.todo_write_tool import create_todo_write_tool

# 业务层创建工具
tools = [
    create_web_search_tool(your_search_config),
    create_todo_write_tool(workspace_root="/path/to/workspace"),
]

agent = await create_skill_agent(
    llm_config=LLMConfig(model="gpt-4", api_key="sk-..."),
    tools=tools,  # 传入业务工具
)
```

### 使用 Wiki Knowledge Base (LLM-Wiki)

```python
from langchain_openai import ChatOpenAI
from myrm_agent_harness.toolkits.wiki import (
    WikiStructure, WikiCompiler, WikiQueryEngine, WikiLinter,
    create_wiki_tools, WikiConfig,
)

# Setup
llm = ChatOpenAI(model="gpt-4")
structure = WikiStructure(base_dir="./my-wiki")
config = WikiConfig(
    parallel_compilation=True,  # 10x faster compilation
    auto_archive_enabled=True,
)

# Initialize components
compiler = WikiCompiler(llm, structure, config)
query_engine = WikiQueryEngine(llm, structure, config)
linter = WikiLinter(llm, structure, config)

# Create tools for Agent (4 tools: ingest, compile, query, maintain)
wiki_tools = create_wiki_tools(compiler, query_engine, linter, structure)

# Use with Agent
agent = await create_skill_agent(
    llm_config=LLMConfig(model="gpt-4", api_key="sk-..."),
    tools=wiki_tools,  # Agent can now use wiki knowledge base!
)

# Direct API usage (without Agent)
from myrm_agent_harness.toolkits.wiki import CompileResult

# Ingest documents
structure.get_raw_file_path("doc.md").write_text("# My Document\n\n...")

# Compile into wiki
result: CompileResult = await compiler.compile_all()
print(f"Generated {result.articles_generated} articles from {result.concepts_count} concepts")

# Query wiki
answer = await query_engine.query("What is X?")
print(answer.answer)

# Maintain wiki health
lint_result = await linter.lint_and_maintain()
print(f"Fixed {lint_result.issues_fixed} issues")
```

📘 **详细文档**: Wiki Toolkit Architecture

### 高级：配置并行工具调用

```python
# 显式启用并行工具调用
agent = await create_skill_agent(
    llm_config=LLMConfig(model="gpt-4", api_key="sk-..."),
    parallel_tool_calls=True,
)

# 显式禁用并行工具调用
agent = await create_skill_agent(
    llm_config=LLMConfig(model="gpt-4", api_key="sk-..."),
    parallel_tool_calls=False,
)
```

- `True`：多个独立工具调用可并行执行（降低延迟）
- `False`：工具串行执行
- `None`（默认）：使用 LLM 提供商的默认值
- 也可通过环境变量 `PARALLEL_TOOL_CALLS=true/false` 配置

### 直接使用 SkillAgent（完全控制）

```python
from myrm_agent_harness.api import SkillAgent, AgentRuntimeConfig
from langchain_openai import ChatOpenAI

# 创建 LLM
llm = ChatOpenAI(model="gpt-4", api_key="sk-...")

# 创建完全控制的 Agent
agent = SkillAgent(
    llm=llm,
    skill_backend=skill_backend,  # 可选
    tools=tools,                   # 可选
    middlewares=middlewares,       # 可选
    system_prompt="You are a helpful assistant.",
    config=AgentRuntimeConfig(
        recursion_limit=50,
        timeout_seconds=300,
    ),
)
```


## 🏗️ 架构概览

```
myrm-agent-harness/          # 本仓库根（示意）
├── src/
│   └── myrm_agent_harness/
│       ├── api/                     # 对外公开 API（推荐 import 路径）
│       ├── core/                    # 框架无关基础层（security, events, hooks, config）
│       ├── agent/                   # Agent 核心（BaseAgent, SkillAgent, 技能, 中间件, 元工具）
│       ├── runtime/                 # 单实例运行时（消息构建、流式执行、事件、checkpoint）
│       ├── infra/                   # 基础设施（文件锁、消息投递、链路追踪）
│       ├── observability/           # 全局监控与诊断（Prometheus, Diagnostic Protocol）
│       ├── backends/                # 后端抽象（skills, storage, profiles, secrets）
│       ├── toolkits/                # 通用工具包（不与 agent/ 耦合，可独立使用）
│       │   ├── code_execution/      # 沙箱代码执行（Agent-in-Sandbox）
│       │   ├── storage/             # 存储与缓存（含 SmartCachedStorage）
│       │   ├── memory/              # 可插拔记忆系统
│       │   ├── retriever/           # 检索（向量/BM25/混合搜索）
│       │   ├── mcp/                 # MCP 协议集成
│       │   ├── browser/             # 浏览器自动化
│       │   ├── web_search/          # 网络搜索
│       │   ├── web_fetch/           # 网页抓取
│       │   ├── context_bundle/      # ContextBundle 统一上下文卷
│       │   └── llms/                # LLM 管理（工厂、适配器）
│       ├── eval/                    # Agent 行为评估框架
│       └── utils/                   # 通用工具函数
│
├── tests/                           # 测试套件（单元 / 集成 / 架构门禁 / 性能）
├── harness_packaging/               # 闭源分发构建（Nuitka core + release wheel）
└── scripts/                         # 边界检测、构建与发布脚本
```

详细架构说明请参考 [ARCHITECTURE.md](ARCHITECTURE.md)。

### Toolkits 模块分区

`toolkits/` 按职责分为三区，安装时通过 `pyproject.toml` 的 optional extras 按需启用（`pip install "myrm-agent-harness[browser,retrieval,...]"`）。

| 分区 | 模块 | 说明 | Optional extra |
|------|------|------|----------------|
| **Core** | `code_execution`, `storage`, `mcp`, `context_bundle`, `llms`, `memory`, `network`, `retriever`, `web_search`, `web_fetch`, `vector`, `file_parsers` | Agent 运行时基础能力；PDF（pdfplumber）、HTML（bs4/lxml）等已在主依赖 | `[file-parsers]` Office；`[retrieval]` 代码分块+BM25；`[acp]` 外部 Agent；`[observability]` Prometheus+OTEL；`qdrant`, `web` 等 |
| **Integrations** | `browser`, `computer_use`, `acp`, `openapi_bridge`, `vision`, `tts` | 外部系统/协议集成，按需安装 | `browser`, `computer-use`, `image-processing`, `acp`, `observability` |
| **Product-adjacent** | `kanban`, `cron`, `automation`, `wiki`, `tasks`, `workspace`, `security` | 通用 Protocol 实现，零 `agent/` 依赖；Myrm 产品默认启用，第三方可按需选用 | 多数无 extra |

框架层模块（非 toolkits）：`api/`（公开入口）、`agent/`、`runtime/`、`core/`、`infra/`、`backends/`、`eval/`、`utils/`。

### 架构原则

1. **框架-业务分离**
   - ✅ 框架层：纯技术概念（`session_id`, `workspace_root`）
   - ✅ 业务层：用户特定逻辑（`user_id`, `chat_id`）
   - ✅ 层间零耦合

2. **协议驱动设计**
   - ✅ 仅 3 个核心协议：`SandboxExecutor`, `StorageProvider`, `SkillBackend`
   - ✅ 易于扩展和测试
   - ✅ 依赖注入友好

3. **性能与 I/O**
   - ✅ 可选缓存层与全异步 I/O
   - ✅ 路径解析集中封装，便于在各执行器复用
   - ℹ️ 具体吞吐与延迟以目标环境与基准测试为准

4. **类型安全与测试**
   - ✅ 静态类型与测试配置见 `pyproject.toml`
   - ✅ 包内避免无约束的 `Any`（按模块逐步收紧）
   - ✅ 回归依赖 `pytest` 与 CI/本地检查命令

5. **分形自文档系统**
   - ✅ 四层文档结构：ARCHITECTURE.md → xxx_SYSTEM.md / xxx_DESIGN.md → _ARCH.md → 文件头 I/O/P 注释
   - ✅ 语义链接网络：INPUT 引用 POS，形成自组织系统
   - ✅ 自愈机制：POS 变化时自动触发连锁更新
   - ✅ 树状+网状结构：纵向层次清晰，横向依赖明确
   - 详见 [ARCHITECTURE.md](ARCHITECTURE.md)

## 核心协议（仅 3 个！）

本库使用最小化的协议架构，以最少的样板代码实现最大的灵活性：

### 1. CodeExecutor（必需）

在执行环境中执行代码：

```python
from myrm_agent_harness.toolkits.code_execution import CodeExecutor, ExecutionResult

class MyCodeExecutor(CodeExecutor):
    async def execute(
        self,
        command: str,
        *,
        workspace_path: str,
        skill_paths: list[str] | None = None,
        timeout_seconds: int = 300,
    ) -> ExecutionResult:
        ...
```

### 2. SkillBackend（必需）

加载技能和技能内容：

```python
from myrm_agent_harness.backends.skills import SkillBackend
from myrm_agent_harness.backends.skills.types import SkillMetadata

class MySkillBackend(SkillBackend):
    async def load_skills(self, skill_ids: list[str]) -> list[SkillMetadata]:
        ...
    async def get_skill_content(self, skill_name: str) -> str:
        ...
    async def get_skill_resources(self, skill_name: str, path: str) -> bytes:
        ...
```

### 3. StorageProvider（必需）

统一文件系统和存储操作：

```python
from myrm_agent_harness.toolkits.storage import StorageProvider

class MyStorageProvider(StorageProvider):
    async def read(self, path: str) -> bytes:
        ...
    async def write(self, path: str, content: bytes) -> None:
        ...
    async def list(self, path: str = "") -> list[str]:
        ...
    async def exists(self, path: str) -> bool:
        ...
    async def delete(self, path: str) -> None:
        ...
    # 便捷方法
    async def read_text(self, path: str, encoding: str = "utf-8") -> str:
        ...
    async def write_text(self, path: str, content: str, encoding: str = "utf-8") -> None:
        ...
    async def resolve_path(self, workspace: str, relative_path: str) -> str:
        ...
```

### 可选特性

#### Artifact 收集

启用 artifact 收集以追踪生成的文件：

```python
# 创建 Agent 时启用 artifact 收集
agent = await create_skill_agent(
    llm_config=LLMConfig(model="gpt-4"),
    collect_artifacts=True,  # 默认：False
)

# 在流处理器中处理 artifacts_ready 事件
async for event in agent.run(query, ...):
    if event["type"] == "artifacts_ready":
        # 框架层提供文件路径和读取函数
        # 业务层处理持久化（user_id, chat_id, URLs）
        artifacts_data = event["data"]  # [{filename, path, type}, ...]
        read_content = event["read_content"]  # async function(path) -> bytes
        ...
```

**架构设计（2026-01-27 纯粹设计）**：
- 框架层：仅追踪文件路径（无 user_id/chat_id）
- 业务层：处理持久化、URL 生成、用户关联

#### 内置工具配置

内置工具（如网络搜索和抓取）现在是**配置驱动**的，而非基于协议：

```python
agent = await create_skill_agent(
    llm_config=LLMConfig(model="gpt-4"),
    # 通过配置启用内置工具
    enable_search=True,
    search_config={"api_key": "..."},
    enable_fetch=True,
    web_fetch_config={...},
)
```

## 🚀 1.0.0 新特性

### 智能缓存系统 ⚡
```python
from myrm_agent_harness.toolkits.storage import SmartCachedStorage, LocalBackend

# SmartCachedStorage：在 backend 之上叠加缓存与异步写回（效果依赖负载与配置）
backend = LocalBackend(root_path="/data")
cache = SmartCachedStorage(
    backend=backend,
    cache_dir="/tmp/cache",
    max_cache_size_mb=500,  # LRU 淘汰
    enable_async_upload=True,  # 后台异步写入
)

# 使用缓存
data = await cache.read("skills/my_skill.py", session_id="abc123")
```

**说明**：是否命中缓存、延迟与吞吐取决于访问模式与配置；请在目标环境中用基准或 profiling 验证。

---

### 统一路径解析 🗺️
```python
from myrm_agent_harness.toolkits.code_execution.utils import WorkspacePathResolver

# 本地路径 → 容器路径
container_path = WorkspacePathResolver.to_container_path(
    "/Users/me/project/script.py",
    "/Users/me/project"
)
# → "/workspace/script.py"

# 容器路径 → 本地路径
local_path = WorkspacePathResolver.to_local_path(
    "/workspace/script.py",
    "/Users/me/project"
)
# → Path("/Users/me/project/script.py")
```

**能力**：
- 统一本地路径与容器工作区路径的解析规则
- 覆盖 `.`、`..`、符号链接与 Unicode 等常见边界情况
- 配套单元测试见 `tests/` 中沙箱与路径相关用例

---

### 多执行模式支持 🐳☁️
```python
from myrm_agent_harness.toolkits.code_execution import create_executor
from myrm_agent_harness.toolkits.code_execution.config import ExecutionMode, ExecutionConfig

# Local（开发环境）
executor = create_executor(ExecutionConfig(mode=ExecutionMode.LOCAL))

# 所有模式统一 API
result = await executor.execute(code, context)
```

**模式对比**：
| 模式 | 隔离性 | 性能 | 可扩展性 | 成本 |
|------|--------|------|----------|------|
| **Local** | ❌ 无 | ⚡ 最快 | ❌ 受限 | ✅ 免费 |
| **Docker** | ✅ 强 | 🔥 快 | 🔥 好 | ✅ 免费 |
| **E2B** | ✅ 强 | ⚡ 即时 | ✅ 无限 | 💵 付费 |

---

## 📚 文档导航

> 💡 **文档系统说明**：本项目采用**分形自文档系统**，通过四层文档结构（ARCHITECTURE.md → xxx_SYSTEM.md → _ARCH.md → 文件头 I/O/P）和语义链接网络（INPUT 引用 POS）形成自组织文档体系。详见 [ARCHITECTURE.md](ARCHITECTURE.md)。

### 快速开始
- [快速开始](#快速开始) - 2 分钟上手

### 架构与设计
- [架构总览](ARCHITECTURE.md) - **必读**：分形自文档系统、系统设计、模块导航、AI 工作流程

### 技术方案文档
- [记忆系统](src/myrm_agent_harness/toolkits/memory/MEMORY_SYSTEM.md) - 可插拔记忆系统设计
- [浏览器系统](src/myrm_agent_harness/toolkits/browser/BROWSER_SYSTEM.md) - 浏览器自动化系统设计

### 核心子系统

### 测试

---

## 🎯 设计原则

1. **框架-业务分离**：框架层只知道 `session_id`，不知道 `user_id`、`chat_id`
2. **协议驱动设计**：仅 3 个核心协议，易于扩展
3. **性能优先**：智能缓存、异步 I/O、高效算法
4. **类型安全**：以严格类型与静态检查约束包内代码
5. **测试**：用 `pytest` 持续验证；新增行为应带对应用例
6. **可维护性**：模块边界清晰，文档与代码同步更新
7. **分形自文档**：自组织、自愈的文档系统，代码与文档同步演化

---

## 📊 项目状态

- **功能范围**：以本仓库 `src/myrm_agent_harness/` 与 `tests/` 为准；各子系统在对应 `*_SYSTEM.md` / `*_DESIGN.md` 中说明职责与依赖。
- **验证**：在包根目录执行 `pytest tests/`；覆盖率与门禁见 `pyproject.toml` 中 `[tool.coverage.*]`。
- **性能**：若需对外宣称加速比或延迟上限，请附可复现实验命令与环境（例如性能测试标记与数据集），本文档不列举固定数字。

---

## 🤝 贡献指南

本仓库为 **Proprietary** 项目，贡献面向内部授权开发者。请参考 [ARCHITECTURE.md](ARCHITECTURE.md) 了解分形自文档系统和架构约束。

### 贡献者快速开始

```bash
# 克隆和设置
git clone <repo-url>
cd myrm-agent-harness
python3.13 -m venv .venv
source .venv/bin/activate
uv sync --all-extras

# ⚠️ 重要：安装 pre-commit（自动化边界检测）
pip install pre-commit
pre-commit install

# 运行测试（默认串行 + 安全 marker 过滤，避免本机内存打满）
pytest -v

# 全量（含 integration / e2e / performance）
pytest -m "" -v

# 浏览器 / 性能用例单独跑
pytest -m "integration or e2e" -v --timeout=600
pytest -m performance -v

# 运行架构检测
pytest tests/architecture/ -m architecture -n0 -v

# 检查代码质量
ruff check .
mypy src/myrm_agent_harness
```

### 架构边界保护

自动化边界检测系统，确保框架层不依赖业务层：
- 🛡️ **白名单模式**：默认拒绝策略，新模块自动拦截
- 🔍 **全面检测**：静态导入 + 动态导入 + exec/eval + f-string
- ⚡ **增量扫描**：pre-commit 只检查变更文件（<0.1秒）
- 🔧 **自动修复**：`python scripts/boundary_check.py --fix` 一键注释违规代码
- 🚫 **CI 门禁**：PR 必须通过边界检测（34个测试）
- 📊 **智能报告**：优先级分级（HIGH/MEDIUM/LOW）+ 统计信息
- 📈 **性能保护**：CI 自动检测性能回归（30%容忍度）

详见 [scripts/_ARCH.md](scripts/_ARCH.md) 了解完整使用方法。

### 文档更新规范

当修改代码时，必须遵循分形自文档系统的更新流程：
1. 修改代码文件
2. 更新文件头的 I/O/P 注释（如果依赖或输出变化）
3. 更新相关的 `*_SYSTEM.md` / `*_DESIGN.md`（如果设计/职责变化）
5. 更新技术方案文档 `xxx_SYSTEM.md`（如果技术方案变化）
6. 更新 `ARCHITECTURE.md`（如果顶层架构变化）

详见 [ARCHITECTURE.md - AI 工作流程](ARCHITECTURE.md#-ai-工作流程)

---

## 📄 许可证

当前为 **Proprietary** 许可（详见 [LICENSE](LICENSE) 与 `pyproject.toml`）。未经授权不得复制、分发或商用。

---

## 🙏 致谢

- 基于 [LangChain](https://github.com/langchain-ai/langchain) 构建
- 灵感来自 [Claude Code](https://www.anthropic.com/claude-code)
- 性能优化源于生产环境实践

---

## 🎯 目标

让代码、文档和架构形成一个**自指、自愈、自组织的分形系统**。

---

**⭐ 如果这个项目对你有帮助，请在 GitHub 上给它一个 Star！**

