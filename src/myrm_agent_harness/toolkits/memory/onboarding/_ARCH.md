# Onboarding Insight Sampling and First Encounter Reporting Toolkit

## 1. 模块定位与职责边界
本模块属于 `myrm-agent-harness` Agent 执行引擎的记忆系统能力子模块（`toolkits.memory.onboarding`）。
针对新用户从其他 AI Agent 工具（如 Cursor、Claude Code、Codex、Hermes、OpenClaw）迁移接入 Myrm 时的“冷启动失忆与全量扫描慢”痛点，提供世界级的轻量滑动窗口关键帧采样、本地双轨零泄漏脱敏（正则 + 香农信息熵）与“初见报告（First Encounter Report）”结构化事实蒸馏引擎。

### 框架边界与定位
- **执行引擎层（Harness）**：纯算法与模型层，提供多源适配器契约、首 2 尾 12 轮滑窗抽取、媒体剔除、字符截断、香农熵识别、事实分类提炼与 SHA-256 规范化指纹计算。
- **业务服务层（Server）**：负责宿主机目录动态探测、管理持久化事务、暴露 RESTful 端点，将用户勾选的初见偏好原子写入长期记忆库。
- **控制平面（Plane）**：不包含任何多租户或调度逻辑，框架层严格单机同构。

## 2. 核心架构组件

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Entry | 子包门面：统一 re-export 采样参数、适配器、注册中枢、采样器与提炼引擎的公共符号。 | ✅ |
| `models.py` | Types | 定义强类型采样参数 `OnboardingSampleOptions`、单轮消息 `SampledTurnMessage`、会话窗口 `OnboardingConversationWindow`、提炼事实 `InsightExtractedFact` 与初见报告 `FirstEncounterReport`（严格零 Any）。 | ✅ |
| `entropy_inspector.py` | Core | `ShannonEntropyInspector`，基于香农信息熵算法识别高熵无特征疑似密钥（Entropy > 4.5 且 Len > 24），杜绝隐蔽凭证泄漏。 | ✅ |
| `redactor.py` | Core | `LocalSecretRedactor`，已知前缀正则匹配 + 香农熵探针双轨脱敏，100% 在本地完成敏感信息擦除。 | ✅ |
| `adapters.py` | Core | `BaseAgentSourceAdapter` 抽象基类及 Cursor、Claude Code、Codex、Hermes、OpenClaw 具体适配器。 | ✅ |
| `registry.py` | Core | `OnboardingSourceRegistry`，插件化适配器注册与宿主机探测中枢。 | ✅ |
| `sampler.py` | Core | `MultiSourceOnboardingSampler`，滑动窗口关键帧提取器（首 2 尾 12 轮、媒体过滤、24k 字符截断）。 | ✅ |
| `distiller.py` | Core | `OnboardingInsightDistiller`，结构化事实提炼引擎，分类沉淀技术偏好、避坑红线与活跃目标。 | ✅ |

## 3. 设计原则
- **代码规范**：严格无 `Any` 类型，单文件行数 < 400 行，模块均配三行分形标头（`[POS]`, `[INPUT]`, `[OUTPUT]`）。
- **零泄漏安全**：所有密钥在离开本地前完成强力脱敏，敏感明文严禁送入大模型 Prompt 上下文。
- **幂等性与去重**：基于 `category:summary` 的规范化 SHA-256 指纹，确保重复扫描安全合并。
