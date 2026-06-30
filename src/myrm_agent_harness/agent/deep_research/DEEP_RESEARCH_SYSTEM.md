# Deep Research System Design

> 多阶段深度研究编排器。规划 → 澄清（可选）→ 并行 research agents → 报告合成。

---

## 设计目标

1. **阶段化编排**：orchestrator 驱动主事件循环，阶段实现分离在 mixin
2. **结构化澄清**：复用 `meta_tools/clarification/` 的 ask_question 能力
3. **并行研究**：多 research agent 分派，结果聚合为最终报告
4. **元工具注入**：orchestrator LLM 上下文注入 3 个 fake/meta tools（`tools.py`）

---

## 系统架构

```
DeepResearchOrchestrator (orchestrator.py)
    │ inherits _OrchestratorPhasesMixin
    ▼
┌──────────────┬─────────────────┬──────────────┐
│ Clarification│ Research dispatch│ Report gen   │
│ (_phases)    │ (parallel agents)│ (_phases)    │
└──────────────┴─────────────────┴──────────────┘
         │                │
         ▼                ▼
   clarification/     sub_agents spawn
   (ask_question)     + meta_tools
```

---

## 核心文件

| 文件 | 职责 |
|------|------|
| `orchestrator.py` | 主事件循环、规划、并行研究调度 |
| `_orchestrator_phases.py` | 澄清 / research dispatch / 报告生成 mixin |
| `config.py` | 配置与类型定义 |
| `prompts.py` | 全阶段 prompt 模板 |
| `tools.py` | Orchestrator 用 3 个 meta tools |
| `helpers.py` | 无状态辅助函数（从 orchestrator 抽出） |

---

## 与 meta_tools/clarification 边界

- **deep_research/** — 多阶段研究产品流程
- **meta_tools/clarification/** — 可复用 HITL 澄清工具（Deep Research 消费方之一）

---

## 扩展指南

1. 新阶段 → `_orchestrator_phases.py` mixin 方法 + prompts
2. 公开 API 仅通过 `deep_research/__init__.py` 导出
3. 更新 [deep_research/_ARCH.md](_ARCH.md)

---

## 参考资料

- [deep_research/_ARCH.md](_ARCH.md)
- [meta_tools/clarification/_ARCH.md](../meta_tools/clarification/_ARCH.md)
