# prompt_layered_authoring Architecture Documentation

## [POS]
所属模块：`myrm_agent_harness.agent.context_management.prompt_layered_authoring`
核心职责：用户提示词三层职责分层编辑引导与叙事文风预设模板套件，防范提示词腐化与选择性失明，实现硬规则/工作流路由/文风叙事三层职责分离与开箱即用叙事文风预设。

## 模块结构
| 文件 | 职责 |
|---|---|
| `layered_types.py` | 强类型契约、三层分区枚举、文风预设、草稿规范与腐化诊断结构定义 |
| `narrative_style_presets.py` | 内置叙事文风预设模板库与文风指令生成器（自然散文、工程严谨、高管简报等） |
| `prompt_corruption_detector.py` | 提示词职责纯净度与腐化检测器，识别工作流过度内联并生成技能沉淀建议 |
| `layered_prompt_assembler.py` | 三层职责提示词确定性组装器，渲染带层级标签的高信噪比系统指令块 |
| `prompt_layered_authoring_suite.py` | 统一协调门面 `UserProfilePromptLayeredAuthoringGuideAndNarrativeStylePresetSuite` |
| `__init__.py` | 包级公共符号门面导出 |
