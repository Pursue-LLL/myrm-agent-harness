
# Interaction Toolkit 架构与设计

## 架构概述

`Interaction Toolkit` 提供 Agent 与人类用户进行结构化交互（表单澄清、UI 渲染、剪贴板等）的基础工具。该模块与具体的业务逻辑解耦，通过回调机制（Callback）或 UIArtifact 系统允许上层调用者注入自定义逻辑。

## 文件清单

| 文件 | 地位 | 职责 | I/O/P |
|---|---|---|---|
| `__init__.py` | 核心 | 模块导出 | ✅ |
| `ask_question.py` | 核心 | 定义交互式多题表单工具（`AskQuestionTool`）及其 Schema。支持多题、单选/多选、富文本选项及自由文本输入。 | ✅ |
| `clipboard_tools.py` | 核心 | 定义剪贴板工具（`write_to_clipboard`），通过客户端事件（Client Action）机制让智能体请求用户设备进行剪贴板写入。 | ✅ |
