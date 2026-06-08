# Agent 记忆系统设计文档

> 框架：`myrm_agent_harness.toolkits.memory`

## 一、设计目标

构建一个 **Protocol-first** 的可插拔 AI Agent 记忆系统：

- **运行时读写**：Agent 通过工具动态存储和检索记忆
- **可解释引用**：`memory_recall_tool` 在返回结果时同步发出 cited memory IDs、轻量 citation refs 与业务无关 retrieval trace；无结果检索也会发出 trace，业务层可展示“为什么没召回”；`conversation_search_tool` 通过标准 `sources` 事件发出历史会话来源，业务层可持久化并在聊天 UI 展示记忆与会话证据来源
- **个性化体验**：基于用户画像和历史交互提供定制化服务
- **跨会话上下文**：记忆在不同对话间持久化
- **跨渠道持久化**：记忆携带确定性 `scope`（`agent_id/channel_id/conversation_id/task_id`），默认支持跨渠道召回并保留来源
- **Agent 级策略**：支持正式的 `AgentMemoryPolicy`，把读取 namespace 边界和写入 scope 边界从运行时散参提升为类型化配置
- **智能检索**：RRF 混合检索策略，精准召回相关记忆
- **可插拔设计**：所有存储后端通过 Protocol 注入，框架零业务依赖
- **审批机制**：通过 `RelationalStoreProtocol` 内置 pending 方法实现开箱即用的用户确认流程
- **可观测契约**：提供业务无关的 operation / influence / retrieval-trace / memory-space DTO，应用层可投影为控制台、日志或审计视图
- **精确变更契约**：显式 type/id 删除返回 `MemoryMutationResult`，区分 deleted、missing、forbidden、failed 引用；profile 读取提供 `ProfileAttributeSnapshot` 修订号；导入 dry-run 可返回 `MemoryImportPlan`。应用层可据此维护可审计回滚账本、避免 ABA 覆盖和用聚合数量推断单条记忆状态。
- **归档可靠性契约**：提供业务无关的 `MemoryArchiveManifest` / `MemoryArchivePayload` / `MemoryArchiveDryRunResult`，应用层可用同一契约实现单机 archive 导出、GUI 审查和内容盲健康投影，不把 GUI、SaaS 或租户语义放入框架层。

---

## 二、系统架构

### 2.1 分层设计

```
┌──────────────────────────────────────────────────────────────────┐
│                     Framework Layer                               │
│                 myrm_agent_harness.toolkits.memory                 │
│                                                                   │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌───────────┐  │
│  │  Profile    │  │  Semantic  │  │  Episodic   │  │Procedural │  │
│  │  Memory     │  │  Memory    │  │  Memory     │  │  Memory   │  │
│  │(Relational) │  │ (Vector)   │  │(Vector+Graph│  │(Relational│  │
│  └──────┬──────┘  └──────┬─────┘  └──────┬──────┘  └─────┬─────┘ │
│         └────────────────┴───────────────┴────────────────┘       │
│                              │                                     │
│              ┌───────────────▼────────────────┐                   │
│              │       MemoryManager            │                   │
│              │  (Unified API + Session Mgmt   │                   │
│              │   + Approval Orchestration)     │                   │
│              └───────────────┬────────────────┘                   │
│                              │                                     │
│     ┌────────────────────────┼────────────────────────┐           │
│     │                        │                        │           │
│  ┌──▼──────┐  ┌──────────────▼─────────────┐  ┌──────▼────────┐  │
│  │ Memory  │  │    MemoryRetriever         │  │  Strategies   │  │
│  │ Session │  │   (RRF Hybrid Search)      │  │ Conflict /    │  │
│  │(Buffer) │  │                            │  │ Forgetting /  │  │
│  └─────────┘  └────────────────────────────┘  │ Extractor     │  │
│                                                └───────────────┘  │
│  ┌─────────────┐  ┌──────────────────────┐                       │
│  │ Agent Tools │  │ Memory Middleware     │                       │
│  │ recall/save │  │ (Context Injection)   │                       │
│  │ manage/search│ │                       │                       │
│  └─────────────┘  └──────────────────────┘                       │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │                    Protocols                              │    │
│  │  VectorStore │ Relational │ Graph │ Embedding │ Cache     │    │
│  │  PendingStore (审批队列)                                   │    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
                              │
                    Protocol 注入（DI）
                              │
┌──────────────────────────────────────────────────────────────────┐
│                       App Layer                                   │
│                    app.core.memory                                │
│                                                                   │
│  adapters/                                                        │
│  ├── relational_store.py     → RelationalStoreProtocol           │
│  ├── vector_adapter.py       → VectorStoreProtocol               │
│  └── setup.py                → create_memory_manager() 工厂      │
│                                                                   │
│  services/                   (empty — embedding now from framework)│
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 目录结构

```
myrm_agent_harness/
├── toolkits/memory/                    # 核心记忆能力
│   ├── config.py                       # MemoryConfig + RetrievalConfig
│   ├── types.py                        # 枚举 + Pydantic 数据模型（含 PendingRecord、MemoryMutationResult、ProfileAttributeSnapshot）
│   ├── manager.py                      # MemoryManager 公开 import 路径
│   ├── _manager/                       # MemoryManager 组合实现（core / governance / deletion / maintenance 等 mixin）
│   ├── session.py                      # MemorySession（对话级缓冲）
│   ├── retriever.py                    # MemoryRetriever（RRF + 几何平均评分 + MMR 多样性重排 + source decay 会话源多样化）
│   ├── signals.py                      # SignalCalculator（上下文信号计算）
│   ├── memory_agent_tools.py           # Agent 工具（memory_recall/save/manage）
│   ├── memory_citations.py             # 记忆 citation refs 与 retrieval trace 的轻量 SSE 元数据桥接
│   ├── observability.py                # 业务无关记忆观测 DTO/Protocol（operation / influence / retrieval trace / space / sink）
│   ├── reliability.py                  # 业务无关记忆可靠性 DTO（probe / repair plan / import plan / recall benchmark summary）
│   ├── conversation_search/            # Protocol-backed 历史会话搜索工具（无业务 DB 依赖）
│   ├── _internal/                      # 内部实现细节
│   │   ├── storage.py                  # 存储辅助函数
│   │   ├── approval.py                 # 审批序列化辅助
│   │   ├── scope.py                    # namespace 派生、作用域绑定、写入目标裁剪、namespace 校验、渠道亲和力
│   │   ├── write_service.py            # 写入编排（扫描、审批、分桶、批量去重、convenience memory 构造）
│   │   ├── search_service.py           # 搜索编排（sanitize、typed recall 路由、RRF 前后编排、graph enrich、raw 裁剪、retrieval trace）
│   │   ├── governance_service.py       # 治理编排（审批流、profile 写入、安全扫描）
│   │   ├── maintenance_service.py      # 维护编排（health、snapshot、maintenance cycle）
│   │   ├── embedding_cache.py          # EmbeddingCache（L1+L2）
│   │   ├── hash_utils.py              # 内容 hash 计算（可配置归一化：NONE/BASIC/FULL）
│   │   └── maintenance.py             # 后台维护（去重、遗忘、访问计数、图增强）
│   ├── protocols/                      # 存储后端接口
│   │   ├── vector.py                   # VectorStoreProtocol
│   │   ├── relational.py              # RelationalStoreProtocol
│   │   ├── graph.py                    # GraphStoreProtocol
│   │   ├── embedding.py               # EmbeddingProtocol
│   │   ├── hooks.py                   # MemoryLifecycleHookProtocol
│   │   └── cache.py                    # EmbeddingCacheProtocol
│   ├── graph/                          # 图存储（开箱即用）
│   │   ├── base.py                    # GraphStore ABC + 数据模型
│   │   ├── sqlite_store.py            # SQLiteGraphStore（aiosqlite + CTE）
│   │   └── exceptions.py              # 图存储异常
│   ├── relational/                    # 关系存储（开箱即用）
│   │   ├── base.py                    # RelationalStore ABC
│   │   ├── sqlite_store.py            # SQLiteRelationalStore（aiosqlite）
│   │   ├── _converters.py             # 行转模型辅助函数
│   │   └── exceptions.py              # 关系存储异常
│   └── strategies/                     # 可插拔策略
│       ├── deduplicator.py             # 三层智能去重（Hash → Vector → LLM）
│       ├── llm_prompt.py               # Layer 3 LLM 去重判断 prompt 模板
│       ├── forgetting.py              # 遗忘策略
│       └── extractor.py               # LLM 自动提取
│
├── agent/
│   └── middlewares/
│       └── memory_context_middleware.py # 记忆上下文注入
```

---

## 三、记忆类型

| 类型                 | Protocol                   | 存储                | 用途                                      | 示例                                                    |
| -------------------- | -------------------------- | ------------------- | ----------------------------------------- | ------------------------------------------------------- |
| **Profile**          | Relational                 | SQLite              | 用户结构化属性                            | 姓名、生日、偏好语言                                    |
| **Semantic**         | Vector                     | Qdrant              | 事实性知识                                | "用户喜欢简洁的回答"                                    |
| **Episodic**         | Vector + Graph             | Qdrant + GraphStore | 事件记录 + 因果关系                       | "用户讨论了旅行计划" → "选择曼谷因为便宜"               |
| **Conversation**     | Vector (Named Vectors)     | Qdrant              | **逐字对话历史**（Verbatim Storage）      | User Q + AI A verbatim                                  |
| **Procedural**       | Relational                 | SQLite              | 行为规则                                  | "用户请求文件时用 Excel 格式"                           |
| **Claim (L3)**       | Graph                      | GraphStore          | 编译后的知识主张，一等检索对象            | "Deploy policy: Use canary rollout before full release" |
| **Task Digest (L2)** | Vector (Episodic metadata) | Qdrant              | 会话级任务摘要，作为后续编译/图谱蒸发输入 | `event_type='task_digest'`                              |
| **Integration**      | Vector + Graph             | Qdrant + GraphStore | 外部服务数据本地缓存，跨源语义检索。并支持**自动化知识播种 (Auto-Seeding)**，提取偏好并写入全局 Profile。        | Gmail 邮件、GitHub PR、Slack 消息、Notion 页面          |

> **时间约定**：所有 `datetime` 字段（`created_at`、`updated_at`、`last_accessed_at` 等）统一使用 **UTC timezone-aware** datetime（`datetime.now(UTC)`）。模型默认值、业务逻辑和测试均遵循此约定。
>
> **作用域约定**：所有 `BaseMemory` 均携带 `MemoryScope`。向量层会持久化 `primary_namespace/namespaces/channel_id/...` 元数据，检索时按当前 manager 的 `namespaces` 过滤，同时保留跨渠道可召回能力。`AgentMemoryPolicy` 允许把“读哪些 namespace”和“写入哪个 scope”正式配置化，例如只读 `global` 共享知识，同时把新记忆仅写入 `task` namespace。
>
> **Façade 编排边界**：`MemoryManager` 负责统一 façade，不再内联 `namespace` 派生、scope 绑定、写入目标裁剪和渠道亲和力重加权，这些纯逻辑统一收敛到 `_internal/scope.py`；扫描、审批路由、分桶、批量去重以及 convenience memory 构造统一收敛到 `_internal/write_service.py`；sanitize、typed recall 路由、RRF 前后编排、graph enrich 与 raw 裁剪统一收敛到 `_internal/search_service.py`；审批流、profile 写入和安全扫描统一收敛到 `_internal/governance_service.py`；health、snapshot 和 maintenance cycle 统一收敛到 `_internal/maintenance_service.py`。
>
> **Digest 生命周期**：`task_digest` 会以 `EpisodicMemory(event_type='task_digest')` 存储，并通过 `MemoryLifecycle` 建模为 `tier='l2'`、`evaporation_state='pending'`、`claim_graph_state='pending'`。向量层会将它扁平化持久化为 metadata 字段，但业务逻辑统一基于 typed lifecycle 推进。
>
> **Claim Graph Binding 继承**：已蒸发的 L2 digest 会被 maintenance 编译成图中的 `Claim` 节点和 `Evidence` 节点，二者会继承 digest 的 `primary_namespace/namespaces/agent_id/channel_id/conversation_id/task_id`，并以 `primary_namespace + claim_key` 作为编译层 Claim 身份，避免不同 task/channel/agent 下的同名结论被错误合并。
>
> **Claim Graph 语义关系闭环**：编译后的 `Claim` / `Evidence` 节点会按语义关系连接，而不再只看 success/fail polarity。当前支持 `SUPPORTED_BY`、`CONTRADICTED_BY`、`SUPERSEDED_BY`、`CONSTRAINED_BY`；Claim 节点保留 `confidence`、`freshness_days`、`contradiction_status` 与 `latest_relationship_type`，Digest lifecycle 会推进到 `claim_graph_state='compiled'` 并回写 `claim_graph_node_id/claim_graph_updated_at/claim_graph_conflict`，保证后续增量编译可重复执行且不重复消费。
>
> **显式变更语义**：`task_digest` 现在允许额外提供 `**Change Kind**: support|contradict|supersede|constrain|none`。当该字段存在时，Claim 编译会优先使用它判定图关系；只有缺失时才回退到关键词和 token overlap 规则。这样可以减少“迁移/替代/约束变化”被误判成普通 polarity 冲突。
>
> **Claim 一等检索对象**：`Claim` 节点在 recall 阶段会被恢复成正式的 `ClaimMemory(memory_type='claim')`，不再伪装成 `SemanticMemory`。Recall 会先按当前 manager 的 `namespaces` 过滤 Claim，再叠加 freshness / contradiction / channel affinity 排序。这保证了事实层和编译知识层的类型边界清晰，也避免 L3 compiled knowledge 重新变成串台源。
>
> **Digest Recall 隐藏规则**：`task_digest` 属于 L2 编译原料，不属于用户侧普通 recall 对象。搜索编排会在普通 recall 阶段主动隐藏 `event_type='task_digest'` 的 episodic 结果，避免“原始 digest + 编译后 claim”同时进入模型上下文，浪费 token 并打乱知识层次。
>
> **Model-Ready Summary 编译层**：Claim 编译阶段会同步生成稳定的 `model_summary`，并持久化在图节点上。Recall 时优先直接消费该摘要，而不是每次临时拼接 `claim_text/last_result/evidence_count`，从而让跨渠道复用和后续 prompt 注入具备稳定输入。
>
> **Lifecycle Hook Protocol**：`protocols/hooks.py` 定义 `MemoryLifecycleHookProtocol`，提供 `on_turn_start`、`on_pre_compress`、`on_memory_write`、`on_delegation`、`on_session_end` 五个可选扩展边界。该协议只暴露 framework DTO / plain string，不承载 SharedContext、team、tenant 等产品语义。

---

## 四、Verbatim Storage 技术方案

### 4.1 设计动机

**问题：Irreversible Information Loss（不可逆信息丢失）**

传统方式（Episodic/Semantic Memory）仅存储LLM提取的摘要，丢失：

- 精确数字（"利润率23.7%" → "利润率约20%+"）
- 代码片段（"使用`async def foo()`" → "使用异步函数"）
- 精确措辞（"用户明确拒绝X" → "用户不喜欢X"）

**竞品研究：**

- [MemPalace](https://github.com/MemPalace/mempalace)在benchmark中达到96.6% R@5（verbatim baseline），而传统方式仅30-45%
- 关键insight：**Verbatim + 6 progressive enhancements** 才能达到98-99% R@5

### 4.2 ConversationMemory 设计

**Dual-field storage（双字段存储）：**

```python
class ConversationMemory(BaseMemory):
    raw_exchange: str           # User Q + AI A verbatim（永不修改）
    content: str                # LLM extracted summary（压缩版）
    raw_embedding: list[float]  # raw_exchange的向量
    summary_embedding: list[float]  # content的向量
```

**存储层：Qdrant Named Vectors**

```python
# Qdrant 1.10+ Universal Query API
vectors_config = {
    "raw": VectorParams(size=1024, distance=Distance.COSINE),
    "summary": VectorParams(size=1024, distance=Distance.COSINE),
}
```

**Dual-track extraction（双轨提取）：**

1. **Verbatim Track**（`enable_verbatim=True`，默认开启）：
   - 无LLM处理，直接存储raw exchange pairs
   - Exchange-pair chunking：`[(User Q1 + AI A1), (User Q2 + AI A2), ...]`
   - 100% lossless preservation
2. **Compressed Track**：
   - LLM提取SemanticMemory/EpisodicMemory
   - Context compression + efficiency

### 4.3 Adaptive Dual-channel Retrieval

**成本问题：**Dual-channel（同时查询raw + summary）成本+100%，但并非所有查询都需要dual-channel。

**Adaptive 3-factor decision logic：**

```python
def should_use_dual_channel(query: str, config: RetrievalConfig) -> bool:
    # Factor 1: Quoted phrases（精确匹配需求）
    if any(q in query for q in ['"', "'", "`", "「", "」"]):
        return True  # 有引号 → dual-channel

    # Factor 2: Token count（长查询更可能需要精确信息）
    token_count = get_token_count(query)
    if token_count >= config.adaptive_threshold:  # default: 5
        return True

    # Factor 3: Word diversity（高词汇多样性 → 复杂查询）
    if token_count >= 3:
        diversity = get_diversity_ratio(query)
        if diversity > config.adaptive_diversity_threshold:  # default: 0.7
            return True

    return False  # 短查询/简单查询 → single-channel (summary only)
```

**真实收益：**

- **-35% query cost**（实测，90%查询single-channel足够）
- **0% recall loss**（需要dual-channel时自动触发）

**Extensibility：**

```python
# Business layer can inject custom strategy
class HistoryBasedAdaptiveStrategy(AdaptiveChannelStrategy):
    def should_use_dual_channel(self, query: str) -> bool:
        # 基于用户历史行为决策
        ...

config = RetrievalConfig(adaptive_strategy=HistoryBasedAdaptiveStrategy())
```

### 4.4 配置与使用

**Framework layer（SkillAgent）：**

```python
agent = SkillAgent(
    ...,
    enable_memory_auto_extraction=True,  # 启用auto-extraction（默认True）
    extraction_llm=cheap_llm,  # 可选：使用便宜模型降本
)
```

**Backend API（GeneralAgent）：**

```python
# app/api/agents/general_agent.py
class GeneralAgentRequest(BaseModel):
    enable_memory_auto_extraction: bool = True  # 默认开启（开箱即用）
```

**Frontend（Settings > Memory Section）：**

```tsx
// src/components/ui/settings/sections/MemorySection.tsx
<Switch
  checked={enableMemoryAutoExtraction}
  onCheckedChange={setEnableMemoryAutoExtraction}
/>
```

**默认值：False（设计决策）**

- 让用户自行配置开启（隐私/性能考虑）
- 前端UI toggle可随时开启/关闭
- 未来可考虑默认开启（需产品决策）

### 4.5 技术细节

**Transparent BLOB Storage（透明大对象外部化存储）：**

为了解决 Qdrant 存储超大 `raw_exchange` 导致的内存和性能瓶颈，系统实现了透明的 BLOB 外部化存储：

```python
# 当 raw_exchange 超过 4KB 时，自动进行 Gzip 压缩并写入文件系统
if len(raw_exchange) > 4096:
    blob_path = write_to_blob_dir(gzip.compress(raw_exchange))
    # Qdrant payload 中仅存储极轻量的指针
    payload["raw_exchange"] = f"blob://{content_hash}"
```
- **零感知**：对上层业务完全透明，检索时自动拦截 `blob://` 前缀并从文件系统解压还原。
- **性能提升**：避免 Qdrant 内存膨胀，提升向量检索速度。
- **多租户隔离**：BLOB 存储路径动态绑定到 `WorkspaceContext`，确保多租户沙箱环境下的数据绝对隔离。
- **自动垃圾回收 (Blob GC)**：通过 `maintenance.py` 中的后台任务定期扫描，自动清理未被 Qdrant 活跃指针引用的孤儿 BLOB 文件，彻底解决磁盘泄漏风险。

**Compression（内联压缩）：**

对于低于 4KB 的中等文本，直接在 Qdrant payload 中进行内联 Gzip 压缩并 Base64 编码，减少 30-70% 存储空间。

**Multi-language tokenization：**

```python
# Unified tokenizer with CJK support
_WORD_PATTERN = re.compile(r"\w+", re.UNICODE)
# "Python性能优化" → ["python", "性能优化"]（单token）
```

**OTEL instrumentation：**

```python
_decision_counter.add(1, {"use_dual": use_dual, "is_override": False})
_decision_latency.record(latency_ms, {"use_dual": use_dual})
```

### 4.6 测试覆盖

- **Unit tests**: 845/845 (100%)
  - `test_adaptive_channel.py`: 12 tests（3-factor logic）
  - `test_text_utils.py`: 28 tests（multi-language tokenization）
  - `test_compression.py`: 12 tests（gzip compression）
  - `test_rrf_dedup.py`: 4 tests（RRF deduplication）
- **Integration tests**: `test_conversation_integration.py`（dual-channel storage + retrieval）
- **Coverage**: >80%（framework requirement）

### 4.7 与竞品对比

以下对比为 **定性**。若需在文档中对「自适应召回、检索成本或延迟」声称具体百分比，须在仓库内附上可重复的基准脚本或原始数据集与版本号——**本节不再预设未核验的百分比**。

| 维度               | MemPalace（参考对标） | MyrmAgent                         | 说明 |
| ------------------ | --------------------- | --------------------------------- | ---- |
| Verbatim 存储       | ✅                    | ✅                                | —    |
| Adaptive 查询      | ❌（文档视角）          | ✅（三路信号 + 阈值工程）           | Myrm Agent 可调节 |
| Hybrid BM25+Vector | ❌                    | ✅（RRF）                         | 混合召回 |
| 多语言 tokenization | ✅                   | ✅（统一 Unicode-aware 正则等）      | —    |
| 框架扩展性         | ❌                    | ✅（Protocol 注入）               | 与 LangChain 类库类比 |
| 生产可观测性       | ⚠️ 视上游版本而定      | ✅（框架内 OTEL 埋点取向）           | —    |

### 4.8 安全扫描

**Verbatim Storage 的安全挑战：**

由于 `ConversationMemory.raw_exchange` 存储原始用户输入（100% lossless），可能包含敏感信息：
- API keys / credentials
- Prompt injection attacks
- Invisible Unicode characters

**Memory Scanner 实现：**

写入路径：所有记忆在写入前经过 `memory_scanner.py` 扫描。

**心理安全与无痕模式 (Psychological Safety & Incognito Mode)：**
1. **Harmful State Detector**: `memory_scanner.py` 内置了有害心理状态检测器，用于拦截可能导致 "AI Psychosis"（AI 精神病）的严重负面心理状态（如自残、重度抑郁、被害妄想等）。当检测到此类状态时，扫描器会返回 `BLOCKED`，防止 AI 永久存储和强化这些瞬态情绪。
2. **Incognito Mode (无痕模式)**: 提供会话级别的完全无痕模式。开启后：
   - **AI 记忆隔离**：Server 业务层会强制将 `enable_memory` 设为 `False`，从物理层面彻底卸载所有记忆工具（不创建 MemoryManager，不注入 memory_save 等工具）。这确保了 AI 无法读取全局记忆，也不会自动或主动提取新记忆。
   - **持久化隔离**：会话在数据库中被标记为 `is_incognito=True` 以维持当前会话上下文，但在侧边栏历史列表 (`get_chat_list`) 中被彻底过滤隐藏。用户一旦离开页面，会话即在 UI 层面“焚毁”，实现真正的“阅后即焚”和零数据泄漏。

读取路径：`MemoryContextMiddleware` 注入时采用指令层级。**Stable（Profile/Rules/Self-Instructions/Corrections）**封装在 `<user_memory_context>` 的 **SystemMessage** 中。**Learned Preferences / Learned Rules**放入 **HumanMessage**，先 `sanitize()` 与逐项 `_escape_xml_item()`（降低伪造围栏标签风险），再由 `wrap_untrusted(..., source="memory_context")` 生成 `<<<UNTRUSTED_DATA id="…">>>` 信封，与同进程已注入的 `SECURITY_BOUNDARY_SYSTEM_RULES` 契约一致。

```python
def scan_and_clean_memory(memory: object, *, block_threshold: float = 0.8) -> ScanResult:
    """Scan all text fields of a memory object and clean in-place.
    
    Scans:
    - content (all memory types)
    - raw_exchange (ConversationMemory)
    - trigger/action (ProceduralMemory)
    """
```

**扫描策略：**

1. **Prompt Injection Detection**：7+2类注入攻击检测（`prompt_guard.py`）
   - HIGH score (≥0.8) → BLOCKED verdict → 触发用户审批
   - LOW score (<0.8) → WARN verdict → 记录日志并存储

2. **Credential Leak Detection**：25+种凭证模式检测（`leak_detector.py`）
   - 自动redact敏感信息（保留前6后4字符）
   - REDACTED verdict → 日志记录

3. **Invisible Unicode Stripping**：零宽字符清除（`content_boundary.py`）
   - 自动清除不可见字符
   - WARN verdict

**安全审计：**

- 所有扫描结果记录到 `ScanMetrics`（total_scans, blocked, redacted, warned）
- 安全决策记录到 audit trail（`agent.security.audit`）
- 生产环境可通过 `/api/v1/health/metrics` 监控扫描统计

**覆盖范围：**

| 字段           | 扫描覆盖 | 说明                                      |
| -------------- | -------- | ----------------------------------------- |
| content        | ✅       | 所有记忆类型的主要内容字段                |
| raw_exchange   | ✅       | ConversationMemory的verbatim原始对话      |
| trigger/action | ✅       | ProceduralMemory的行为规则字段            |

**测试覆盖：**

- `test_memory_scanner.py`：29个单元测试，覆盖所有verdict路径
- 包含 `test_conversation_memory_raw_exchange_*` 测试用例验证raw_exchange扫描

---

## 五、核心组件

### 5.1 MemoryManager

统一入口，协调所有记忆操作。通过 Protocol 注入存储后端和配置。

```python
from myrm_agent_harness.toolkits.memory import MemoryManager, MemoryConfig

manager = MemoryManager(
    config=config,
    relational=relational,     # RelationalStoreProtocol
    vector=vector_store,       # VectorStoreProtocol
    embedding=embed_adapter,   # EmbeddingProtocol
    graph=graph,               # GraphStoreProtocol (可选)
    approval_required=True,    # 启用审批（使用 RelationalStore 的 pending 方法）
)

results = await manager.search("用户的健身偏好", limit=10)
await manager.set_profile_attribute("name", "张三")
await manager.add_knowledge("用户喜欢简洁的回答", importance=0.8)
await manager.add_event("用户询问了健身计划", event_type="conversation")
await manager.add_rule(trigger="用户请求文件", action="使用 Excel 格式")
```

### 5.2 MemorySession（对话级缓冲）

延迟写入直到对话结束，减少 IO 开销：

```
Agent.process_stream(chat_id)
  ├── manager.begin_session(chat_id)
  │     ├── memory_save_tool("知识A") → buffer (0 IO)
  │     ├── memory_save_tool("知识B") → buffer (0 IO)
  │     ├── memory_save_tool("偏好")  → DB (幂等直写)
  │     ├── memory_recall_tool("xxx") → DB + buffer merged
  │     └── finally: manager.end_session()
  │           ├── store_batch() → batch persist + dedup
  │           ├── preference micro-rebuild
  │           ├── maybe_consolidate (interval-based)
  │           └── recurrence_check (async background)
  │                 └── embedding similarity → trigger LLM consolidation if ≥k
  └── agent.close()
```

- Semantic/Episodic/Procedural 缓冲；Profile 直写（幂等）
- `memory_recall_tool` 合并持久化结果和缓冲区
- 无 session 时等同直写（优雅降级）

### 5.3 MemoryRetriever（混合检索 + RRF 融合 + MMR 多样性重排）

**双通道混合检索架构**：

```
Query
  ├─→ Vector 通道（语义相似度）
  │     └─→ Semantic + Episodic collections
  │
  ├─→ BM25 通道（关键词匹配）
  │     └─→ Semantic + Episodic full-text (auto-degrades >5000)
  │
  └─→ RRF 融合 + 纠正链抑制 + MMR 多样性选择（content_sim + source_decay）+ 归一化
        └─→ 最终结果
```

**评分机制**（加权几何平均数）：

```
final = semantic^w0 × recency^w1 × frequency^w2 × importance^w3 × preference^w4 × confidence
```

- 加权几何平均，类型感知权重（见 `signals.py`）
- 语义主导（Semantic 权重 ≥ 0.70）
- 无逆转：低语义分数无法通过高热度逆转
- 纠正链抑制：被纠正记忆的分数乘以 `correction_penalty`（默认 0.1）
- Source Decay：MMR 选择时对已选来源的记忆施加软惩罚，促进跨会话多样性。`penalty = content_sim + source_diversity_weight × (same_source_count / selected_count)`，默认 weight=0.5，设为 0 退化为纯内容 MMR

**类型感知信号权重**：

| 类型           | Semantic | Recency | Frequency | Importance | Half-life |
| -------------- | -------- | ------- | --------- | ---------- | --------- |
| **Semantic**   | 0.70     | 0.12    | 0.08      | 0.10       | 30天      |
| **Episodic**   | 0.45     | 0.30    | 0.15      | 0.10       | 7天       |
| **Profile**    | 0.20     | 0.00    | 0.00      | 0.30       | 无衰减    |
| **Procedural** | 0.35     | 0.00    | 0.15      | 0.50       | 无衰减    |

**信号计算**（见 `signals.py`）：

- **Recency**: `exp(-ln(2) × age_days / half_life_days)`
- **Frequency**: `log(1 + access_count) / log(1 + saturation_point)`
- **Importance**: 直接提取 `memory.importance`
- **Preference**: 直接提取 `memory.preference_strength`
- **Confidence**: 直接提取 `memory.confidence`（作为最终乘数）

**BM25 自动降级**：当用户记忆总量超过 `bm25_max_corpus_size`（默认 5000）时，自动禁用 BM25 通道以保证性能，回退到纯 Vector 检索。

### 5.4 EmbeddingCache（双层缓存）

```
查询 → L1 Memory LRU (μs) → L2 API (100ms+)
```

直接实现 `EmbeddingCacheProtocol`，支持 `get/put/get_batch/put_batch`。使用 LRU 策略淘汰旧缓存。

---

## 六、Protocols（存储后端接口）

框架定义接口，三大后端全部开箱即用：

| Protocol                  | 核心方法                                                                                                 | 框架内置实现                                           | 可选企业级实现    |
| ------------------------- | -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ | ----------------- |
| `VectorStoreProtocol`     | `upsert`, `search`, `scroll`, `delete`                                                                   | `QdrantVectorStore`                                    | -                 |
| `RelationalStoreProtocol` | `get_profile`, `set_profile`, `create_rule`, `submit_pending` 等 21 个方法                               | `SQLiteRelationalStore` (aiosqlite)                    | SQLAlchemy 适配器 |
| `GraphStoreProtocol`      | `create_node`, `create_relationship`(幂等), `get_causal_chain`, `delete_subgraph`, `delete_all_by_owner` | `SQLiteGraphStore` (aiosqlite + CTE + UNIQUE 关系去重) | SQLite CTE        |
| `EmbeddingProtocol`       | `embed`, `embed_batch`, `dimension`                                                                      | `EmbeddingService`                                     | -                 |
| `EmbeddingCacheProtocol`  | `get`, `put`, `get_batch`, `put_batch`                                                                   | `EmbeddingCache` (L1+L2)                               | -                 |

---

## 七、Strategies（可插拔策略）

### 7.1 三层智能去重 (`strategies/deduplicator.py`)

**三层架构**：

| 层级        | 方法          | 判断依据         | 决策                                            |
| ----------- | ------------- | ---------------- | ----------------------------------------------- |
| **Layer 1** | Hash 精确匹配 | SHA-256 内容哈希 | DUPLICATE（跳过）                               |
| **Layer 2** | Vector 相似度 | 语义向量 cosine  | ≥0.95 → DUPLICATE；<0.60 → NEW                  |
| **Layer 3** | LLM 语义判断  | 上下文理解       | DUPLICATE / UPDATE_REPLACE / UPDATE_MERGE / NEW |

**四种决策**：

| 决策             | 含义           | 示例                                |
| ---------------- | -------------- | ----------------------------------- |
| `DUPLICATE`      | 语义相同，跳过 | "timeout 5s" vs "timeout 5 seconds" |
| `UPDATE_REPLACE` | 参数/版本变化  | "pool size 10" → "pool size 50"     |
| `UPDATE_MERGE`   | 增量功能合并   | "缓存" + "备份" → 合并特性          |
| `NEW`            | 独立记忆       | 不同事件                            |

**关键特性**：

- 动态阈值：Semantic (0.95/0.60) vs Episodic (0.92/0.65)
- 早期锁保护：Vector 搜索后立即预留目标，避免冗余 LLM 调用
- 合并追踪：`merge_count` 和 `merge_history` 记录演化历史
- Metadata 合并：UPDATE_REPLACE 全替换 / UPDATE_MERGE 合并覆盖；tags 去重合并；source 字段始终更新为最新来源
- 失败降级：LLM 失败时默认为 NEW（避免丢失）

### 7.2 遗忘策略 (`strategies/forgetting.py`)

四维保留分数计算：

```
retention = 0.4 × time_score + 0.3 × access_score + 0.2 × importance_score + 0.1 × relation_score
```

- `time_score`：基于半衰期 90 天的指数衰减
- `access_score`：`min(1.0, access_count / 20)`
- `importance_score`：记忆重要性（0-1）
- `relation_score`：向量邻居数近似（sim > 0.8），零额外写入

保护规则（优先级从高到低）：

- `pinned=True` 的记忆无条件豁免（用户标记保护）：
  - 遗忘策略：`should_forget=False`，reason="Protected: user-pinned"
  - Agent 工具删除：`allow_pinned=False` 时拒绝删除，返回明确拒绝消息（防 prompt injection）
  - WebUI/管理员操作：`allow_pinned=True`（默认），可正常删除
- 创建 7 天内的记忆不遗忘
- importance ≥ 0.9 的记忆受保护
- 最近 7 天内访问过的记忆受保护

### 7.3 自动提取 (`strategies/extractor.py`)

`MemoryExtractor` 使用 LLM 从对话中自动提取结构化记忆。

**核心特性**：

- **6 大原则**：防注入、穷尽提取、细节保留、时间精度、**No-Op Default (严格精度门控)**、主体归属隔离 (Attribution)。
- **No-Op Default (严格精度门控)**：彻底颠覆传统的高召回倾向，向大模型施加极其严厉的 `Strict Precision` 惩罚指令。默认返回空数组 `[]`，仅在存在高杠杆价值知识、明确用户约束时才允许提取。从源头阻断日常闲聊产生的碎片垃圾入库，保护长期上下文纯净度。
- **主体归属隔离 (Attribution)**：严格区分用户本人与第三方（家人、朋友、同事等），禁止将第三方的特征、疾病或偏好归因于用户本人。
- **瞬态情绪过滤 (Transient State Filter)**：过滤掉短暂的情绪和心理状态（如“今天很焦虑”、“感觉很抑郁”），除非明确说明是慢性疾病，防止 AI 永久存储瞬态情绪。
- **动态提示词**：根据 `ExtractionConfig` 动态生成，仅包含启用的记忆类型
- **Token 优化**：337 tokens（全类型）→ 229 tokens（最小配置），节省 32%

```python
from myrm_agent_harness.toolkits.memory.strategies.extractor import MemoryExtractor

extractor = MemoryExtractor(llm_func=llm)
result = await extractor.extract(messages=messages)
# result.memories → [ExtractedMemory(...), ...]
```

### 7.4 Tool-Scoped Memory Capture (`tool_capture.py`)

`ToolMemoryCaptureHook` 从两条零 LLM 成本路径自动创建工具级行为规则：

1. **Edict 检测**：正则匹配用户禁令/偏好（中英双语），关联到具体工具后存为 CRITICAL 优先级 `ProceduralMemory`
2. **重复失败记录**：同一工具在会话中失败 ≥2 次时，创建 NORMAL 优先级规则引导后续工具选择

**数据流**：
- `extract_memories_from_conversation` 对 user 消息执行正则预扫描，零 LLM 成本捕获 edicts
- `ToolMemoryCaptureHook.on_post_tool_failure` 跟踪工具失败次数
- `MemorySession.flush()` 调用 `hook.drain_pending()` 将待持久化规则纳入批量写入
- `memory_context_middleware` 将 CRITICAL/HIGH 优先级规则提升到 stable 层（抗压缩），NORMAL 保持在 untrusted 层

**优先级层级**（`ToolRulePriority`）：

| 级别 | 来源 | 注入位置 | 压缩抗性 |
|------|------|---------|---------|
| CRITICAL | 用户显式禁令 | stable_sections | 免压缩 |
| HIGH | 用户强偏好 | stable_sections | 免压缩 |
| NORMAL | 自动推断/失败 | untrusted_sections | 可压缩 |

```python
from myrm_agent_harness.toolkits.memory import ToolMemoryCaptureHook, MemorySession

hook = ToolMemoryCaptureHook()
session = MemorySession(manager=mm, chat_id="...", tool_capture_hook=hook)
# hook.on_post_tool_failure 注册到 HookRegistry
# session.flush() 自动 drain pending rules
```

### 7.5 Pre-Compaction Recall (`agent/context_management/pre_compact_service.py`)

`MemoryPreCompactService` 是框架默认的 `ContextPreCompactCallback` 实现，在上下文 compaction 发生前从持久记忆库语义召回相关约束，并格式化为受保护的 `HumanMessage` 注入块（`wrap_untrusted(source="pre_compact_recall")` + `<pre_compact_recall_context>` marker）。

**Pipeline 位置**（Harness）：

```
Filter → CacheTtlPrune → PreCompactProcessor → Compress → SessionNotes → Summarize
```

**保护策略**：

| 阶段 | 行为 |
|------|------|
| PreCompactProcessor | 调用 callback，将 recall 写入 `context.metadata["pre_compact_message"]` |
| CompressProcessor | 压缩后 `apply_pre_compact_after_protected_head()` 插入 protected zone |
| SessionNotes / Summarize | `prepend_pre_compact_message()` 在 summary 前 protected prepend；已含 marker 时跳过重复注入 |

**预算与超时**：

- 用户预算：800–2000 tokens（Frontend 滑块 → Server `pre_compact_budget_tokens`）
- 动态缩放：随 token pressure 在 `[800, 2000]` 内调整
- 搜索超时：3s，失败非阻塞
- 子 Agent / subagent channel：Server `PreCompactMemoryExtension` 跳过，防止跨 Agent 污染

**Server 审计**（App Layer）：

- `PreCompactMemoryExtension` 包装 callback 并异步写入 Ledger `INJECT`
- metadata：`trigger=pre_compact`、`recalled_ids`、`compaction_tier`、`query_preview`
- Command Center Live Stream 与 Session Replay `memory_events` 投影同一账本事件

```python
from myrm_agent_harness.agent.context_management.pre_compact_service import MemoryPreCompactService

service = MemoryPreCompactService(manager)
injection = await service.build_injection(
    messages=messages,
    chat_id=chat_id,
    user_id=user_id,
    compaction_tier="compress",
    token_pressure_ratio=0.82,
    user_goal_hint="refactor auth module",
)
```

---

## 八、Agent 工具

### 8.1 工具创建

```python
from myrm_agent_harness.toolkits import create_memory_tools

tools = create_memory_tools(manager=manager)
```

只需传入 `MemoryManager` 实例。审批行为由 `manager.approval_required` 自动控制，无需额外参数。

### 8.2 工具列表

| 工具            | 功能                                                                  |
| --------------- | --------------------------------------------------------------------- |
| `memory_recall_tool` | 搜索记忆（合并缓冲区，偏好提权，纠正链抑制，图增强，动态陈旧代码路径验证警告）                  |
| `memory_save_tool`   | 存储新记忆，支持 knowledge/event/preference/rule/instruction 五种类别。description 含写入质量引导（何时存/何时不存/声明式写入/类别选择/重要性评分/write_target），从源头减少垃圾记忆 |
| `memory_manage_tool` | 更新/删除/纠正记忆（correct action 创建纠正链）                       |
| `conversation_search_tool` | 搜索历史会话，返回证据片段和预计算摘要；框架只依赖 `ConversationSearchProtocol` |

`memory_recall_tool` 的 `limit` 是 Agent 工具层上下文预算，而不是底层检索能力上限。工具入口会将模型请求归一化并收敛到 `1..15`：默认返回 5 条，复杂问题允许提升到 10-15 条，非法值回落到默认值，超大值不会继续下传到检索层。返回内容还会受到工具输出预算保护：每条超长记忆会截断正文但保留 id/category/score/age/citation 相关元信息，整体输出保持在上下文安全范围内，避免一次错误工具调用污染当前上下文窗口。检索链路会输出 sanitize / route / embed / collect / rank / graph / budget 等 retrieval trace step，供应用层做回放、诊断和瀑布流展示；该 DTO 不含业务表依赖，仍属于框架层通用能力。
`conversation_search_tool` 的 `limit` 收敛到 `1..8`；空查询或 `*` 表示浏览最近会话。工具自身不调用 LLM，也不持有数据库连接，并通过标准 `sources` 事件输出 `conversation_history` 来源；Server 层可用 FTS5 + `compacted_summary` 实现零现场摘要成本的会话召回。

### 8.3 审批机制

审批是 `MemoryManager` 的一等公民能力。当构造时 `approval_required=True`，审批自动启用：

```
前端开关 memoryRequireConfirmation=true
  → API 传入 approval_required=True
  → create_memory_manager(approval_required=True)
  → MemoryManager(relational=pg_store, approval_required=True)
  → manager.approval_required == True
  → Agent 调用 memory_save_tool
  → manager.store() 自动路由到 pending 队列
  → 前端展示待审批列表
  → 用户 approve → manager.approve(id) → 持久化到永久存储
  → 用户 reject  → manager.reject(id)  → 标记拒绝
```

`MemoryManager` 审批相关方法：

| 方法                     | 功能                       |
| ------------------------ | -------------------------- |
| `submit_pending(memory)` | 提交记忆到审批队列（去重） |
| `approve(pending_id)`    | 审批通过并持久化           |
| `reject(pending_id)`     | 拒绝                       |
| `list_pending(limit=50)` | 列出待审批记忆             |
| `count_pending()`        | 统计待审批数量             |
| `batch_approve(ids)`     | 批量审批                   |
| `batch_reject(ids)`      | 批量拒绝                   |

---

## 九、Agent 中间件

`MemoryContextMiddleware` 在首次 LLM 调用时注入两类记忆上下文，采用**指令层级 + 特权分离**：稳定层为高特权系统侧说明，学习到的事实/规则在低特权不可信数据中呈现，以降低间接提示词注入成功率。

注入内容拆分：

| 层级 | 内容 | 载体 | Prompt cache |
|-----|------|------|--------------|
| **Stable** | Profile、Self-Instructions、Behavioral Rules、Corrections | `SystemMessage`，包裹 `<user_memory_context>` | ✅ 与同用户前缀稳定对齐 |
| **Learned（advisory）** | Learned Preferences / Learned Rules | `HumanMessage`，注入 `[Created: YYYY-MM-DD]` 绝对时间戳，并经 `wrap_untrusted(...)` 包裹（`<<<UNTRUSTED_DATA id="…">>>`），与 SECURITY_BOUNDARY 规则对齐 | ⚠️ 随机边界 id 前缀每请求变化；带静态绝对时间戳，保留 Prompt Caching |

**一次性注入**：若消息前部已包含 `<user_memory_context` **或** `<<<UNTRUSTED_DATA`，则跳过，避免/learned-only 路径被重复写入。

前缀顺序（与其它中间件 stacking 对齐后）通常为：

```
[0] System: core prompt
[1+] System: `<data_boundary_rules>`（SecurityBoundary）
[+] System: `<user_instructions>` …
[+] System: `<user_memory_context>` … stable …
Human: <<<UNTRUSTED_DATA>>> learned … （若有）
Human: 用户第一轮输入 …
```

---

## 十、自动化机制

| 机制                       | 触发时机                      | 行为                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| -------------------------- | ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **集成数据自动播种**       | Integration 数据同步结束时    | **Automated Knowledge Seeding**：在服务端监听集成数据同步事件，拦截最新的一小批结构化数据（含类型和标题，限制在 200 条内以优化 Token），通过 `asyncio.create_task` 在后台异步调用 `MemoryExtractor` 的 No-Op Default 机制，静默提取高价值偏好特征并写入全局 Profile。                                                                                                                                                           |
| **自动提取（Dual-track）** | `SkillAgent.run()` 结束时     | **Verbatim Track**（`enable_verbatim=True`，默认）：Raw exchange pairs存储为ConversationMemory（无LLM，lossless）；**Compressed Track**：LLM提取Semantic/EpisodicMemory（压缩）。需开启 `enable_memory_auto_extraction=True`（**默认True**，frontend UI toggle可配置）。可选：Task Digest（`enable_task_digest=True`），独立模型降本（`extraction_llm`）。Quality filter：跳过trivial conversations（<=3 messages且reply<100 chars），除非检测到correction signals |
| **三层智能去重**           | `store_batch()`               | Hash（完全相同）→ Vector（相似度分段）→ 早期锁保护 → LLM（语义关系判断），支持 DUPLICATE/UPDATE_REPLACE/UPDATE_MERGE/NEW 决策，避免冗余 LLM 调用（需传递 `dedup_llm`）                                                                                                                                                                                                                                                                                              |
| **循环触发巩固**           | `_cleanup_session()` 会话结束时 | 后台异步：将会话摘要 embedding 存入专用 recurrence buffer collection；若同话题出现 ≥k 次（cosine≥0.7），触发 LLM 精炼生成高质量长期记忆。重要性旁路：健康/安全/凭证类信息立即巩固。配置：`RecurrenceConfig`（`similarity_threshold`、`recurrence_k`、`buffer_capacity`、`importance_preemption`） |
| **定期遗忘**               | 每 N 次 `end_session()`       | 扫描低保留分数记忆并删除；`relation_count` 通过向量邻居数（sim>0.8）近似计算，仅对 Semantic 集合，零额外写入                                                                                                                                                                                                                                                                                                                                                        |
| **访问计数**               | `search()` 返回后             | 异步更新 `access_count` 和 `last_accessed_at`（fire-and-forget）                                                                                                                                                                                                                                                                                                                                                                                                    |
| **图增强检索**             | `search()` 有 Episodic 结果时 | 通过 `get_related_nodes_with_depth` 进行多跳图遍历（支持 2-hop，`asyncio.gather` 并行），统一评分系统（token overlap + distance decay + freshness + importance + channel affinity，与 Claim Graph 公式一致），内容级去重（归一化 MD5 哈希），可配置兄弟节点数量（`graph_sibling_limit`）和遍历深度（`graph_max_depth`）                                                                                                                                                           |

---

## 十一、偏好记忆与反馈纠正

### Cognitive Deriver (异步辩证推理引擎)
废弃了传统的正则匹配，全面采用基于 LLM 的 Cognitive Deriver 进行偏好提取与画像生成：
1. **隐性偏好提取**：`MemoryExtractor` 在对话结束时，通过 Dialectic Reasoning（辩证推理）从对话中提取用户的显性喜好。
2. **实时偏好投影 (Real-time Persona Projection)**：`CognitiveDeriver` 在异步提取出 `reply_style`、`cognitive_depth`、`proactivity` 等核心隐性偏好后，除了在图数据库中保存证据和处理冲突，还会**实时投影**（双写）到用户的 `ProfileEntry` (KV存储) 中。`MemoryContextMiddleware` 会在下一轮对话中瞬间读取并注入到 System Prompt，实现“0延迟”的个性化体验。
3. **Agent 认知注入**：`memory_context_middleware.py` 自动拦截并读取该画像与长期目标、隐性偏好，将其常驻注入到大模型的 System Prompt (`<Our Relationship & Your Persona>`) 中，彻底解决 Agent 认知致盲问题，且完美契合 Prompt Caching。

### 偏好记忆

`SemanticMemory` 内置偏好字段，由 Cognitive Deriver 自动提取：

- `preference_type`: `"explicit"` | `"implicit"` | `None`
- `preference_strength`: 0.0-1.0，检索时自动通过加权几何平均融合
- 统一检索路径：`memory_recall_tool` 自动返回偏好记忆，无需模型选择不同工具

### 偏好稳定性检测

`PreferenceStabilityStrategy`（`strategies/preference_stability.py`）管理偏好生命周期：

- **六类偏好分类**（PreferenceCategory）：Identity(90d)/Veto(60d)/Tooling(30d)/Goal(30d)/Style(14d)/Channel(7d)，各有独立半衰期
- **稳定性公式**：`stability = cue_weight × exp(-ln2 × Δt/half_life) × ln(1 + evidence_count) × explicit_mult`（explicit_mult: 显式证据2.0倍加成）
- **四级生命周期**：Candidate(≥0.4) → Provisional(≥0.7) → Active(≥1.5)，<0.4→Dropped
- **类别预算**：每类最多 3-5 个 Active 偏好，防止膨胀
- **Value冲突解决**：同 key 不同 value 时 argmax(stability) 自动选最强证据，弱者删除
- **用户覆盖**：Pinned=∞ 永不衰减，Forgotten=0 立即清除
- **触发时机**：session 结束 micro_rebuild（快速晋升），maintenance 周期 full_rebuild（全量衰减+清理）
- **持久化**：独立 SQLite `preference_facets` 表（`PreferenceFacetStoreProtocol`），WAL 模式

### 反馈纠正

`correct` action 实现"纠正不是删除，是用更强的真相覆盖错误"：

```
Agent: memory_manage_tool(action="correct", memory_id="abc", new_content="正确的事实")
  → 旧记忆 "abc": importance ×0.3, confidence → 0.1, metadata["corrected"]=True
  → 新记忆 "xyz": confidence=0.95, correction_of="abc"（纠正链）
  → 检索时抑制: importance降权 × confidence降权 × correction_penalty(0.1)
```

### 非对称信任评分

`rate_memory()` 使用非对称 EMA 更新 `user_rating`，负反馈权重高于正反馈：

```
alpha = alpha_negative (0.5) if normalized < old_rating else alpha_positive (0.3)
rating_new = rating_old + alpha * (normalized - rating_old)
```

设计理由：错误信息的伤害远大于正确信息的价值。一条错误记忆被召回后用户纠正，
该记忆的 rating 应快速下降并需要更多正面验证才能恢复信任。配置项：
`rating_alpha`（正向，默认 0.3）、`rating_alpha_negative`（负向，默认 0.5）。

---

## 十二、部署模式

| 组件               | 统一架构 (Agent-in-Sandbox)                                                                        |
| ------------------ | -------------------------------------------------------------------------------------------------- |
| Profile/Procedural | SQLite (本地文件)                                                                                  |
| Semantic/Episodic  | Qdrant Embedded (本地文件)                                                                         |
| GraphStore         | SQLite CTE (本地文件)                                                                              |
| PendingStore       | SQLite (本地文件)                                                                                  |
| **总依赖**         | ✅ 零 Docker，零云端数据库，完全基于本地文件系统，通过 `MEMORY_BASE_PATH` 环境变量映射到持久化卷。 |

---

## 十三、参考资料

- [CoALA: Cognitive Architectures for Language Agents](https://arxiv.org/abs/2309.02427)
- [A-MEM: Agentic Memory](https://arxiv.org/abs/2502.12110)
- [Qdrant 官方文档](https://qdrant.tech/documentation/)
- [Apache AGE 文档](https://age.apache.org/)

## FTS5 混合检索 (Hybrid Search)

为了解决长周期会话的“失忆”和“上下文爆炸”问题，系统实现了基于 SQLite FTS5 的混合检索架构：

- **零冗余存储**：使用 `External Content` 模式，只建倒排索引不复制原始对话文本，节省 50% 磁盘。
- **自动同步**：在 SQLite 层面建立 `INSERT/UPDATE/DELETE` 触发器，彻底杜绝应用层代码漏写导致的索引不一致。
- **多语言支持**：强制启用 `trigram` 分词器，确保中英文混合搜索的 100% 召回率。
- **混合检索**：底层并行触发 FTS5（精准关键词匹配）和 Vector（语义匹配），并使用 RRF（倒数排序融合）算法进行数学重排。
- **语法清洗**：提供严格的 FTS5 查询语法清洗（Sanitization），支持带点号和连字符的代码文件名防切词，拦截崩溃注入。
