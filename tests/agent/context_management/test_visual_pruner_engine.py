"""单元测试：多模态视觉帧主动脱水修剪与时延压榨套件 (Item 203).

[INPUT]
- VisualFramePruningEngine
- VisualPruningConfig
- VisualPruningMode
- VisualPruningResult
- PrunedFrameFootprint

[OUTPUT]
- 验证严格滑动窗口淘汰历史早期图像帧并保留最新 N 帧
- 验证保留首帧（初始环境基线）与尾部滑动窗口模式
- 验证透传模式与图像数量低于窗口阈值时的零损耗直通
- 验证 Computer Use 动作提炼、结构化占位符替换与字典序列化
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_management.visual_pruner import (
    PrunedFrameFootprint,
    VisualFramePruningEngine,
    VisualPruningConfig,
    VisualPruningMode,
    VisualPruningResult,
)


def _make_dummy_image_block(pixel_tag: str) -> dict[str, object]:
    """Helper creating fake base64 image block."""
    fake_base64 = f"data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8{pixel_tag}"
    return {
        "type": "image_url",
        "image_url": {"url": fake_base64},
    }


def test_sliding_window_strict_eviction() -> None:
    """验证严格滑动窗口：在 5 张截图中仅保留最新 2 张，前 3 张物理剔除为紧凑单行占位符。"""
    config = VisualPruningConfig(
        window_size=2,
        mode=VisualPruningMode.SLIDING_WINDOW_STRICT,
        tokens_per_image_estimate=1500,
    )
    engine = VisualFramePruningEngine(config)

    messages: list[dict[str, object]] = []
    for turn in range(5):
        messages.append(
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": f"Turn {turn} observation"},
                    _make_dummy_image_block(f"frame_{turn}"),
                ],
                "tool_calls": [
                    {
                        "name": "computer_use",
                        "args": {"action": "click", "coordinate": [100 + turn, 200 + turn]},
                    }
                ],
            }
        )

    res: VisualPruningResult = engine.prune_messages(messages)

    assert res.total_images_found == 5
    assert res.retained_image_count == 2
    assert res.pruned_image_count == 3
    assert res.estimated_tokens_saved == 3 * 1500
    assert res.reclaimed_bytes > 0
    assert len(res.pruned_footprints) == 3

    # 检查前 3 轮的消息中，图像已被替换为脱水文本
    for turn in range(3):
        msg_blocks = res.cleansed_messages[turn]["content"]
        assert isinstance(msg_blocks, list)
        img_placeholder_block = msg_blocks[1]
        assert isinstance(img_placeholder_block, dict)
        assert img_placeholder_block["type"] == "text"
        assert f"[Image Pruned (Turn {turn}):" in str(img_placeholder_block["text"])
        assert "computer_use action='click'" in str(img_placeholder_block["text"])

    # 检查后 2 轮的消息中，图像完整保留未被触动
    for turn in (3, 4):
        msg_blocks = res.cleansed_messages[turn]["content"]
        assert isinstance(msg_blocks, list)
        retained_block = msg_blocks[1]
        assert isinstance(retained_block, dict)
        assert retained_block["type"] == "image_url"


def test_sliding_window_keep_initial_frame() -> None:
    """验证保留初始基线帧模式：保留 Turn 0 与最新 2 帧（Turn 2, Turn 3），仅淘汰 Turn 1。"""
    config = VisualPruningConfig(
        window_size=2,
        mode=VisualPruningMode.SLIDING_WINDOW_KEEP_INITIAL,
    )
    engine = VisualFramePruningEngine(config)

    messages: list[dict[str, object]] = []
    for turn in range(4):
        messages.append(
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": f"Step {turn}"},
                    _make_dummy_image_block(f"step_{turn}"),
                ],
            }
        )

    res = engine.prune_messages(messages)

    assert res.total_images_found == 4
    # 保留了 Turn 0（首帧）以及 Turn 2, Turn 3（尾部 2 帧）
    assert res.retained_image_count == 3
    assert res.pruned_image_count == 1
    assert len(res.pruned_footprints) == 1
    assert res.pruned_footprints[0].turn_index == 1

    # Turn 0 为 image_url
    assert res.cleansed_messages[0]["content"][1]["type"] == "image_url"
    # Turn 1 被脱水为 text
    assert res.cleansed_messages[1]["content"][1]["type"] == "text"
    # Turn 2, 3 维持 image_url
    assert res.cleansed_messages[2]["content"][1]["type"] == "image_url"
    assert res.cleansed_messages[3]["content"][1]["type"] == "image_url"


def test_bypass_and_under_threshold_scenarios() -> None:
    """验证 BYPASS 模式与少于窗口限制时的零损耗透传。"""
    # 场景 1: 图像少于 window_size
    engine_strict = VisualFramePruningEngine(VisualPruningConfig(window_size=3))
    short_messages = [
        {"role": "user", "content": [_make_dummy_image_block("one")]},
        {"role": "assistant", "content": [_make_dummy_image_block("two")]},
    ]
    res_under = engine_strict.prune_messages(short_messages)
    assert res_under.total_images_found == 2
    assert res_under.pruned_image_count == 0
    assert res_under.retained_image_count == 2
    assert res_under.cleansed_messages == short_messages

    # 场景 2: BYPASS 模式
    engine_bypass = VisualFramePruningEngine(
        VisualPruningConfig(mode=VisualPruningMode.BYPASS, window_size=1)
    )
    res_bypass = engine_bypass.prune_messages(short_messages)
    assert res_bypass.pruned_image_count == 0
    assert res_bypass.cleansed_messages == short_messages


def test_action_summary_extraction_and_serialization() -> None:
    """验证元数据提炼、JSON 字典序列化与耗时统计。"""
    config = VisualPruningConfig(window_size=1)
    engine = VisualFramePruningEngine(config)

    messages: list[dict[str, object]] = [
        {
            "role": "assistant",
            "content": [_make_dummy_image_block("old")],
            "tool_calls": [
                {
                    "name": "browser_action",
                    "args": {"action": "navigate", "command": "goto https://example.com"},
                }
            ],
        },
        {
            "role": "assistant",
            "content": [_make_dummy_image_block("new")],
            "content_str": "Done",
        },
    ]

    res = engine.prune_messages(messages)
    assert res.pruned_image_count == 1
    assert res.duration_ms >= 0.0

    out_dict = res.to_dict()
    assert out_dict["total_images_found"] == 2
    assert out_dict["retained_image_count"] == 1
    assert out_dict["pruned_image_count"] == 1
    assert len(out_dict["pruned_footprints"]) == 1
    footprint = out_dict["pruned_footprints"][0]
    assert footprint["turn_index"] == 0
    assert "browser_action" in footprint["action_summary"]
