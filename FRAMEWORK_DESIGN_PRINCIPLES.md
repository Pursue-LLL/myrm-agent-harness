# Myrm Agent Harness 框架设计原则

> **许可**: `myrm-agent-harness` 是独立**闭源**仓库，与 `myrm-control-plane`（闭源）相对；`myrm-agent-server`、`myrm-agent-frontend`、`myrm-agent-desktop` 为开源仓库。

Myrm Agent Harness 是一个独立于业务逻辑的底层执行引擎与编排框架。为了保持代码库的高质量、可维护性与扩展性，任何向本仓库贡献代码的开发者，必须严格遵守以下设计原则：

## 1. 严格的框架与业务分离 (Framework-Business Separation)
- **业务无关性**：Harness 框架层绝不包含任何特定的业务规则（如“用户支付权限”、“特定渠道校验”等）。
- **零依赖原则**：框架本身仅依赖标准的开源包（如 `langchain`, `pydantic`, `fastapi`），严禁反向依赖 `myrm-agent-server`（业务端）或 `myrm-control-plane`（控制平面）的模块。
- **协议契约（Protocol/DTO）**：所有跨层级、需要被业务系统实现的模块，一律使用 Python `Protocol` 或 Pydantic BaseModel 作为边界契约。业务系统只需实现这些契约。

## 2. 严格零信任类型安全 (Zero-Trust Typing)
- **100% 类型覆盖**：所有新增函数、类、变量必须具备 Type Hints。**严禁使用 `Any` 类型**，特殊情况下使用必须附带注释解释理由。
- **Mypy Strict**：全项目默认开启 `mypy --strict`。对于边界输入或动态类型，必须在解析点立即被转化为明确的数据模型。

## 3. 架构四“不”原则 (The Four "Don'ts")
1. **不妥协向后兼容**：不为垃圾代码和糟糕的设计妥协。有明确的高价值重构，就大胆废弃和替换历史包袱，拒绝屎山堆积。
2. **不绕过持久化契约**：所有涉及 `Memory`, `Artifacts`, `Checkpoints` 的数据存取，必须走标准的 SQLite/Local FS 的 Vault 与 Storage 抽象，严禁在内存中维护跨长会话（Session）的业务持久状态。
3. **不用长字符串拼接大数据**：智能体交互中若存在诸如 PDF、大代码库解析等体积庞大的工件（Artifacts），**必须**使用 `Shared Artifact Vault` 存入沙箱共享系统，并使用 `vault://<uuid>` 的零拷贝指针在 Agent 间传递，严禁将千行以上文本丢进 LLM Prompt 引发 Token 爆炸。
4. **不使用极简偷懒实现**：核心调度路径上的设计必须具有“工业级前瞻性”（例如防死锁并发机制、Agent Call Stack 跟踪、WAL 数据库配置）。

## 4. “同沙箱零拷贝”协同通信策略 (Zero-Copy Sandbox Synergy)
本项目采用 `Agent-in-Sandbox` 架构。在单用户或 SaaS 多租户调度下，主智能体和所有子智能体都会运行在专属的隔离持久化 Volume 内。
基于此优势，框架层原生支持通过 `ArtifactVault` 和 `vault://` 协议传递大文件结果，彻底避免多智能体交互时的内存和 Token 爆炸。

## 5. 闭源分发策略 (Proprietary Distribution)

`myrm-agent-harness` 作为闭源 Python 包分发，模式参考 Claude Code（npm 壳 + 原生 binary）：

| 层 | 格式 | 内容 |
|----|------|------|
| **公开 API** (`myrm_agent_harness.api`) | `.py` 源码 | factory、Protocol、DTO、hooks — 第三方框架接入面 |
| **核心 IP** (`harness_packaging/core_manifest.yaml`) | Nuitka 编译 `.so` | skill 进化、context pipeline、memory 策略等 |
| **平台包** (`myrm-agent-harness-core-{platform}`) | 按平台 optional dep | 与 Claude Code 的 `@anthropic-ai/claude-code-darwin-arm64` 同模式 |

- **开发模式**：editable install，全部 `.py` 源码，`_distribution.get_distribution_mode()` 返回 `source`
- **发行模式**：`pip install 'myrm-agent-harness[compiled-core]'` 或手动安装平台包 `myrm-agent-harness-core-darwin-arm64`
- **构建**：`uv sync --group build && .venv/bin/python scripts/assemble_production.py`（推荐）或 `build_core.py` + `build_release_wheel.py`（CI: `publish-pypi.yml`、`build-official-runtime.yml`）
- **安装验证**：`verify-harness-distribution` console script（Docker builder/runtime、Tauri、`assemble_production.py --install`）
- **Release 保护**：主 wheel 剥离 manifest `.py`；平台 wheel 注入 `.so`
- **外部消费者**：优先 `from myrm_agent_harness.api import create_skill_agent`，禁止依赖 `_core` 内部模块
