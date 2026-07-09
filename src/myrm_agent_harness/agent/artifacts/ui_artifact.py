"""交互式 UI 工件定义

基于 A2UI 理念设计的声明式 UI 描述格式，支持 Agent 生成交互式用户界面。

核心设计原则：
1. 安全性：只允许预定义的组件类型（白名单机制）
2. LLM 友好：扁平化邻接表结构，便于 LLM 生成
3. 框架无关：声明式描述，前端自行映射到具体组件
4. 渐进式更新：支持增量更新数据模型

[INPUT]
- (none)

[OUTPUT]
- UIComponentType: class — U I Component Type
- UIComponent: class — U I Component
- UIAction: class — U I Action
- UIArtifact: class — U I Artifact
- UIDataUpdate: class — U I Data Update

[POS]
Provides UIComponentType, UIComponent, UIAction.
"""

from enum import StrEnum

# JSON-compatible value type (replaces Any for type safety)
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

JsonValue = Any


class UIComponentType(StrEnum):
    """支持的 UI 组件类型（安全白名单）

    所有可用组件类型都在此枚举中定义，Agent 只能使用这些预批准的组件，
    防止 UI 注入攻击。
    """

    # 基础组件
    TEXT = "text"  # 文本显示
    BUTTON = "button"  # 按钮
    BUTTON_GROUP = "button_group"  # 按钮组（单选/多选）

    # 表单组件
    TEXT_FIELD = "text_field"  # 文本输入框
    TEXTAREA = "textarea"  # 多行文本框
    SELECT = "select"  # 下拉选择框
    DATE_PICKER = "date_picker"  # 日期选择器
    TIME_PICKER = "time_picker"  # 时间选择器
    SLIDER = "slider"  # 滑块
    CHECKBOX = "checkbox"  # 复选框
    RADIO = "radio"  # 单选框
    SWITCH = "switch"  # 开关

    # 布局组件
    CONTAINER = "container"  # 容器（布局）
    CARD = "card"  # 卡片
    DIVIDER = "divider"  # 分隔线
    GRID = "grid"  # 网格布局
    TABS = "tabs"  # 选项卡布局

    # 数据展示组件
    TABLE = "table"  # 表格
    LIST = "list"  # 列表
    IMAGE = "image"  # 图片
    CHART = "chart"  # 图表
    PROGRESS = "progress"  # 进度条
    BADGE = "badge"  # 徽章/标签


class UIComponent(BaseModel):
    """UI 组件声明

    使用邻接表模式：每个组件通过 id 标识，children 字段引用子组件 id。
    这种扁平结构更适合 LLM 增量生成。
    """

    id: str = Field(default_factory=lambda: str(uuid4())[:8], description="组件唯一标识符")
    type: UIComponentType = Field(..., description="组件类型")
    props: dict[str, JsonValue] = Field(default_factory=dict, description="组件属性（透传给前端渲染器）")
    children: list[str] = Field(default_factory=list, description="子组件 ID 列表")
    bindings: dict[str, str] = Field(
        default_factory=dict, description="数据绑定映射 (组件属性名 -> 数据路径，如 'value' -> '$.form.name')"
    )
    events: dict[str, str] = Field(
        default_factory=dict, description="事件绑定映射 (事件名 -> 动作 ID，如 'onClick' -> 'submit_action')"
    )


class UIAction(BaseModel):
    """UI 动作定义

    定义用户可以触发的动作，当用户点击按钮或提交表单时，
    前端将动作信息回传给 Agent。
    """

    id: str = Field(default_factory=lambda: str(uuid4())[:8], description="动作唯一标识符")
    type: Literal["submit", "cancel", "navigate", "custom"] = Field(..., description="动作类型")
    label: str = Field(..., description="动作显示文本")
    payload: dict[str, JsonValue] = Field(default_factory=dict, description="额外载荷数据")


class UIArtifact(BaseModel):
    """交互式 UI 工件

    Agent 生成的完整 UI 描述，包含组件树、数据模型和可触发动作。
    前端 Renderer 接收此对象后，将其渲染为原生 UI。
    """

    surface_id: str = Field(
        default_factory=lambda: str(uuid4())[:8], description="Surface 标识符，用于区分同一消息中的多个 UI"
    )
    title: str | None = Field(default=None, description="UI 标题（可选）")
    components: list[UIComponent] = Field(..., description="组件列表（扁平邻接表结构）")
    root_ids: list[str] = Field(..., description="根组件 ID 列表（渲染入口点）")
    data: dict[str, JsonValue] = Field(default_factory=dict, description="数据模型（组件通过 bindings 绑定）")
    actions: list[UIAction] = Field(default_factory=list, description="可触发的动作列表")

    def to_dict(self) -> dict[str, JsonValue]:
        """转换为字典（用于 SSE 传输）"""
        return self.model_dump()


class UIDataUpdate(BaseModel):
    """UI 数据增量更新

    用于 Agent 发送数据模型的增量更新，而不需要重新发送整个 UI 结构。
    """

    surface_id: str = Field(..., description="目标 Surface 的标识符")
    updates: dict[str, JsonValue] = Field(
        ...,
        description="顶层 data 补丁；嵌套 plain object 递归合并，数组与标量按 key 整键替换",
    )


class UIActionEvent(BaseModel):
    """用户动作事件

    当用户在 UI 上触发动作时，前端将此事件回传给 Agent。
    """

    surface_id: str = Field(..., description="来源 Surface 的标识符")
    action_id: str = Field(..., description="触发的动作 ID")
    action_type: str = Field(..., description="动作类型")
    data: dict[str, JsonValue] = Field(default_factory=dict, description="当前 UI 的数据状态")
    payload: dict[str, JsonValue] = Field(default_factory=dict, description="动作携带的额外数据")


# ==================== 便捷工厂函数 ====================


def create_text(text: str, component_id: str | None = None, **props: JsonValue) -> UIComponent:
    """创建文本组件"""
    return UIComponent(id=component_id or str(uuid4())[:8], type=UIComponentType.TEXT, props={"text": text, **props})


def create_button(label: str, action_id: str, component_id: str | None = None, **props: JsonValue) -> UIComponent:
    """创建按钮组件"""
    return UIComponent(
        id=component_id or str(uuid4())[:8],
        type=UIComponentType.BUTTON,
        props={"label": label, **props},
        events={"onClick": action_id},
    )


def create_text_field(
    label: str, data_path: str, component_id: str | None = None, placeholder: str = "", **props: JsonValue
) -> UIComponent:
    """创建文本输入框组件"""
    return UIComponent(
        id=component_id or str(uuid4())[:8],
        type=UIComponentType.TEXT_FIELD,
        props={"label": label, "placeholder": placeholder, **props},
        bindings={"value": data_path},
    )


def create_select(
    label: str,
    options: list[str] | list[dict[str, str]],
    data_path: str,
    component_id: str | None = None,
    **props: JsonValue,
) -> UIComponent:
    """创建下拉选择框组件"""
    return UIComponent(
        id=component_id or str(uuid4())[:8],
        type=UIComponentType.SELECT,
        props={"label": label, "options": options, **props},
        bindings={"value": data_path},
    )


def create_card(title: str, children: list[str], component_id: str | None = None, **props: JsonValue) -> UIComponent:
    """创建卡片组件"""
    return UIComponent(
        id=component_id or str(uuid4())[:8],
        type=UIComponentType.CARD,
        props={"title": title, **props},
        children=children,
    )


def create_tabs(
    tabs: list[dict[str, str]], children: list[str], component_id: str | None = None, **props: JsonValue
) -> UIComponent:
    """创建选项卡布局组件

    Args:
        tabs: 标签定义，每项包含 label 字段
        children: 子组件 ID 列表，顺序与 tabs 对应
    """
    return UIComponent(
        id=component_id or str(uuid4())[:8],
        type=UIComponentType.TABS,
        props={"tabs": tabs, **props},
        children=children,
    )


def create_table(
    columns: list[dict[str, str]], data_path: str, component_id: str | None = None, **props: JsonValue
) -> UIComponent:
    """创建表格组件

    Args:
        columns: 列定义，每列包含 key 和 title
        data_path: 数据绑定路径
    """
    return UIComponent(
        id=component_id or str(uuid4())[:8],
        type=UIComponentType.TABLE,
        props={"columns": columns, **props},
        bindings={"data": data_path},
    )
