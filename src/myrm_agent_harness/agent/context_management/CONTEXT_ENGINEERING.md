
# 上下文工程：AI Agent 的核心竞争力

当 AI Agent 执行复杂任务时，上下文窗口会被大量工具调用结果填满——成本飙升、延迟累积、性能下降。Manus 的实测数据显示，通过**缓存层优化**（保持工具列表不变、前缀稳定、只追加不删除）和**五维度上下文管理**（卸载、缩减、检索、隔离、缓存），推理次数从 4.3 降至 1.2 次，总成本直接砍掉 72%。

本文系统梳理了来自 Manus、Anthropic、Factory Research 等一线团队的上下文工程实战经验，涵盖从架构设计到成本优化的完整方法论。无论你是在构建自己的 Agent 系统，还是想深入理解 AI Agent 的核心瓶颈，这篇文章都值得参考。

> 核心参考来源：
> - Manus Context Engineering + Anthropic Prompt Caching 文档
> - Manus 联合创始人季逸超（Pete）与 LangChain 创始工程师 Lance Martin 的深度对话
> - Anthropic Multi-Agent 的上下文隔离策略

---

## 目录

1. [核心问题](#1-核心问题) - 上下文腐烂、KV 缓存重要性
2. [架构设计](#2-架构设计) - Manus 双层优化、多智能体原则、设计哲学对比
3. [五维度上下文管理](#3-五维度上下文管理) - Offload、Reduce、Retrieve、Isolate、Cache
4. [Prompt Cache 优化策略](#4-prompt-cache-优化策略) - 前缀匹配、批量清理、工具分层、缓存断点
5. [成本分析与决策模型](#5-成本分析与决策模型) - 成本公式、场景化决策
6. [各模型提供商对比](#6-各模型提供商对比) - Anthropic、OpenAI、阿里云、Gemini
7. [最佳实践](#7-最佳实践) - System Prompt 设计、工具定义顺序、监控调优
8. [设计原则](#8-设计原则) - 核心原则、上下文退化模式、关键技术
9. [参考资料](#9-参考资料) - 官方文档、Claude Code 实战、开源项目

---

## 1. 核心问题

### 1.1 上下文腐烂 (Context Rot)

随着 Agent 执行越来越长的任务，上下文窗口会被大量工具调用结果填满，导致：

1. **成本急剧增加**：每一轮都要把所有先前的工具结果传回给模型
2. **延迟累积**：处理更长的上下文需要更多时间
3. **性能下降**：研究表明性能会随着上下文长度而下降

**关键数据**：
- Manus 平均每个任务涉及 **50+ 次工具调用**
- 任务长度大约每 **7 个月翻一番**

### 1.2 为什么 KV 缓存是 Agent 最重要的指标

> "如果我必须选择一个指标，我认为 KV-cache 命中率是生产阶段 AI 代理最重要的单一指标。" —— Manus

**原因**：
- Agent 的输入/输出比例约 **100:1**（大量输入，少量输出）
- 缓存命中可节省 **10 倍成本**（Claude: $0.30 vs $3.00 / M tokens）
- 直接影响 TTFT（首 token 延迟）

### 1.3 什么是 Prompt Caching？

Prompt Caching 是模型提供商（如 Anthropic、OpenAI）提供的优化机制：

> 如果连续两次 API 调用的 Prompt **前缀相同**，第二次调用可以复用第一次的计算结果。

**优势**：
- **成本降低**：Anthropic 缓存命中时 90% 折扣
- **延迟减少**：跳过重复的前向计算
- **吞吐提升**：相同成本下可处理更多请求

**关键约束**：
- 缓存基于**字节级前缀匹配**
- 任何修改都会破坏从该位置开始的缓存
- 前面的内容改变，后面的缓存全部失效

---

## 2. 架构设计

### 2.1 Manus 双层优化架构

```text
Manus 的设计目标：
提高准确率 + 保持缓存有效 + 降低成本

分成两个层面：

第一层：缓存层（成本优化）
├─ 目标：保持缓存有效
├─ 策略：
│  ├─ 前缀稳定（工具列表不变）
│  ├─ 上下文只追加（不删除历史）
│  └─ 手动触发缓存（显式标记断点）
└─ 结果：缓存命中率高 → 每次推理成本低

第二层：准确率层（质量优化）
├─ 目标：提高模型准确率
├─ 策略：
│  ├─ 上下文感知状态机（管理工具可用性）
│  ├─ 约束解码（禁用不允许的工具）
│  └─ 响应预填充（强制正确的格式）
└─ 结果：失败率低 → 重试次数少

两层的结合效果：
准确率高 + 缓存有效
    ↓
推理次数少 + 每次推理成本低
    ↓
总成本最低
```

**关键设计**：状态机不改变工具列表，而是通过约束解码限制可用工具。

```text
❌ 传统方法（破坏缓存）：
状态 1：工具列表 = [A, B, C, D]
状态 2：工具列表 = [A, B]  ← 改变了！
结果：缓存经常失效 ❌

✅ Manus 的做法（保持缓存）：
状态 1：工具列表 = [A, B, C, D]（始终不变）
状态 2：工具列表 = [A, B, C, D]（始终不变）
        ↓ 但通过约束解码禁用 C、D
结果：缓存始终有效 ✅
```

> **注意**：约束解码（Logits Masking）和响应预填充仅适用于自托管模型。商业 API（OpenAI/Claude/Gemini）不支持这些特性，但缓存层的策略对所有模型都有效。

### 2.2 多智能体架构原则：智能体即工具

> **核心洞察**（来自 Manus）：「我们对增加更多子智能体非常谨慎，原因我们之前提过，**通信非常困难**。我们更多地将子智能体实现为'智能体即工具'的形式。」

#### 2.2.1 架构模式对比

```text
❌ 错误模式 A：完全没有子智能体
主 Agent
  ├─ search_tool（普通工具）
  ├─ bash_code_execute_tool（普通工具）
  └─ file_tool（普通工具）

问题：
- 所有复杂逻辑都在主 Agent 中
- 主 Agent 上下文会爆炸（研究过程的所有细节都在主上下文）
- 无法灵活使用不同模型

❌ 错误模式 B：平级的多智能体互相通信
Orchestrator Agent（调度者）
  ├─ 设计师 Agent ←┐
  ├─ 程序员 Agent ←┼→ 互相通信
  └─ 测试员 Agent ←┘

问题：
- 通信复杂（消息格式、路由）
- 信息丢失（传递链路长，Telephone Game 问题）
- 状态不一致
- 难以调试

✅ 正确模式：主 Agent + 子智能体（工具形式）
主 Agent（通用执行器）
  │
  │ 上下文作为信息总线
  │ ┌─────────────────────────┐
  │ │ 所有工具的返回都进入    │
  │ │ 这个上下文，子智能体     │
  │ │ 不直接互相通信          │
  │ └─────────────────────────┘
  │
  ├─ planner_tool（子智能体，有推理能力）
  ├─ delegate_to_agent_tool / dispatch_research（子智能体委派，独立上下文）
  ├─ knowledge_manager（子智能体，有推理能力）
  │
  ├─ search_tool（普通工具）
  ├─ bash_code_execute_tool（普通工具）
  └─ file_tool（普通工具）

优势：
- 主 Agent 负责编排，上下文精简
- 子智能体处理复杂任务，独立上下文（Isolate）
- 统一的工具接口，调用简单
- 灵活使用不同模型（规划用小模型，研究用大模型）
```

#### 2.2.2 子智能体 vs 普通工具

**关键问题**：什么时候需要子智能体？什么时候只需要普通工具？

| 维度 | 普通工具 | 子智能体（智能体即工具） |
|------|---------|------------------------|
| **推理能力** | ❌ 无，只执行固定逻辑 | ✅ 有，能自主决策 |
| **上下文** | ❌ 无状态 | ✅ 独立的上下文窗口 |
| **迭代能力** | ❌ 一次调用一次结果 | ✅ 可多轮迭代决策 |
| **工具调用** | ❌ 不能调用其他工具 | ✅ 可以调用工具 |
| **对外接口** | ✅ 工具接口 | ✅ 工具接口（包装） |
| **示例** | `grep_tool`, `file_read_tool` | `planner_tool`, `delegate_to_agent_tool` |

**决策树**：

```text
需要实现新功能
    │
    ↓
需要推理/决策能力？
    ├─ 否 → 普通工具
    │       例如：search、file、time
    │       特征：固定逻辑、无状态
    │
    └─ 是 → 需要多轮迭代？
            ├─ 否 → 可能只需要一次 LLM 调用
            │       （考虑在主 Agent 中实现）
            │
            └─ 是 → 子智能体（工具形式）
                    例如：研究员、规划器
                    
                    特征：
                    - 有独立系统提示
                    - 可调用其他工具
                    - 多轮迭代决策
                    - 独立上下文（Isolate）
```

### 2.3 多智能体设计哲学对比

> 当前业界存在两种截然不同的多智能体设计思路，分别以 Yuker（Claude Code Sub-Agent 实践）和 Manus 为代表。理解两者的异同对于做出正确的架构决策至关重要。

#### 2.3.1 两种设计哲学的核心分歧

**Yuker 的"拟人化团队"思路**

- **理念**：将 Multi-Agent 系统类比为**人类团队分工**，强调"专业化角色"
- **典型实践**：Four Agent 系统（架构师 + 构建师 + 验证者 + 记录员）
- **底层逻辑**：任务按**职能领域**切分（设计、开发、测试、文档）
- **通信机制**：通过共享文件（如 `MULTI_AGENT_PLAN.md`）进行通信
- **核心数据**：Anthropic 内部数据显示，Claude Opus 4 + 多个 Sonnet 4 组成的多智能体系统，在研究任务上比单个 Opus 4 高出 **90.2%**

**Manus 的"最小化反拟人"思路**

- **理念**：认为按角色划分智能体是**对人类组织的不必要模仿**，源于人类上下文窗口的局限性
- **典型实践**：仅 3-4 个智能体（通用执行器 + 规划器 + 知识管理器）
- **底层逻辑**：任务按**功能抽象层次**切分（规划层、执行层、知识层）
- **通信机制**：双模通信（简单任务用通信模式，复杂任务用共享上下文模式）+ Schema 约束输出
- **核心洞察**：「我们对增加更多子智能体非常谨慎，**通信非常困难**。我们更多地将子智能体实现为'智能体即工具'的形式。」

#### 2.3.2 关键设计维度对比

| **维度** | **Yuker（拟人化）** | **Manus（反拟人化）** |
|---------|-------------------|---------------------|
| **智能体数量** | 4+ 个（可扩展） | 3-4 个（极度克制） |
| **划分原则** | 按工作流阶段 | 按系统功能 |
| **通信策略** | 共享文件（Markdown） | 双模通信 + Schema |
| **专业化程度** | 高（每个高度专精） | 低（通用执行器） |
| **可扩展性** | 易扩展（添加新角色） | 难扩展（需重新设计） |
| **通信复杂度** | O(n) 线性增长 | O(1) 低复杂度 |

#### 2.3.3 如何选择？

**何时采用 Yuker 风格（拟人化）：**
- ✅ 需要快速原型验证（POC 阶段）
- ✅ 团队成员需要理解系统运作（可读性优先）
- ✅ 任务流程明确（如软件开发全生命周期）

**何时采用 Manus 风格（极简主义）：**
- ✅ 生产级系统（性能 + 成本优先）
- ✅ Token 成本是关键约束
- ✅ 需要高一致性和可靠性

**混合策略适用场景：**
- ✅ **平衡性能与可维护性**：既要控制成本，又要保持架构清晰
- ✅ **中等规模任务**：不需要 4+ 个角色，但也不能只用 3 个
- ✅ **渐进式扩展**：通过"智能体即工具"形式，灵活添加新能力

**关键洞察**：

> "不要为了'看起来很酷'而过度设计。无论选择哪种设计，都应避免为了拟人化而牺牲性能，也不要为了极简而牺牲可维护性。正确的架构是在**通信成本**、**上下文效率**和**系统复杂度**之间找到平衡点。"

#### 2.3.4 延伸阅读

- **Yuker 的实践**：[Multi-Agent 小白入门：让你的 Claude Code 提效 90.2%](https://x.com/YukerX/status/2013094122656334136)
- **Anthropic 数据**：多智能体系统在研究任务上比单智能体高出 90.2%（Opus 4 + Sonnet 4 组合）


## 3. 五维度上下文管理

> **核心理念**（来自季逸超）：「卸载和检索使得缩减更为高效，而稳定的检索则使隔离变得安全。但隔离又会减慢上下文的传递速度，降低缩减的频率。然而，更多的隔离和缩减又会影响缓存效率和输出质量。所以，归根结底，上下文工程是一门艺术与科学，它要求在多个可能相互冲突的目标之间找到完美的平衡。这真的很难。」

### 3.1 卸载 (Offload) - 长期持久化

**定义**：Agent **主动**将信息从上下文窗口转移到外部存储，以便**跨任务、跨调用**持久化。

**范畴**：长期记忆、技能系统、用户偏好、知识库

**特点**：
- **主动存储** - Agent 主动决定保存什么
- **长期保存** - 跨多个 Agent 调用持久化
- **按需检索** - Agent 在需要时主动读取
- **用途** - 保存计划、记忆、知识库、中间结果

#### Scratchpad 模式

> Scratchpad 是卸载策略的一种具体实现：Agent 主动维护一个结构化的笔记文件，记录任务进度、关键发现、待解决问题。这是独立于系统压缩/摘要的第一道防线。

#### 三层行动空间（Manus 架构）

> 参考：[上下文工程：理解 Agent 的统一框架](https://mp.weixin.qq.com/s/0esJgUxlBQ5ao-Fsv3LFqg)

Manus 采用**元工具 + 代码执行沙箱**架构，将行动空间分为三层：

| Manus 层级 | 可见性 | 示例 |
|-----------|--------|------|
| **Layer 1: Function Calls** | 模型可见 | `read_file`, `shell_exec`, `web_search` |
| **Layer 2: Sandbox Utilities** | 模型不可见 | `grep`, `ffmpeg`, `awk` |
| **Layer 3: Packages & APIs** | 模型不可见 | Pandas, Numpy, 外部 API |

**设计优势**：
- **最大化 KV Cache 命中率**：模型可见的工具定义极度稳定（约 10 个核心工具）
- **零 Token 占用**：Layer 2/3 的海量工具不占用上下文
- **无限扩展**：熟悉 Linux/Python 就拥有无限工具箱

```text
模型视角：
[file_edit_tool] [bash_code_execute_tool] [web_search_tool] [skill_select_tool]
       ↓                ↓              ↓                 ↓
   编辑文件        执行命令        网络搜索          加载技能
                     ↓
           [grep] [ffmpeg] [python script]  ← 模型不直接看到
```

#### 主动外部化（三层防线的第一层）

Agent 在任务进行中**主动**将关键发现写入文件，这是独立于系统压缩/摘要的第一道防线。

| 特性 | 主动外部化 | 系统压缩 |
|------|----------|---------|
| **触发者** | Agent 自己（Prompt 引导） | 系统自动（超过阈值） |
| **存储内容** | 提炼后的关键发现（50-200 tokens） | 原始工具输出（5000+ tokens） |
| **恢复成本** | 低（读取简短笔记） | 高（读取原始大文件） |

**价值**：在长对话中，主动外部化可避免恢复时重读大量原始数据。

### 3.2 缩减 (Reduce) - 会话级上下文管理

缩减策略用于管理**当前会话**的上下文体积，包含三种子策略：过滤、压缩、摘要。

#### 3.2.1 过滤 (Filtering) - 入口拦截

**定义**：当工具返回**单个大型结果**时，系统**自动**将其拦截并转移到文件系统，使用**任务感知的混合过滤策略**生成摘要。

**触发条件**：
```text
单个工具结果 > 阈值（如 5000 tokens）→ 触发过滤
```

**工具保护机制**：

某些关键工具的输出**不应被过滤**，避免 Agent 陷入死循环。例如：
- 技能文档被过滤后，Agent 读取文件又被过滤 → **死循环**
- 任务计划被过滤后，Agent 无法执行任务

**任务感知的混合过滤策略**：

根据内容类型自动选择最优过滤方式：

| 内容类型 | 过滤器 | 策略 | 需要 LLM |
|---------|--------|------|----------|
| **JSON** | 结构化过滤器 | 代码提取结构信息 | ❌ |
| **XML** | 结构化过滤器 | 代码提取标签结构 | ❌ |
| **代码** | 结构化过滤器 | 代码提取函数/类定义 | ❌ |
| **HTML** | 语义过滤器 | LLM 生成任务相关摘要 | ✅ |
| **Markdown** | 语义过滤器 | LLM 生成任务相关摘要 | ✅ |
| **纯文本** | 语义过滤器 | LLM 生成任务相关摘要 | ✅ |

**设计理念**：
> **任务感知**：过滤器不只是提取结构信息，而是根据用户的查询意图提取**相关**信息。

**工作流程**：

```text
工具返回结果
        │
        ▼
┌──────────────────────────────────────────────────────────────┐
│                    工具拦截中间件（过滤器）                      │
│                                                              │
│  结果 < 阈值  ──────────────────────────→  直接传递给 LLM     │
│                                                              │
│  结果 > 阈值  ────→ 存入文件 ────→ 任务感知过滤 ───→ LLM     │
│                    │                                         │
│                    ├─ 检测内容类型（JSON/HTML/代码等）          │
│                    │                                         │
│                    ├─ JSON/XML/代码 → 结构化过滤器             │
│                    │   └─ 代码提取结构信息（无 LLM 调用）       │
│                    │                                         │
│                    └─ HTML/MD/纯文本 → 语义过滤器              │
│                        └─ LLM 生成任务相关摘要                │
└──────────────────────────────────────────────────────────────┘
```

#### 3.2.2 压缩 (Compression) - 可逆的紧凑格式

**定义**：当**总上下文**达到阈值时，系统**自动**将历史中的旧工具调用结果**外部化到文件系统**，上下文只保留引用。

**触发条件**：
```text
总上下文 > 压缩阈值（如 60k tokens）→ 触发压缩
且预计节省 > 最小节省阈值（如 3k tokens）→ 避免破坏 Prompt Cache
```

> "通过大量的评估，确定那个'腐烂前'的阈值非常重要，通常在 128k 到 200k 之间。" —— Manus

**为什么压缩不需要工具保护？**

与过滤不同，**压缩不需要工具保护**，原因：

1. **压缩是可逆的**：内容存入文件系统，完整保留，Agent 可通过读取文件恢复
2. **过滤是不可逆的**：生成摘要，原始内容丢失部分细节，Agent 读取文件后又被过滤 → 死循环，**必须保护**
3. **成本权衡**：不保护压缩 → 节省 tokens → 降低成本；需要时恢复 → +1 轮交互（可接受）

**核心理念（来自 Manus）**：
> "信息被外部化了，没有真正丢失。只要信息能从外部状态重建，就应该从 Context 中剔除。"

**压缩后格式示例**：

```text
COMPACTED: web_search_tool
QUERY: Claude API pricing 2024
META: tokens_saved=5000 time=2024-12-20T15:30:00
FILE: /persistent/.context/user_001/session_abc/compacted/web_search_tool_20241220_153000_xyz.txt
RECOVER: cat /persistent/.context/user_001/session_abc/compacted/web_search_tool_20241220_153000_xyz.txt
```

**落盘与恢复策略**：
- 阈值：≥5000 tokens 写文件，<5000 tokens 纯内存
- 路径：`/persistent/.context/{session_id}/compacted/sha256/{prefix}/{tool}_{content_hash}_{original_bytes}.txt[.gz]`
- 压缩：>10KB 文件自动 gzip 压缩，降低可压缩文本 payload 的持久化体积
- 持久化：使用 Docker Volume 挂载到 `/persistent`，跨 Sleep/Destroy 保留
- 隔离：Per-User Container 架构，Docker 提供容器级物理隔离
- 目录结构：`{session_id}/compacted/`（压缩输出）、`scratchpad/`（主动外部化）
- 访问检测：归档写入和读取都记录到 `FileAccessTracker`，后台清理以会话活跃度和最近访问时间作为保留条件
- 恢复预算：执行层读取 `.context/{session_id}/compacted/` 文件时校验会话归属、整文件恢复 token 上限、单路径读取次数和单任务恢复 token 上限；整文件读取先用文件大小估算触发预算硬闸，文件大小探测失败时 fail-closed，不暴露归档正文
- 轻量索引：归档引用包含 `content_index` 和 `chunk_restore_args`，只记录行数、分块行号、文件读取参数、JSON 顶层 key / 数组长度、Markdown 标题以及代码块、表格、列表的行号范围，并在恢复阻断事件中输出 `restore_range_hints` 和 `content_features`，帮助模型和 GUI 按结构恢复，不把原文重新塞回上下文
- 幂等归档：Cache-TTL 归档按会话、用户、工具、工具调用 ID、内容长度和内容哈希组成处理器内幂等键；运行时归档存储按会话、工具、原始内容哈希和原始字节数生成内容寻址路径，并在复用前校验 metadata 与归档 payload 哈希；无会话 ID 的匿名上下文不写入共享归档目录，失败结果不进入缓存
- 结构化阻断：恢复预算耗尽、整文件恢复需要范围读取或文件大小探测失败时返回 `archive_restore_blocked` payload，包含原因、估算 tokens、建议动作，并扁平输出 `reason_label_key`、`severity`、`primary_restore_arg`、`recommended_ranges`、`restore_range_hints`、`content_features`，同时记录 `ArchiveRestoreBlockEvent` 并通过结构化 `agent_status` 下发 GUI，便于 GUI 和上层 Agent 给出可执行恢复路径
- 类型契约：Prompt cache 使用反馈通过 `CacheUsageFeedback` 进入剪枝决策；归档写入通过 `ContextOffloadResult` 暴露成功路径和失败分类，避免框架层解析业务层自然语言错误
- 清理：会话结束通过 context-root guard 删除 session 文件并清理访问记录；后台任务每日自动清理过期文件（>7天）
- 监控：实时存储使用量跟踪（Prometheus metrics + 定期扫描）

**Pete 的关键洞察**：
> "例如，假设你有一个向文件写入的工具，它可能有两个字段：路径和内容。一旦工具执行完毕，你可以确保该文件已经存在于环境中。因此，在紧凑格式中，我们可以安全地去掉超长的内容字段，只保留路径。这样一来，没有任何信息真正丢失，只是被外部化了。"

#### 3.2.3 摘要 (Summarization) - 不可逆的最后手段

**定义**：当压缩后上下文**仍然过大**时，作为最后手段，使用 LLM 生成结构化摘要替换大部分历史消息。

**触发条件**：
```text
总上下文 >= 摘要阈值（如 150k tokens）
```

**摘要什么时候会触发？**

摘要不会"永远不触发"。关键在于**紧凑格式本身也占空间**（~150 tokens/个）：

| 工具调用数 | 紧凑格式累积 | 其他消息 | 总计 | 触发摘要？ |
|-----------|-------------|---------|------|----------|
| 100 | 15,000 | 20,000 | 35,000 | ❌ |
| 500 | 75,000 | 30,000 | 105,000 | ❌ |
| 1000 | 150,000 | 40,000 | 190,000 | ✅ |

当对话非常长（上千次工具调用）时，紧凑格式累积最终会超过摘要阈值，此时触发摘要。

**特点**：
- **被动触发** - 压缩不足时自动触发
- **不可逆** - 原始消息结构被替换，无法恢复
- **结构化** - 使用固定模式，非自由形式
- **保留最近调用** - 最近 N 次工具调用保持完整格式（few-shot 示例）

**为什么保留最近 N 次调用？**
> "保留几个完整的工具调用和结果示例非常有帮助。因为这能让模型知道它上次停在了哪里，从而更平滑地继续工作。否则，你会发现摘要之后，模型有时会改变其风格和语气。" —— Manus

**有损但可追溯策略**：

> "在进行摘要之前，我们可能会将上下文的关键部分卸载到文件中。有时，我们甚至会更激进，将整个摘要前的上下文转储为一个文本文件或日志文件，以便日后随时恢复。如果模型足够聪明，它甚至知道如何检索那些被摘要前的上下文。" —— Manus

工作流程：
1. **Offload（备份）**：将完整 Context 转储到文件系统
2. **Summarize（摘要）**：基于完整数据生成结构化摘要
3. **Replace（替换）**：Context 中只保留摘要 + 备份文件路径
4. **Restore（按需恢复）**：模型可用文件读取工具检索原始细节

**结构化摘要格式**：

```json
{
    "user_goal": "用户的最终目标",
    "completed_actions": ["已完成的操作1", "已完成的操作2"],
    "key_findings": ["关键发现1", "关键发现2"],
    "files_modified": ["修改的文件"],
    "last_action": "最后执行的操作"
}
```

**Pete 的关键洞察**：
> "不要使用自由形式的提示让 AI 生成所有内容，而是定义一个模式，就像一个有很多字段的表单，让 AI 去填写。如果你使用这种更结构化的模式，至少输出会比较稳定。"

#### 3.2.4 策略执行顺序

```text
工具返回结果
        │
        ├─ 子代理结果 > 阈值 → 隔离（Isolate）→ 存入文件 + 摘要返回
        │
        ├─ 单个结果 > 过滤阈值 → 过滤（Filtering）→ 存入文件 + 智能预览
        │
        └─ 正常添加到消息历史
                │
                ↓
每轮结束后检查
        │
        ├─ 总上下文 < 压缩阈值 → 正常运行
        │
        ├─ 压缩阈值 ~ 摘要阈值 → 压缩（Compression）
        │     │
        │     ├─ 压缩旧工具调用，保留最近 N 次完整
        │     │  仅当节省 > 最小节省阈值时执行
        │     │
        │     └─ 主动外部化的关键发现不受影响
        │
        └─ > 摘要阈值 → 摘要（Summarization）
              │
              ├─ 生成结构化摘要（不可逆）
              │
              ├─ files_modified 字段记录之前写入的文件路径
              │
              └─ 保留最近 N 次完整工具调用
```

---

### 3.3 隔离 (Isolate) - 子代理独立上下文

> 来自 Anthropic Multi-Agent 的上下文隔离策略

**定义**：通过子代理的**独立上下文窗口**，将探索时的开销分散到多个隔离的处理单元中。子代理的"过程噪音"不会污染主代理上下文。

**触发条件**：
```text
子代理结果 > 隔离阈值（如 2000 tokens）→ 触发隔离
```

**特点**：
- **独立上下文** - 子代理有自己的上下文窗口
- **结果卸载** - 完整研究结果写入文件系统
- **摘要返回** - 主代理只接收精炼摘要 + 文件引用
- **按需读取** - 主代理可通过文件路径读取完整内容

**隔离后的返回格式示例**：

```json
{
  "topic": "AI 技术最新动态",
  "summary": "精炼的研究摘要...",
  "key_points": ["要点1", "要点2", "..."],
  "_isolated": true,
  "_full_result_file": "/workspace/research_results/ai_技术_abc123.json",
  "_full_result_tokens": 8500,
  "_read_instruction": "Full research result (8500 tokens) saved to file..."
}
```

**设计理念**：
> "子代理可能累积数万 token 的过程噪音，但这些 token 被隔离在其独立上下文中——主代理只接收精炼后的结论。这类似于组织中的层级汇报：基层员工处理大量细节，向上级仅提交摘要和结论。"

## 4. Prompt Cache 优化策略

### 4.1 前缀匹配原理

#### LLM API 请求的序列化顺序

LLM provider 将请求体序列化为 prompt 时，各部分的**确定性顺序**为：

```text
┌────────────────────────────────────────┐
│  1. Tools 定义 (JSON Schema)           │  ← 最先序列化
│  2. System Prompt                      │
│  3. Messages (对话历史 + 用户查询)      │  ← 最后
└────────────────────────────────────────┘
```

**验证来源**：
- **Anthropic Claude**：官方文档明确 cache breakpoint 顺序为 `tools → system → messages`。开源项目 opencode PR #14743 验证了通过稳定 tools 排序 + 拆分 system prompt，缓存命中率从 0% 提升到 97.6%
- **OpenAI**：文档指出 "structured output schema serves as a prefix to the system message"，`tools` 与 `response_format` 同属于 system-level 前缀
- **Claude Code 团队实践**：Claude Code 工程师 Thariq 将 prompt caching 称为"整个产品围绕的架构约束"，cache hit rate 下降会触发 SEV

#### Token 级前缀匹配的精确语义

> "If tokens 1-499 haven't changed, their Keys and Values are still correct, even if token 500 is different. But if token 200 changes, the Keys and Values for tokens 201-499 are all wrong — because each of them was computed with token 200 as an input. **You have to recompute from token 200 onward.**"
> —— *How Prompt Caching Actually Works in Claude Code*, 2026-02-25

缓存匹配是**token 级别的前缀匹配**：从第一个 token 开始逐一比较，直到发现第一个不同的 token，该位置之前的所有 KV cache 保留，之后的全部重算。

**设计影响**：
- 修改 tools 定义 → **所有缓存失效**（位于最前）
- 修改 system prompt → tools 缓存保留，system prompt 中变化点之前的部分保留，之后的全部失效
- 修改 messages → tools + system prompt 缓存均保留
- **动态内容（如时间戳）应放在 messages 中**，而非 system prompt 或 tools 中

> **Claude Code 官方策略**：当信息过时（日期变化、文件修改）时，**不修改 system prompt**，而是将更新信息作为 `<system-reminder>` 标签放在下一条 user message 中。这确保 system prompt 前缀永远冻结，cache 始终命中。

#### 前缀匹配示例

```text
第一次调用:
[Tools][System Prompt][User Message 1][Tool Output 1][User Message 2]
                                                      ↑
                                              新增内容从这里开始

第二次调用:
[Tools][System Prompt][User Message 1][Tool Output 1][User Message 2][Tool Output 2]
└──────────────────────── 完全相同的前缀 ────────────────────────────┘
                                    ↓
                             可以复用缓存！
```

### 4.2 批量清理（积累-爆发模式）

> **设计理念**：减少缓存破坏频率，最大化 Prompt Cache 收益。

#### 问题背景：为什么需要批量清理？

**核心问题**：LLM 服务商（OpenAI、Anthropic）使用 **Prompt Cache** 缓存重复的上下文前缀：
- ✅ **缓存命中**：价格打 1 折（90% 折扣）
- ❌ **缓存失效**：支付原价

**传统渐进式清理的问题**：每次超过阈值就压缩，频繁破坏缓存

```text
渐进式清理（❌ 成本高）:
  轮 10: tokens=65k → 清理 → Cache 失效 → 支付原价 $0.01
  轮 15: tokens=65k → 清理 → Cache 失效 → 支付原价 $0.01
  轮 20: tokens=65k → 清理 → Cache 失效 → 支付原价 $0.01
  (3 次 Cache 失效，总成本：$0.05 = 5轮 × $0.01)

批量清理（✅ 成本低）:
  轮 10-14: 积累，不清理 → Cache 命中 → 支付折扣价 4轮 × $0.002
  轮 15: 批量清理 → Cache 失效 → 支付原价 $0.01
  (1 次 Cache 失效，总成本：$0.028 = $0.01 + $0.008 + $0.01)
  
节省：44%
```

#### 三阶段清理逻辑

系统使用**三个阈值**实现积累-爆发模式：

| 阈值 | 示例值 | 作用 | 行为 |
|-----|--------|------|------|
| **压缩阈值** | 60k | 积累起点 | 开始积累轮数 |
| **强制压缩阈值** | 120k | 安全阀 | 强制立即清理 |
| **积累上限** | 5 轮 | 积累上限 | 达到后批量清理 |

**详细工作流程**：

```text
阶段 1: tokens < 压缩阈值
  ✅ 正常运行，不压缩
  ✅ 重置积累轮数

阶段 2: 压缩阈值 <= tokens < 强制压缩阈值 (积累模式)
  ⏳ 积累轮数 +1
  
  if 积累轮数 >= 5:
    📦 触发批量清理
    重置积累轮数 = 0
  else:
    ⏸️ 继续积累，本轮不压缩

阶段 3: tokens >= 强制压缩阈值 (强制模式)
  🚨 立即强制清理！（无视积累轮数）
  重置积累轮数 = 0
  
  作用：安全阀，防止上下文爆炸
  - 如果一直积累不清理，可能超过模型上下文限制
  - 强制压缩阈值确保即使积累期间也有兜底保护
```

#### 成本效果对比

假设每轮 LLM 调用基础成本 $0.01，缓存命中折扣 90%：

| 策略 | 轮次 | 缓存状态 | 单轮成本 | 总成本 |
|-----|------|---------|---------|--------|
| **渐进式** | 1-5 | 每轮失效 | $0.01 × 5 | **$0.05** |
| **批量式** | 1 | 建立缓存 | $0.01 | |
| | 2-5 | 命中缓存 | $0.002 × 4 | |
| | 6 | 批量清理 | $0.01 | **$0.028** |

**节省比例**：(0.05 - 0.028) / 0.05 = **44%**

### 4.3 工具定义管理：分层 + Logits Masking

> 来自 Manus Context Engineering

**问题**：工具列表动态变化会破坏缓存前缀。工具定义位于上下文前部，任何更改都会使后续所有内容的 KV 缓存失效。此外，当先前的动作引用了已移除的工具时，模型会产生困惑。

**解决方案**：双管齐下——**分层排序** + **Logits Masking**。

#### Logits Masking：运行时动态控制

使用 **Logits Masking**（解码时遮蔽 token 概率）来控制工具可用性，而非修改工具定义：

```text
工具定义: [browser_click, browser_type, shell_exec, web_search, ...]
          └─────────────────────────────────────────────────────────┘
                              始终保持不变！

Logits Masking（解码阶段）:
  - 当前状态需要浏览器操作 → 只允许 browser_* 前缀的 token
  - 用户刚输入新消息 → 强制选择 reply 动作
  - 需要执行命令 → 只允许 shell_* 前缀的 token
```

**响应预填充技巧**（以 Hermes 格式为例）：

| 模式 | 预填充内容 | 效果 |
|------|-----------|------|
| 自动 | `<\|im_start\|>assistant` | 模型自由选择是否调用函数 |
| 必需 | `<\|im_start\|>assistant<tool_call>` | 必须调用函数，但不限制哪个 |
| 指定 | `<\|im_start\|>assistant<tool_call>{"name": "browser_` | 只能调用 browser_* 工具 |

**关键设计**：工具命名使用一致前缀（`browser_*`、`shell_*`、`web_*`）便于分组控制。

> **注意**：Logits Masking 和响应预填充仅适用于自托管模型。商业 API 不支持这些特性。

#### 工具分层：编译时静态优化

将工具按稳定性分层排序，稳定的放前面，动态的放后面：

1. **保护核心前缀稳定性**：通过分层排序（CORE > COMMON > EXTENDED），修改靠后的工具只会破坏其后方的缓存，靠前的核心工具缓存仍然有效。

2. **确定性的变动溢出区**：对于不可避免的动态变动（如按需加载的技能），将其排在最后，确保前方核心前缀能命中缓存。

#### 层级定义

| 层级 | 稳定性 | 变化频率 | 缓存价值 | 工具示例 |
|------|--------|---------|---------|---------|
| **CORE** | 极高 | 几乎不变 | 最高 | `web_fetch_tool` |
| **COMMON** | 高 | 很少变 | 高 | `bash_code_execute_tool`, `file_read_tool`, `file_write_tool`, `file_edit_tool`, `planner_tool`, `web_search_tool`, `request_answer_user_tool` |
| **EXTENDED** | 中 | 偶尔变 | 中 | `skill_select_tool`, `memory_recall_tool`, 浏览器/MCP 动态工具 |

#### 分层结构示例

```text
[System Prompt]           ← 完全稳定，永远缓存
[Layer 1: CORE 工具定义]   ← 高度稳定 (web_fetch_tool)
[Layer 2: COMMON 工具定义] ← 相对稳定 (bash/file/planner/web_search/request_answer_user)
[Layer 3: EXTENDED 工具]   ← 易变区 (skill/memory/browser/MCP 等)
[对话历史]                 ← 增量增长
```

#### 效果

```text
第 1 轮: [System][CORE: web_fetch][COMMON: bash,file_*,planner,web_search,request_answer_user][EXTENDED: skill_select][History 1]
第 2 轮: [System][CORE: web_fetch][COMMON: bash,file_*,planner,web_search,request_answer_user][EXTENDED: memory_recall][History 1-2]
                 |<----- 这部分可缓存 ----->|

虽然 EXTENDED 工具变了，但：
- System Prompt + CORE 工具部分仍然命中缓存
- 只有 EXTENDED 及之后需要重新计算
```

### 4.4 避免 Prompt 顺序陷阱

```python
# ❌ 错误：动态内容放在前面
[RAG Context] + [System Prompt] + [User Question]
# 后果：即使 System Prompt 一个字没改，也无法命中缓存！
# 原因：前缀缓存要求"从头开始的连续一致性"

# ✅ 正确：静态内容放在前面
[System Prompt] + [Tool Definitions] + [RAG Context] + [User Question]
# 效果：System Prompt + Tools 部分命中缓存
```

### 4.5 Manus 三个关键实践

**1. 保持提示前缀稳定**

> "由于 LLM 的自回归特性，即使是单个 token 的差异也会使该 token 之后的缓存失效。一个常见的错误是在系统提示的开头包含时间戳。"

**2. 使上下文只追加**

> "避免修改之前的操作或观察。确保你的序列化是确定性的。许多编程语言和库在序列化 JSON 对象时不保证键顺序的稳定性。"

**3. 明确标记缓存断点**

> "某些模型提供商或推理框架不支持自动增量前缀缓存，而是需要在上下文中手动插入缓存断点。"

### 4.6 提升缓存命中率的通用原则

**核心原则**：将重复内容置于提示词开头，差异内容置于末尾。

```text
✅ 缓存 "ABCD" 后，请求 "ABE" → 可能命中 "AB"
❌ 缓存 "ABCD" 后，请求 "BCD" → 无法命中（前缀不匹配）
```

**典型高命中场景**：
- **多轮对话**：每轮对话的 messages 数组天然是前缀追加
- **长文本问答**：相同文档 + 不同问题
- **角色扮演/Few-shot**：相同 System Prompt + 不同 User Message

### 4.7 缓存断点策略（Anthropic 最佳实践）

> 参考：
> - [Anthropic 官方文档](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
> - [Anthropic Cookbook](https://platform.claude.com/cookbook/misc-prompt-caching)

#### 增量缓存原理

**增量缓存原理**（官方文档原文）：

> "The system will automatically lookup and use the longest previously cached sequence of blocks for follow-up messages. That is, blocks that were previously marked with cache_control are later not marked with this, but they will still be considered a cache hit."

**关键理解**：
- ✅ **不需要重复标记**：系统自动向前查找之前缓存的内容
- ✅ **增量累积**：每轮只需为新增内容支付 125%，匹配部分只需 5%
- ✅ **20-block Lookback Window**：系统最多向前查找 20 个 content blocks

#### 推荐断点位置

```text
断点位置 = {
    1. System 后（必须）              # 缓存系统提示词
    2. 每 15 blocks（自动）           # 防止超出 20-block lookback window
    3. 压缩边界后（按需）             # 保护压缩内容
    4. 最后一条消息（必须）           # 增量对话缓存（官方推荐）
}
```

#### 智能断点保留

**问题**：Anthropic/阿里云限制最多 4 个断点。当对话超过 **45 条消息**时，会生成超过 4 个断点。

**解决方案**：智能保留策略，确保核心断点永远保留。

```text
# 场景：75 条消息，生成 6 个断点
预计断点: [0:System, 16, 32, 48, 64, 74:最后]

# 智能保留（最多 4 个）
实际断点: [0:System, 16, 32, 74:最后]  ✅
          └────必须保留────┘  └──必须保留──┘
```

**保留规则**：
1. ✅ **第一个（System）**：永远保留 → 缓存系统提示词
2. ✅ **最后一个（最后消息）**：永远保留 → 增量缓存核心（官方推荐）
3. ✅ **中间 N 个（保护断点）**：保留前 `max_breakpoints - 2` 个 → 防止超出 20-block lookback

**设计理由**：
- 🎯 **最后消息最重要**：丢失会失去增量缓存能力，成本节省从 68% → 0%
- 🎯 **System 也重要**：缓存系统提示词，通常占 tokens 的 30-50%
- 🎯 **中间断点可取舍**：优先保护前半部分对话，确保不超出 lookback window

#### 性能数据

**成本节省**（9 轮对话）：

| 轮次 | 增量缓存方案 | 无缓存方案 | 节省 |
|------|---------|--------|------|
| 1 | 1,562.5 | 1,500 | - |
| 2 | 687.5 | 800 | 14% |
| 3 | 712.5 | 1,300 | 45% |
| 9 | 862.5 | 4,300 | 80% |
| **总计** | **7,062** | **22,000** | **68%** ✅ |

**延迟降低**（官方 Benchmark，187K tokens）：

| 场景 | 非缓存 | 第1次缓存 | 第2次缓存 | 加速 |
|------|--------|-----------|-----------|------|
| 单轮 | 6.86s | 5.96s | 3.66s | **1.9x** ✅ |

---

## 5. 成本分析与决策模型

### 5.1 上下文工程 vs 前缀缓存

> **核心问题**：如何衡量上下文工程缩减带来的 token 节省，与缓存带来的费用折扣？

这是 **"数量减少（上下文工程）"** vs **"单价打折（前缀缓存）"** 之间的博弈。

**定义两个核心变量**：
- `R_comp`（压缩率）：上下文工程把 Token 数量减少了多少。例如压缩 50%，`R_comp = 0.5`
- `D_cache`（缓存折扣率）：命中缓存后的价格是原价的多少。例如 DeepSeek/Claude 命中缓存后价格是原价的 10%，则 `D_cache = 0.1`

```text
上下文工程的成本 = Input_orig × (1 - R_comp) × Price_base
前缀缓存的成本   = Input_orig × D_cache × Price_base

盈亏平衡点：当 (1 - R_comp) = D_cache 时两者相等
```

**结论**：如果不考虑质量损失，**前缀缓存通常完胜**。

目前主流厂商（DeepSeek, Anthropic）的缓存命中价格仅为 **1/10 (10%)**。这意味着：
- 除非上下文工程能把 1000 个字压缩成 100 个字（**90% 压缩率**），否则单纯从省钱角度看，不如直接用缓存
- 而 90% 的压缩率通常会**严重丢失信息**，导致模型变笨

### 5.2 压缩决策公式

**变量定义**：
- `T_cleared` = 压缩清理的 token 数
- `T_prefix` = 被破坏的缓存前缀长度
- `P` = Prompt Cache 命中时的折扣率（Anthropic: 90%，OpenAI: 50%）

```text
执行压缩当且仅当：
    T_cleared > T_prefix × (1 - P)

对于 Anthropic (P = 90%):  T_cleared > T_prefix / 10
对于 OpenAI (P = 50%):     T_cleared > T_prefix / 2
```

**简化实现建议**：

完整公式需要实时追踪 `T_prefix`（被破坏的缓存前缀），实现复杂。实践中可使用固定阈值（如 3000 tokens，假设 `T_prefix=30k`，按 90% 折扣估算）作为 `compress_min_save`。

**示例**：

| 场景 | 前缀长度 | 清理量 | Anthropic 决策 | OpenAI 决策 |
|------|----------|--------|----------------|-------------|
| 小清理 | 30k | 2k | ❌ 不执行 (2k < 3k) | ❌ 不执行 (2k < 15k) |
| 中等清理 | 30k | 5k | ✅ 执行 (5k > 3k) | ❌ 不执行 (5k < 15k) |
| 大清理 | 30k | 20k | ✅ 执行 (20k > 3k) | ✅ 执行 (20k > 15k) |

### 5.3 场景化决策模型

#### 场景 A：静态长文本

**特征**：系统设定、知识库、Few-Shot 示例。内容几周变一次，或者对所有用户都一样。

**策略**：🔴 **死磕前缀缓存，不要压缩**

**原因**：
- 缓存命中能打 1 折，且保留 100% 精度
- 如果去压缩它，不仅丢失细节，而且压缩算法导致每次输出微小差异，反而让缓存失效，两头亏

#### 场景 B：动态长历史

**特征**：用户聊了 50 轮。内容每轮都在变（Append），且越来越长。

**策略**：🟡 **必须用上下文工程（滑动窗口/摘要）**

**原因**：
- 虽然头部相同能命中部分缓存，但随着总长度逼近模型窗口上限（200k），物理塞不进去是首要矛盾
- 此时省钱是次要的，不报错才是主要的

**高级技巧**：使用"分段摘要"。把前 10 轮总结成固定 Summary，把这个 Summary 当作新的 Prefix 缓存起来。

#### 场景 C：RAG（检索增强生成）

**特征**：每次根据问题去向量库里捞出不同的片段。

**策略**：🟢 **混合策略 - 前缀缓存 + 上下文工程**

**关键洞察**：System Prompt 可以缓存！即使检索内容每次不同。

**"前缀厚度"策略** - 让 System Prompt 变"厚"：
- 加入 10-20 个高质量 Few-Shot 示例 → 前缀从 500 → 3000 tokens
- 把复杂的输出格式/合规规则写在前面
- 缓存收益从 5% 提升到 30-50%

### 5.4 场景化配置建议

| 场景 | 特点 | `compress_min_save` 建议值 | 原因 |
|------|------|------------------------|------|
| **短对话（<10轮）** | 剩余轮数少，缓存价值高 | 10k+ tokens | 保守，保持缓存 |
| **长对话（>30轮）** | 剩余轮数多，节省效果累积 | 2-3k tokens | 激进，频繁清理 |
| **研究任务** | 大量工具调用，上下文增长快 | 5k tokens | 配合批量清理 |
| **实时交互** | 低延迟优先 | 8k+ tokens | 避免缓存失效延迟 |
| **后台任务** | 成本优先 | 2k tokens | 最大化节省 |

## 6. 各模型提供商对比

### 6.1 机制对比

| 提供商 | 机制类型 | 触发方式 | 折扣率 | 缓存写入成本 | TTL | 最小缓存长度 |
|--------|----------|----------|--------|--------------|-----|--------------|
| **Anthropic** | 显式 + 自动 | 自动 + `cache_control` | 90% | 原价 25% | 5分钟/1小时 | 1024-4096 tokens |
| **OpenAI** | 纯自动 | 完全自动 | 50% | 无 | 5-10 分钟 | 1024 tokens |
| **Google** | 显式 + 隐式 | 显式接口 + 自动匹配 | 75% | $1/M tokens/小时 | 1小时-1天 | 32k(显式) / 1k(隐式) |
| **阿里云** | 隐式 + 显式 | 自动 + `cache_control` | 80%/90% | 隐式无/显式125% | 不确定/5分钟 | 256(隐式) / 1024(显式) |
| **DeepSeek** | 纯自动 | 完全自动 | ~90% | 无 | 动态 | 64 tokens |

### 6.2 各提供商详解

#### Anthropic (Claude)

> **⚠️ 关键发现**：Claude 的缓存**并非 100% 保证命中**，存在以下限制：

1. **精确匹配要求**：缓存命中需要 **100% 相同**的提示词段，包括所有文本和图像的**字节级一致**
2. **20 块回溯窗口**：系统仅检查每个显式 `cache_control` 断点之前的**最多 20 个块**。如果修改发生在 20 个块之外，将**无法命中缓存**
3. **并发请求限制**：缓存条目仅在**第一个响应开始后**才可用。并行请求可能无法命中刚创建的缓存
4. **组织隔离**：缓存在组织之间隔离，不同组织永远不会共享缓存

**最小缓存长度要求（按模型）**：

| 模型 | 最小缓存长度 |
|------|-------------|
| Claude Opus 4.5 | 4096 tokens |
| Claude Opus 4.x / Sonnet 4.x | 1024 tokens |
| Claude Haiku 4.5 | 4096 tokens |
| Claude Haiku 3.x | 2048 tokens |

**缓存失效因素**（优先级从高到低）：

| 变更类型 | 工具缓存 | 系统缓存 | 消息缓存 | 影响范围 |
|---------|---------|---------|---------|---------|
| 工具定义修改 | ❌ | ❌ | ❌ | 全部失效 |
| 网络搜索/引用切换 | ✅ | ❌ | ❌ | 系统+消息失效 |
| `tool_choice` 参数变化 | ✅ | ✅ | ❌ | 消息失效 |
| 图像添加/删除 | ✅ | ✅ | ❌ | 消息失效 |
| 思考参数变化 | ✅ | ✅ | ❌ | 消息失效 |

**TTL 选项**：
- **5 分钟缓存**：默认，写入成本为基础价格的 1.25 倍
- **1 小时缓存**：需额外付费，写入成本为基础价格的 2 倍

#### Google (Gemini)

- **显式缓存 (Context Caching)**：最小缓存长度 32k tokens（门槛较高），适合超大长文档或代码库缓存，需要支付存储成本。
- **隐式缓存 (Implicit Caching)**：Gemini 1.5 Flash/Pro 支持**自动前缀匹配 (Automatic Prefix Matching)**。当 Prompt 头部稳定且重复时，后端会自动缓存。

#### 阿里云（通义千问）

> 参考：[阿里云 Context Cache 文档](https://help.aliyun.com/zh/model-studio/context-cache)

**⚠️ 关键发现**：隐式缓存与显式缓存**互斥**，单个请求只能应用其中一种模式。

**隐式缓存**（自动模式）：
- **触发方式**：自动开启，无法关闭
- **命中概率**：**不确定**，由系统判定（即使请求上下文完全一致，仍可能未命中）
- **计费**：命中部分按输入 Token 单价的 **20%** 计费
- **最小缓存长度**：256 tokens
- **TTL**：不确定，系统定期清理长期未使用的缓存

**显式缓存**（主动模式）：
- **触发方式**：在 messages 中加入 `"cache_control": {"type": "ephemeral"}` 标记
- **命中概率**：**确定性命中**
- **计费**：
  - 创建缓存：输入 Token 单价的 **125%**
  - 命中缓存：输入 Token 单价的 **10%**
- **最小缓存长度**：1024 tokens
- **TTL**：5 分钟（命中后重置）
- **限制**：
  - 单次请求最多 **4 个缓存标记**
  - 系统从 `cache_control` 标记位置向前回溯最多 **20 个 content 块**

**支持的模型**（隐式缓存）：
- qwen3-max、qwen-max、qwen-plus、qwen-flash、qwen-turbo
- qwen3-coder-plus、qwen3-coder-flash
- qwen3-vl-plus、qwen3-vl-flash、qwen-vl-max、qwen-vl-plus

#### DeepSeek

- 最小缓存长度仅 64 tokens
- 对代码补全有额外优化

### 6.3 统一策略

**好消息：不需要为每个模型单独配置策略！**

所有提供商都基于相同的核心机制——**前缀匹配**：

```text
前缀相同 → 缓存命中 → 享受折扣
前缀变化 → 缓存失效 → 支付原价
```

这意味着优化策略**对所有模型都有效**：
1. ✅ 遮罩而非移除
2. ✅ 工具定义分层
3. ✅ 批量清理
4. ✅ 保护前缀

---

## 7. 最佳实践

### 7.1 System Prompt 设计

```python
# ✅ 好的设计：核心内容稳定
SYSTEM_PROMPT = """
你是一个专业的 AI 助手。

## 核心规则
1. 规则 1
2. 规则 2
...
"""

# ❌ 不好的设计：每次调用都变化
SYSTEM_PROMPT = f"""
你是一个专业的 AI 助手。
当前时间：{datetime.now()}  # 每次都变，破坏缓存！
...
"""
```

**解决方案**：动态信息放在用户消息中，而不是 System Prompt 中。

### 7.2 工具定义顺序

```python
# ✅ 好的设计：常用工具放前面
tools = [
    web_search_tool,      # 常用，放前面
    read_file_tool,       # 常用，放前面
    ...
    rare_tool_1,          # 少用，放后面
    rare_tool_2,          # 少用，放后面
]
```

### 7.3 动态信息注入位置

由于序列化顺序为 `tools → system_prompt → messages`（见 §4.1），**任何每次请求都会变化的内容必须放在 messages 中**，才不会破坏 tools 和 system_prompt 的缓存前缀。

> **Claude Code 官方做法**：日期、git status、打开的文件内容等动态信息，一律通过 `<system-reminder>` 标签放在 user message 中，**绝不修改 system prompt**。这是他们缓存策略的核心。

**注意**：即使把动态内容放在 system_prompt 的**末尾**，前缀匹配是 token 级别的，system_prompt 中变化点**之前**的内容仍能缓存命中（见 §4.1 精确语义）。但这与放在 messages 中的缓存效果差异极小（仅差动态内容本身的 tokens 数），且违反了 system_prompt 冻结的架构原则。

```python
# ❌ 不推荐：System Prompt 中放动态内容
system = f"当前时间：{now}\n你是 AI 助手..."

# ✅ 推荐：动态内容放在 messages 中（Claude Code 官方策略）
system = "你是 AI 助手。动态上下文会在对话中提供。"

messages = [
    SystemMessage(content=system),  # 冻结的前缀，永远不改
    # 时间戳等动态内容作为 message 注入
    HumanMessage(content=f"""
    <system-reminder>
    当前时间：{now}
    </system-reminder>

    {user_query}
    """),
]
```

### 7.4 监控与调优

关注以下核心指标：
- **KV Cache 命中率**：最重要的单一指标
- **Context Editing 触发频率**：过于频繁说明阈值设置不合理
- **每次节省的 token 数**：评估压缩效果
- **Tokens-per-Task**：任务级 token 消耗，而非单次请求

> "传统压缩指标优化的是 tokens-per-request。正确的指标是 **tokens-per-task**。" —— Factory Research

### 7.5 缓存层策略清单

| 策略 | 说明 |
|------|------|
| **遮罩而非移除** | 保持消息结构稳定，压缩时用紧凑格式替换而非删除 |
| **compress_min_save 阈值** | 小清理不值得破坏缓存 |
| **时间信息放末尾** | 动态时间放在 HumanMessage 末尾，不放 System Prompt |
| **System Prompt 稳定** | 静态核心 + 动态信息注入到 HumanMessage |
| **工具名称规范化** | 使用一致前缀（`browser_*`、`file_*`）便于分组控制 |
| **工具定义分层** | CORE > COMMON > EXTENDED，稳定的放前面 |
| **批量清理策略** | 积累-爆发模式，减少缓存破坏频率 |
| **显式缓存标记** | 在关键位置设置 `cache_control` 断点（Anthropic/阿里云） |

### 7.6 准确率层策略（自托管模型适用）

| 策略 | 适用范围 | 说明 |
|------|---------|------|
| **约束解码（Logits Masking）** | 自托管模型 | 商业 API 不暴露 Logits 接口 |
| **响应预填充** | Claude / 自托管模型 | 强制模型以特定格式开始响应 |
| **上下文感知状态机** | 自托管模型 | 依赖约束解码机制 |

---

## 8. 设计原则

> 本节整合从 Anthropic 官方文章、Factory Research 和 Agent-Skills-for-Context-Engineering 项目中提炼的设计原则。

### 8.1 核心设计原则

#### Right Altitude 原则（系统提示词设计）

> 来源：Anthropic 官方文章

| 极端 | 问题 | 正确做法 |
|------|------|---------|
| 过度具体 | 硬编码复杂脆弱逻辑 | 足够具体以有效引导行为 |
| 过度模糊 | 缺乏具体信号 | 又足够灵活以提供强启发式 |

#### 工具设计三原则

> 来源：Anthropic 官方文章 + Agent-Skills 项目

1. **自包含**：功能完整，不依赖其他工具的隐式状态
2. **健壮**：对错误有清晰的恢复指导
3. **明确**：描述回答"做什么"、"何时用"、"返回什么"

**核心判断标准**：
> "如果人类工程师无法确定用哪个工具，AI Agent 也做不到。"

#### 工具整合原则（Consolidation Principle）

> 来源：Agent-Skills 项目

与其实现多个细粒度工具，不如实现综合工具处理完整工作流：
- 减少工具描述 token 消耗
- 消除工具选择歧义
- 降低工具选择复杂度

#### 混合检索策略（Claude Code 模式）

> 来源：Anthropic 官方文章

| 策略 | 适用场景 | 示例 |
|------|---------|------|
| **预加载** | 稳定内容 | System Prompt、技能定义 |
| **自主探索** | 动态内容 | `bash_code_execute_tool`、`file_read_tool`、`grep_tool` |

**优势**：避免过时索引和复杂语法树的问题。

#### 架构精简原则（Architectural Reduction）

> 来源：Agent-Skills 项目

**核心问题**：你的工具是在**启用**能力，还是在**限制**推理？

- 模型改进速度快于工具演进
- 为当前模型优化的复杂架构可能限制未来模型的能力
- 优先构建能从模型改进中获益的最小架构

### 8.2 上下文退化五种模式

> 来源：Agent-Skills 项目

| 模式 | 定义 | 缓解策略 |
|------|------|---------|
| **Lost-in-Middle** | 上下文中部信息注意力降低 | 关键信息放开头/结尾（U 型注意力曲线） |
| **Context Poisoning** | 错误信息复合放大 | 工具结果验证、规则检测 |
| **Context Distraction** | 无关信息占用注意力 | 过滤无关内容 |
| **Context Confusion** | 无法判断适用上下文 | 任务分割、子代理隔离 |
| **Context Clash** | 累积信息冲突 | 版本管理、时间戳标记 |

### 8.3 关键技术

#### Forward Message 模式

> 来源：LangGraph benchmark / Agent-Skills 项目

> "Supervisor 架构因'电话游戏'问题导致性能下降 50%。"

**解决方案**：让子代理直接传递响应给用户，而非经过主 Agent 转述。通过标记（如 `_forward_directly: true`）让子代理的响应直接透传。

#### Artifact Trail 独立跟踪

> 来源：Factory Research

> "所有压缩方法的 Artifact Trail 得分都很低（2.2-2.5/5.0）。需要独立的 artifact 索引，或在 Agent 脚手架中显式跟踪文件状态。"

**解决方案**：
1. 正常对话：后台静默追踪文件操作，不写入上下文
2. 摘要压缩时：将 Artifact 索引注入到摘要消息中
3. 效果：即使原始工具调用被压缩，Agent 仍能追踪到创建/修改的文件

#### 锚定增量摘要 (Anchored Iterative Summarization)

> 来源：Factory Research

> "Factory 的关键区别是更新机制：每次压缩只处理新截断的内容，然后**增量合并**到持久摘要中。"

**问题**：全量重新生成摘要会导致信息漂移，多次压缩后早期信息逐渐丢失。

**解决方案**：
- 首次摘要：完整生成新摘要
- 增量合并：将新内容合并到已有摘要，保留所有重要信息
- 合并质量监控：对比合并前后的信息数量，检测信息丢失

**效果**：核心信息始终锚定在摘要中，避免多次压缩后的信息漂移。

#### Lost-in-Middle 感知放置

> 来源：Agent-Skills 项目 / 论文 "Lost in the Middle"

> "将关键信息放在上下文的开头或结尾，因为模型对这些位置的注意力更高（U 型注意力曲线）。"

**问题**：Transformer 对上下文中部信息的注意力较低
- 开头/结尾：回忆准确率 ~80%
- 中间：回忆准确率 ~50%

**建议的信息排列**：
```text
开头（高注意力）：🎯 用户目标 + 📍 最后操作
中间（低注意力）：已完成操作 + 文件索引 + 历史日志路径
结尾（高注意力）：💡 关键发现
```

---

## 9. 参考资料

### 官方文档
- [Anthropic Prompt Caching](https://platform.claude.com/docs/build-with-claude/prompt-caching) - Claude 官方最新文档
- [Anthropic Effective Context Engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) - Anthropic 官方上下文工程指南
- [OpenAI Prompt Caching](https://platform.openai.com/docs/guides/prompt-caching)
- [阿里云 Context Cache 文档](https://help.aliyun.com/zh/model-studio/context-cache)
- [Google Gemini 上下文缓存 文档](https://ai.google.dev/gemini-api/docs/caching?hl=zh-cn&lang=python#explicit-caching)

### Manus 实战经验
- [Manus Context Engineering (英文)](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)
- [上下文工程才是AI应用的护城河 | Manus首席科学家季逸超万字对话实录](https://mp.weixin.qq.com/s?__biz=Mzg2NzY0MTkzOQ==&mid=2247493844)
- [Context Engineering for AI Agents with LangChain and Manus](https://www.bestblogs.dev/video/087a1f3)
- [Just-in-Time Context](https://mp.weixin.qq.com/s/vQisnurhpJNowJmchp7ZzA)

### Claude Code 实战经验
- [How Prompt Caching Actually Works in Claude Code](https://www.claudecodecamp.com/p/how-prompt-caching-actually-works-in-claude-code) - 2026-02-25，基于 API 实验验证的深度分析，引用 Claude Code 工程师 Thariq 的 7 条架构原则
- [opencode PR #14743: improve Anthropic prompt cache hit rate](https://github.com/anomalyco/opencode/pull/14743) - 通过稳定 tools 排序 + system prompt 拆分，缓存命中率从 0% → 97.6%
- [I Tested LLM Prompt Caching With Anthropic and OpenAI](https://mcginniscommawill.com/posts/2025-11-17-llm-prompt-caching-comparison/) - 实测对比 Anthropic 和 OpenAI 的缓存行为

### 开源项目与研究
- [Agent-Skills-for-Context-Engineering](https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering) - 上下文工程 Skills 集合
- [Factory Research: Evaluating Context Compression](https://factory.ai/blog/evaluating-context-compression) - 压缩质量评估框架
- [LangChain Blog: How agents can use filesystems for context engineering](https://blog.langchain.com/how-agents-can-use-filesystems-for-context-engineering/)
- [Multi-Agent 小白入门：让你的 Claude Code 提效 90.2%](https://x.com/YukerX/status/2013094122656334136)
