# auto_consolidation/

## 架构概述

闲置自适应与预算门禁会话记忆沉淀引擎套件（Idle & Budget Gated Auto-Memory Engine Suite · Item 123 P1 · 对标 CodeX 自动化记忆双门禁实践与六维切片规范）。

### 核心机制
1. **会话闲置自适应触发（Session Idle-Timeout Trigger）**：
   - 摆脱传统的“仅当会话关闭或新开会话才运行”的死板时机；
   - 监听会话非活动闲置窗口（默认 15 分钟），由后台低优先级协程自适应唤醒并评估是否触发会话总结与记忆抽取。
2. **双重工业级准入门禁（Turn Count & Token Budget Gate）**：
   - **门禁 1: 短对话轻量跳过与信息增益门禁（Turn & Info Gain Gate）**：有效对话少于 3 轮或词汇信息熵/密度低于阈值（如“好的”、“在吗”等废话）时直接拦截，杜绝产生垃圾碎片污染长期记忆库；
   - **门禁 2: Token 额度与预算保护门禁（Budget & Quota Safety Gate）**：检测剩余 Token 配额；若低于保护底线或预计提炼成本占剩余额度比例超过安全上限（默认 25%），自动安全挂起，杜绝反客为主造成用户账单超支。
3. **六维结构化记忆归档（Six-Dimensional Structured Artifact）**：
   - 结构化沉淀六大核心维度：
     ① 工作目录环境（Working Directory Context）；
     ② 关键主题词（Key Technical Topics）；
     ③ 用户个性偏好（User Preferences & Style）；
     ④ 可复用领域经验（Reusable Domain Knowledge）；
     ⑤ 失败教训反思（Failure Lessons & Pitfalls）；
     ⑥ 工具调用习惯（Tool Calling Patterns）。

## 文件清单

| 文件 | 角色 | 职责 | I/O/P |
| --- | --- | --- | --- |
| `models.py` | 实体模型 | 定义 AutoMemoryGatingConfig, TurnGatingDecision, BudgetGatingDecision, IdleDetectionState, OverallGatingReport, SixDimensionalMemoryArtifact | ✅ |
| `gating_engine.py` | 门禁引擎 | 闲置状态判定、轮数/信息增益双重校验、Token 预算保护与复合决策生成 | ✅ |
| `six_dimensional_extractor.py` | 抽取引擎 | 从对话消息与工具调用序列中归纳提炼六维高价值结构化记忆切片 | ✅ |
| `orchestrator.py` | 调度门面 | 聚合门禁评估与自适应抽取流程，提供统一运行时入口 | ✅ |
| `__init__.py` | 包门面 | 导出公共类型、核心类与门禁判定函数 | — |

## 依赖关系

- 依赖标准库与 `pydantic`
- 被 `myrm-agent-server/app/services/memory/` 业务层消费
