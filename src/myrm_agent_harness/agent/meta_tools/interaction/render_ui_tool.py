"""Declarative UI rendering tool (A2UI).

[INPUT]
- langchain_core.tools::tool
- myrm_agent_harness.agent.artifacts::UIArtifact, get_ui_registry
- myrm_agent_harness.agent.artifacts.ui_artifact::UIAction, UIComponent, UIComponentType

[OUTPUT]
- render_ui_tool: LangChain tool that creates a UIArtifact from declarative JSON.

[POS]
Agent meta-tool emitting interactive UI via UIArtifact. Requires agent artifact context.
"""

import logging

from langchain_core.tools import tool

from myrm_agent_harness.agent.artifacts import UIArtifact, get_ui_registry
from myrm_agent_harness.agent.artifacts.ui_artifact import (
    UIAction,
    UIComponent,
    UIComponentType,
)

logger = logging.getLogger(__name__)


def render_ui(
    title: str,
    components: list[dict[str, object]],
    root_ids: list[str],
    data: dict[str, object] | None = None,
    actions: list[dict[str, object]] | None = None,
) -> str:
    """向用户展示交互式 UI 界面。

    使用此工具向用户呈现表单、卡片、表格等交互式界面，用于：
    - 收集用户输入（如预订表单、设置选项）
    - 展示结构化数据（如对比表格、信息卡片）
    - 提供交互选项（如多项选择、操作按钮）

    组件类型说明：

    基础组件：
    - text: 文本显示，props 包含 text, variant(body/heading/caption)
    - button: 按钮，props 包含 label, variant(primary/secondary/outline/ghost/danger), loading, fullWidth, size(sm/md/lg)
    - button_group: 按钮组，使用 children 包含多个 button

    表单组件（支持验证）：
    - text_field: 文本输入框，props 包含 label, placeholder, type(text/email/password/number)
    - textarea: 多行文本框，props 包含 label, placeholder, rows
    - select: 下拉选择，props 包含 label, options(字符串数组或{value,label}数组)
    - date_picker: 日期选择器，props 包含 label, minDate, maxDate
    - time_picker: 时间选择器，props 包含 label, minTime, maxTime, step
    - slider: 滑块，props 包含 label, min, max, step, showValue
    - checkbox: 复选框，props 包含 label
    - radio: 单选按钮组，props 包含 label, options, layout(horizontal/vertical)
    - switch: 开关，props 包含 label

    布局组件：
    - container: 普通容器，使用 children 包含子组件
    - card: 卡片容器，props 包含 title, 使用 children 包含子组件
    - grid: 网格布局，props 包含 columns, gap, mobileColumns, tabletColumns
    - tabs: 选项卡布局，props 包含 tabs([{label}])，使用 children 包含子组件，顺序与 tabs 对应
    - divider: 分隔线

    数据展示组件：
    - table: 表格，props 包含 columns([{key,title}]), bindings 绑定 data
    - chart: 图表，props 包含 type(bar/line/pie/donut), title, showLegend, showValues
    - image: 图片，props 包含 src, alt, caption, objectFit(cover/contain)
    - progress: 进度条，props 包含 value, max, showLabel
    - badge: 徽章，props 包含 text, variant(default/success/warning/error)

    验证规则（在表单组件的 props 中添加）：
    - required: true/false - 必填验证
    - minLength: number - 最小长度
    - maxLength: number - 最大长度
    - pattern: string - 正则表达式验证
    - min: number - 最小值（用于数字/slider）
    - max: number - 最大值（用于数字/slider）
    - validation: [{type, value, message}] - 自定义验证规则数组

    条件渲染（在组件的 bindings 或 props 中添加）：
    - visible: "path.to.value" - 根据数据路径的值决定是否显示
    - visible: "path == 'value'" - 条件表达式

    Args:
        title: UI 标题
        components: 组件列表（扁平邻接表结构）
        root_ids: 根组件 ID 列表
        data: 初始数据模型
        actions: 可触发的动作列表

    Returns:
        确认消息，说明 UI 已发送给用户
    """
    try:
        parsed_components: list[UIComponent] = []
        for comp_dict in components:
            comp_type_str = comp_dict.get("type", "")
            try:
                comp_type = UIComponentType(comp_type_str)
            except ValueError:
                logger.warning("Unknown component type: %s, skipping", comp_type_str)
                continue

            parsed_components.append(
                UIComponent(
                    id=comp_dict.get("id", ""),
                    type=comp_type,
                    props=comp_dict.get("props", {}),
                    children=comp_dict.get("children", []),
                    bindings=comp_dict.get("bindings", {}),
                    events=comp_dict.get("events", {}),
                )
            )

        parsed_actions: list[UIAction] = []
        for action_dict in actions or []:
            parsed_actions.append(
                UIAction(
                    id=action_dict.get("id", ""),
                    type=action_dict.get("type", "custom"),
                    label=action_dict.get("label", ""),
                    payload=action_dict.get("payload", {}),
                )
            )

        ui_artifact = UIArtifact(
            title=title,
            components=parsed_components,
            root_ids=root_ids,
            data=data or {},
            actions=parsed_actions,
        )

        registry = get_ui_registry()
        if registry:
            registry.add_ui(ui_artifact)
            logger.warning(
                "UI artifact registered: %s (surface_id=%s)",
                title,
                ui_artifact.surface_id,
            )
        else:
            logger.warning("UI Registry not initialized, UI artifact will be lost")

        return f"已向用户展示交互式界面：「{title}」。用户可以在界面上进行操作，操作结果将自动反馈给我。"

    except Exception as e:
        error_msg = f"Failed to render UI: {type(e).__name__}: {e!s}"
        logger.error(error_msg)
        return error_msg


render_ui_tool = tool("render_ui_tool")(render_ui)
render_ui_tool.tags = ["interactive"]
