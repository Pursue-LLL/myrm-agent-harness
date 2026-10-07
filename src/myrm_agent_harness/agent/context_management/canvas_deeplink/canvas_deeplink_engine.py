"""跨会话画布深度直链共享、设计资产穿透与专业设计平台桥接核心引擎。

[INPUT]
- canvas_deeplink_types.py: 契约模型 (CanvasLayerKind, ProStudioPlatform, CanvasDeepLinkUri, CanvasLayerNode, CanvasDesignTokens, CanvasDesignAsset, ProStudioSyncPayload)

[OUTPUT]
- CanvasDeepLinkParser: 画布全局直链解析与格式化器
- CanvasAssetRegistry: 画布设计资产统一注册与检索中心
- CanvasTunnelingEngine: 跨会话穿透上下文注入与专业设计平台同步桥

[POS]
- 位于 context_management/canvas_deeplink/canvas_deeplink_engine.py
"""

from datetime import datetime, timezone
import re
from urllib.parse import parse_qs, urlparse

from .canvas_deeplink_types import (
    CanvasDeepLinkUri,
    CanvasDesignAsset,
    CanvasDesignTokens,
    CanvasLayerKind,
    CanvasLayerNode,
    ProStudioPlatform,
    ProStudioSyncPayload,
)


class CanvasDeepLinkParser:
    """画布统一寻址深度直链 (canvas://{workspace}/{canvas}) 解析与构建器。"""

    _CANVAS_URI_REGEX = re.compile(r"canvas://([a-zA-Z0-9_\-]+)/([a-zA-Z0-9_\-]+)(?:\?([^\s]*))?")

    @classmethod
    def parse_uri(cls, uri_str: str) -> CanvasDeepLinkUri:
        """解析标准画布直链 URI。"""
        if not uri_str:
            return CanvasDeepLinkUri(
                raw_uri="",
                workspace_id="",
                canvas_id="",
                focus_layer_id=None,
                access_mode="readonly",
                is_valid=False,
            )

        match = cls._CANVAS_URI_REGEX.match(uri_str.strip())
        if not match:
            return CanvasDeepLinkUri(
                raw_uri=uri_str,
                workspace_id="",
                canvas_id="",
                focus_layer_id=None,
                access_mode="readonly",
                is_valid=False,
            )

        workspace_id = match.group(1)
        canvas_id = match.group(2)
        query_str = match.group(3) or ""

        query_params = parse_qs(query_str)
        focus_layer = query_params.get("layer", [None])[0]
        access_mode = query_params.get("mode", ["interactive"])[0]

        return CanvasDeepLinkUri(
            raw_uri=uri_str,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            focus_layer_id=focus_layer,
            access_mode=access_mode,
            is_valid=True,
        )

    @classmethod
    def build_uri(
        cls,
        workspace_id: str,
        canvas_id: str,
        focus_layer_id: str | None = None,
        access_mode: str | None = None,
    ) -> str:
        """构建标准画布直链 URI。"""
        base = f"canvas://{workspace_id}/{canvas_id}"
        query_parts: list[str] = []
        if focus_layer_id:
            query_parts.append(f"layer={focus_layer_id}")
        if access_mode:
            query_parts.append(f"mode={access_mode}")

        if query_parts:
            return f"{base}?{'&'.join(query_parts)}"
        return base


class CanvasAssetRegistry:
    """画布结构化设计资产内存注册表。"""

    def __init__(self) -> None:
        self._assets: dict[str, CanvasDesignAsset] = {}

    def register(self, asset: CanvasDesignAsset) -> None:
        self._assets[asset.canvas_id] = asset

    def get(self, canvas_id: str) -> CanvasDesignAsset | None:
        return self._assets.get(canvas_id)

    def remove(self, canvas_id: str) -> bool:
        return bool(self._assets.pop(canvas_id, None))


class CanvasTunnelingEngine:
    """跨会话设计资产上下文穿透注入与专业设计平台桥接引擎。"""

    def __init__(self, registry: CanvasAssetRegistry | None = None) -> None:
        self._registry = registry or CanvasAssetRegistry()

    @property
    def registry(self) -> CanvasAssetRegistry:
        return self._registry

    def detect_and_resolve_canvases(self, prompt_text: str) -> list[tuple[CanvasDeepLinkUri, CanvasDesignAsset]]:
        """从用户提示词中自动探测并解析出所有包含的画布资产。"""
        resolved: list[tuple[CanvasDeepLinkUri, CanvasDesignAsset]] = []
        # 匹配文本中所有的 canvas:// 链接
        pattern = re.compile(r"canvas://[a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-]+(?:\?[^\s\)\"\']*)?")
        for match in pattern.finditer(prompt_text):
            uri_str = match.group(0)
            parsed = CanvasDeepLinkParser.parse_uri(uri_str)
            if parsed.is_valid:
                asset = self._registry.get(parsed.canvas_id)
                if asset:
                    resolved.append((parsed, asset))
        return resolved

    def generate_context_injection_brief(
        self,
        asset: CanvasDesignAsset,
        focus_layer_id: str | None = None,
    ) -> str:
        """生成注入大模型对话上下文的高密度结构化设计前置卡片。"""
        tokens_info = ", ".join(f"{k}: {v}" for k, v in asset.tokens.color_palette.items()) or "默认设计变量"

        layer_lines: list[str] = []
        self._collect_layer_hierarchy(asset.root_frame, layer_lines, level=0, focus_layer_id=focus_layer_id)
        hierarchy_text = "\n".join(layer_lines) if layer_lines else "无子图层"

        brief = (
            f"【画布设计资产穿透前置上下文】\n"
            f"- 画布标识: {asset.canvas_id} (标题: {asset.title}, 版本: v{asset.version})\n"
            f"- 核心配色变量: {tokens_info}\n"
            f"- 文本摘要内容: {asset.extracted_text_summary or '未包含排版文本'}\n"
            f"- 矢量图层结构骨架:\n{hierarchy_text}\n"
            f"（注：已直接穿透该画布设计上下文，模型可直接基于此配色、文案与布局回答或继续设计。）"
        )
        return brief

    def _collect_layer_hierarchy(
        self,
        node: CanvasLayerNode,
        lines: list[str],
        level: int,
        focus_layer_id: str | None,
    ) -> None:
        indent = "  " * level
        marker = " [聚焦]" if focus_layer_id and node.layer_id == focus_layer_id else ""
        lines.append(f"{indent}- [{node.kind}] {node.name} (id: {node.layer_id}){marker}")
        for child in node.children:
            self._collect_layer_hierarchy(child, lines, level + 1, focus_layer_id)

    def export_to_pro_studio(
        self,
        asset: CanvasDesignAsset,
        platform: ProStudioPlatform,
        studio_base_url: str = "https://figma.com/file",
    ) -> ProStudioSyncPayload:
        """将画布结构化矢量图层转译为专业设计平台的标准化双向同步载荷。"""
        # 统计全图层节点数量
        total_layers = self._count_layers(asset.root_frame)

        direct_url = f"{studio_base_url.rstrip('/')}/sync_{asset.canvas_id}"
        spec = {
            "canvas_id": asset.canvas_id,
            "title": asset.title,
            "root_bounds": f"{asset.root_frame.bounds[2]}x{asset.root_frame.bounds[3]}",
            "tokens_count": len(asset.tokens.color_palette),
            "export_format": "standard_vector_svg_json",
        }

        return ProStudioSyncPayload(
            platform=platform,
            target_project_name=asset.title,
            document_spec=spec,
            layers_count=total_layers,
            direct_studio_url=direct_url,
            generated_at_iso=datetime.now(timezone.utc).isoformat(),
        )

    def _count_layers(self, node: CanvasLayerNode) -> int:
        count = 1
        for child in node.children:
            count += self._count_layers(child)
        return count
