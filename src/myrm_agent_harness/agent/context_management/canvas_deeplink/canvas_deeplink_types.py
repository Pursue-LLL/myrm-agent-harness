"""跨会话画布深度直链共享、设计资产穿透与专业设计平台桥接套件强类型契约定义。

[INPUT]
- 无外部动态依赖，定义画布统一寻址 URI 契约、设计图层树、设计系统 Token 与专业工具同步载荷契约。

[OUTPUT]
- CanvasLayerKind: 画布图层类型枚举 (FRAME, VECTOR, TEXT, IMAGE, GROUP)
- CanvasDeepLinkUri: 画布标准深度直链解析契约
- CanvasLayerNode: 结构化矢量图层节点契约
- CanvasDesignTokens: 调色板与字体排印设计变量契约
- CanvasDesignAsset: 画布全量设计资产契约
- ProStudioPlatform: 专业设计协同平台枚举 (FIGMA, PENPOT, ARDOT)
- ProStudioSyncPayload: 专业设计工具云端同步载荷契约

[POS]
- 位于 context_management/canvas_deeplink/canvas_deeplink_types.py
"""

from dataclasses import dataclass, field
from enum import StrEnum


class CanvasLayerKind(StrEnum):
    """画布矢量图层类别枚举。"""

    FRAME = "frame"
    VECTOR = "vector"
    TEXT = "text"
    IMAGE = "image"
    GROUP = "group"


class ProStudioPlatform(StrEnum):
    """专业级外部矢量设计协同工具枚举。"""

    FIGMA = "figma"
    PENPOT = "penpot"
    ARDOT = "ardot"


@dataclass(frozen=True)
class CanvasDeepLinkUri:
    """画布标准全局统一寻址 URI 契约 (canvas://{workspace_id}/{canvas_id})。"""

    raw_uri: str
    workspace_id: str
    canvas_id: str
    focus_layer_id: str | None
    access_mode: str  # "readonly" | "interactive"
    is_valid: bool


@dataclass(frozen=True)
class CanvasLayerNode:
    """结构化矢量图层节点契约。"""

    layer_id: str
    name: str
    kind: CanvasLayerKind
    bounds: tuple[float, float, float, float]  # (x, y, width, height)
    properties: dict[str, str | int | float | bool]
    children: tuple["CanvasLayerNode", ...] = ()


@dataclass(frozen=True)
class CanvasDesignTokens:
    """设计系统变量规范 (Design Tokens)。"""

    color_palette: dict[str, str]       # name -> #HEX/RGBA
    typography: dict[str, str]          # name -> font family + size
    spacing: dict[str, int]             # name -> px


@dataclass(frozen=True)
class CanvasDesignAsset:
    """画布结构化设计资产全量契约。"""

    canvas_id: str
    title: str
    root_frame: CanvasLayerNode
    tokens: CanvasDesignTokens
    extracted_text_summary: str
    version: int
    updated_at_iso: str


@dataclass(frozen=True)
class ProStudioSyncPayload:
    """向专业设计协同平台双向同步的标准化载荷契约。"""

    platform: ProStudioPlatform
    target_project_name: str
    document_spec: dict[str, str | int | float | bool]
    layers_count: int
    direct_studio_url: str
    generated_at_iso: str
