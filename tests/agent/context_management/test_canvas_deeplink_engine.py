"""跨会话画布深度直链共享、设计资产穿透与专业设计平台桥接套件单元测试。

[INPUT]
- CanvasDeepLinkParser, CanvasAssetRegistry, CanvasTunnelingEngine, CanvasDesignAsset, CanvasLayerNode, CanvasDesignTokens, CanvasLayerKind, ProStudioPlatform

[OUTPUT]
- 自动化验证标准直链解析与逆向构建、画布资产跨会话穿透识别、前置上下文生成与专业平台同步转译

[POS]
- 位于 tests/agent/context_management/test_canvas_deeplink_engine.py
"""

from myrm_agent_harness.agent.context_management.canvas_deeplink import (
    CanvasAssetRegistry,
    CanvasDeepLinkParser,
    CanvasDeepLinkUri,
    CanvasDesignAsset,
    CanvasDesignTokens,
    CanvasLayerKind,
    CanvasLayerNode,
    CanvasTunnelingEngine,
    ProStudioPlatform,
    ProStudioSyncPayload,
)


def _create_mock_canvas_asset(canvas_id: str = "cv_poster_01") -> CanvasDesignAsset:
    """构建用于测试的样本画布资产。"""
    cta_btn = CanvasLayerNode(
        layer_id="layer_cta",
        name="CTA Button",
        kind=CanvasLayerKind.FRAME,
        bounds=(50.0, 300.0, 200.0, 48.0),
        properties={"fill": "#FF5500", "radius": 8},
        children=(),
    )
    title_text = CanvasLayerNode(
        layer_id="layer_title",
        name="Header Title",
        kind=CanvasLayerKind.TEXT,
        bounds=(50.0, 50.0, 500.0, 60.0),
        properties={"text": "未来智能体生态峰会", "font_size": 32},
        children=(),
    )
    root = CanvasLayerNode(
        layer_id="root_frame",
        name="Main Artboard",
        kind=CanvasLayerKind.FRAME,
        bounds=(0.0, 0.0, 800.0, 600.0),
        properties={"background": "#0F172A"},
        children=(title_text, cta_btn),
    )
    tokens = CanvasDesignTokens(
        color_palette={"primary": "#FF5500", "background": "#0F172A", "text": "#FFFFFF"},
        typography={"title": "Inter Bold 32px", "body": "Inter Regular 14px"},
        spacing={"sm": 8, "md": 16, "lg": 24},
    )
    return CanvasDesignAsset(
        canvas_id=canvas_id,
        title="2026 智能体生态宣发海报",
        root_frame=root,
        tokens=tokens,
        extracted_text_summary="未来智能体生态峰会 · 立即报名",
        version=2,
        updated_at_iso="2026-10-08T04:00:00Z",
    )


def test_canvas_deeplink_parser_parse_and_build() -> None:
    """测试标准画布直链 URI 的解析与构建。"""
    raw_uri = "canvas://workspace_alpha/cv_poster_01?layer=layer_cta&mode=interactive"
    parsed: CanvasDeepLinkUri = CanvasDeepLinkParser.parse_uri(raw_uri)

    assert parsed.is_valid is True
    assert parsed.workspace_id == "workspace_alpha"
    assert parsed.canvas_id == "cv_poster_01"
    assert parsed.focus_layer_id == "layer_cta"
    assert parsed.access_mode == "interactive"

    # 测试逆向构建
    reconstructed = CanvasDeepLinkParser.build_uri(
        workspace_id="workspace_alpha",
        canvas_id="cv_poster_01",
        focus_layer_id="layer_cta",
        access_mode="interactive",
    )
    assert reconstructed == raw_uri

    # 测试非法 URI
    invalid_parsed = CanvasDeepLinkParser.parse_uri("https://example.com/not_canvas")
    assert invalid_parsed.is_valid is False


def test_canvas_asset_registry_and_tunneling() -> None:
    """测试画布资产注册表与跨会话提示词自动穿透解析。"""
    registry = CanvasAssetRegistry()
    asset = _create_mock_canvas_asset(canvas_id="cv_card_88")
    registry.register(asset)

    engine = CanvasTunnelingEngine(registry)

    prompt = "请根据 canvas://workspace_beta/cv_card_88?layer=layer_cta 的配色方案帮我写一段宣发文案"
    resolved = engine.detect_and_resolve_canvases(prompt)

    assert len(resolved) == 1
    parsed_uri, resolved_asset = resolved[0]
    assert parsed_uri.canvas_id == "cv_card_88"
    assert parsed_uri.focus_layer_id == "layer_cta"
    assert resolved_asset.title == "2026 智能体生态宣发海报"


def test_generate_context_injection_brief() -> None:
    """测试生成高密度结构化设计前置卡片，验证图层层级与聚焦标识。"""
    engine = CanvasTunnelingEngine()
    asset = _create_mock_canvas_asset(canvas_id="cv_test_01")

    brief = engine.generate_context_injection_brief(asset, focus_layer_id="layer_cta")

    assert "cv_test_01" in brief
    assert "2026 智能体生态宣发海报" in brief
    assert "#FF5500" in brief
    assert "[聚焦]" in brief  # layer_cta 被聚焦
    assert "未来智能体生态峰会" in brief


def test_export_to_pro_studio() -> None:
    """测试向 Figma/Penpot/Ardot 专业设计工具导出的标准化同步载荷。"""
    engine = CanvasTunnelingEngine()
    asset = _create_mock_canvas_asset(canvas_id="cv_pro_99")

    payload: ProStudioSyncPayload = engine.export_to_pro_studio(
        asset=asset,
        platform=ProStudioPlatform.FIGMA,
        studio_base_url="https://figma.com/file",
    )

    assert payload.platform == ProStudioPlatform.FIGMA
    assert payload.target_project_name == "2026 智能体生态宣发海报"
    assert payload.layers_count == 3  # root + title + cta
    assert payload.direct_studio_url == "https://figma.com/file/sync_cv_pro_99"
    assert payload.document_spec["root_bounds"] == "800.0x600.0"
