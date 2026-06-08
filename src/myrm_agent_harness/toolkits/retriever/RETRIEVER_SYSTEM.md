# 检索系统设计文档

> 框架：`myrm_agent_harness.toolkits.retriever`

---

## 一、设计目标

构建 **混合检索** 的 RAG 检索系统：

- **语义 + 关键词**：向量搜索（语义）与 BM25（关键词）结合，提高召回率
- **灵活管道**：预处理 → 分块 → 嵌入 → 并行检索 → 融合 → 重排序
- **可插拔**：支持多种向量后端（Qdrant、Numpy）、嵌入模型、融合策略
- **性能优化**：智能缓存、批量处理、并发检索、性能监控

---

## 二、系统架构

### 2.1 检索管道

```
1. 文档预处理 (preprocessing)  — 过滤、清理、标准化
2. 文档分块 (splitter)         — 长文档分割，多种分块策略
3. 文本嵌入 (embedding)        — 本地/云端嵌入服务
4. 并行检索 (vector + BM25)    — 向量语义 + 关键词检索
5. 结果融合 (fusion_strategies)— RRF、加权等融合策略
6. 重排序 (reranker)           — 精排提升相关性
7. 返回 Top-K 结果
```

### 2.2 模块依赖关系

```
hybrid_retriever (混合检索器)
  ↓ 使用
├─ qdrant_retrieval (向量检索)
│   ↓ 使用
│   embedding/ (嵌入服务)
├─ bm25_retrieval (关键词检索)
│   ↓ 使用
│   bm25/ (BM25 算法)
└─ reranker/ (重排序)
```

### 2.3 子模块职责

| 子模块 | 职责 |
|--------|------|
| **embedding/** | 文本嵌入（本地/云端），支持多种嵌入模型 |
| **bm25/** | BM25 算法实现和分词器 |
| **reranker/** | 检索结果重排序（提高相关性） |
| **splitter/** | 文档分块（多种分块策略） |
| **preprocessing/** | 文档预处理（过滤、清理、标准化） |
| **hybrid_search/** | 混合搜索管道（检索 → 融合 → 重排序） |
| **sufficiency/** | 检索充分性评估（LLM-based 后检索质量判断 + 负面约束检测） |
| **vector_search/** | 向量搜索（Qdrant、Numpy 等后端） |

---

## 三、融合策略

- **RRF (Reciprocal Rank Fusion)**：无参数融合，常用默认
- **加权融合**：可配置向量/BM25 权重
- **自定义**：通过 `fusion_strategies` 扩展

---

## 四、与 app/core/retriever 的关系

- **myrm_agent_harness.toolkits.retriever**：通用检索框架，零业务依赖
- **app.core.retriever**：业务层封装，集成知识库、权限、图存储等

---

## 五、相关文档

- [ARCHITECTURE.md](../../../../ARCHITECTURE.md) - 项目整体架构
- `embedding/` - 嵌入服务模块
- `bm25/` - BM25 实现模块
- `reranker/` - 重排序服务模块
