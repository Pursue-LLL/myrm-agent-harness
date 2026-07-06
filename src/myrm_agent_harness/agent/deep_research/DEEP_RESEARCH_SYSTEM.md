# Deep Research System Design

> 多阶段深度研究编排器。规划 → 澄清（可选）→ 并行 research agents → 报告合成。

---

## 设计目标

1. **阶段化编排**：orchestrator 驱动主事件循环，阶段实现分离在 mixin
2. **结构化澄清**：复用 `meta_tools/clarification/` 的 ask_question 能力
3. **并行研究**：多 research agent 分派，结果聚合为最终报告
4. **编排信号**：orchestrator 通过 `agent/orchestration/signals/deep_research.py` 注入 3 个 JSON schema（非 Action Tool）

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
| `../orchestration/signals/deep_research.py` | Orchestrator 用 3 个编排信号 schema |
| `helpers.py` | 无状态辅助函数（从 orchestrator 抽出） |

---

## 与 meta_tools/clarification 边界

- **deep_research/** — 多阶段研究产品流程
- **meta_tools/clarification/** — 可复用 HITL 澄清工具（Deep Research 消费方之一）

---

## Callback 机制

Orchestrator 支持 4 个可选回调，由业务层注入：

| Callback | 触发时机 | 签名 |
|----------|----------|------|
| `on_clarify` | CLARIFY 阶段需要用户输入 | `(AskQuestionInput) -> ClarificationAnswer \| None` |
| `on_plan_ready` | 研究计划生成后 | `(str) -> str \| None` |
| `on_cycle_complete` | 每个研究循环结束 | `(int, list[dict]) -> PhaseGuidance \| None` |
| `on_report_ready` | 最终报告生成成功后 | `(DeepResearchResult) -> None` |

`on_report_ready` 仅在 `result.report` 非空且无 error 时触发（在 `finally` 块中），
用于后处理如 wiki 入库、通知等。回调失败不影响研究结果。

---

## 扩展指南

1. 新阶段 → `_orchestrator_phases.py` mixin 方法 + prompts
2. 公开 API 仅通过 `deep_research/__init__.py` 导出
3. 更新 [deep_research/_ARCH.md](_ARCH.md)

---

## 参考资料

- [deep_research/_ARCH.md](_ARCH.md)
- [meta_tools/clarification/_ARCH.md](../meta_tools/clarification/_ARCH.md)
