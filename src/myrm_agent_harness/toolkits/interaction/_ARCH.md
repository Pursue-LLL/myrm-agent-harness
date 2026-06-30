
# Interaction Toolkit 架构与设计

## 架构概述

`Interaction Toolkit` 提供 Agent 与人类用户进行结构化交互（表单澄清等）的基础能力。
声明式 UI 渲染（`render_ui_tool`）在 harness `agent/meta_tools/interaction/`（依赖 artifact 上下文）。

LangChain 适配层遵循 `*_agent_tools.py` 约定：`interaction_agent_tools.py`。
Pydantic schema SSOT 在 `ask_question.py`。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|---|---|---|---|
| `__init__.py` | 核心 | 模块导出（schema + adapter） | ✅ |
| `ask_question.py` | 核心 | 结构化澄清表单 schema（AskQuestionInput / QuestionItem / OptionItem） | ✅ |
| `interaction_agent_tools.py` | 适配 | LangChain 工具：AskQuestionTool、create_ask_question_tool | ✅ |
