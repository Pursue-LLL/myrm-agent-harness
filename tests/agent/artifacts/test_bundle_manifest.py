"""Tests for DeliverableManifest schema and category inference."""

import json
from myrm_agent_harness.agent.artifacts.bundle_manifest import (
    DeliverableCategory,
    DeliverableItem,
    DeliverableManifest,
    DeliverableStatus,
    infer_item_category,
)


def test_deliverable_item_serialization():
    item = DeliverableItem(
        id="art-123",
        filename="xhs_copy.md",
        relative_path="02_copywriting_and_content/xhs_copy.md",
        category=DeliverableCategory.COPYWRITING,
        platform="xiaohongshu",
        content_type="text/markdown",
        size_bytes=1024,
        sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        status=DeliverableStatus.READY_FOR_DISTRIBUTION,
        description="小红书痛点版文案",
    )
    d = item.to_dict()
    assert d["category"] == "copywriting"
    assert d["status"] == "ready_for_distribution"
    assert d["platform"] == "xiaohongshu"

    recovered = DeliverableItem.from_dict(d)
    assert recovered.id == "art-123"
    assert recovered.category == DeliverableCategory.COPYWRITING
    assert recovered.status == DeliverableStatus.READY_FOR_DISTRIBUTION


def test_deliverable_manifest_roundtrip():
    item1 = DeliverableItem(
        id="art-1",
        filename="strategy.md",
        relative_path="01_strategy_and_overview/strategy.md",
        category=DeliverableCategory.STRATEGY,
    )
    item2 = DeliverableItem(
        id="art-2",
        filename="cover.png",
        relative_path="03_visual_and_media/cover.png",
        category=DeliverableCategory.VISUAL,
    )
    manifest = DeliverableManifest(
        title="AI 产品发布宣发全案",
        description="包含公众号长文、小红书图文与配图",
        agent_id="agent-copywriter",
        goal_id="goal-456",
        items=[item1, item2],
    )
    d = manifest.to_dict()
    assert len(d["items"]) == 2
    json_str = json.dumps(d)
    assert "AI 产品发布宣发全案" in json_str

    parsed = DeliverableManifest.from_dict(json.loads(json_str))
    assert parsed.title == "AI 产品发布宣发全案"
    assert len(parsed.items) == 2
    assert parsed.items[0].category == DeliverableCategory.STRATEGY


def test_infer_item_category():
    assert infer_item_category("fact_check_sheet.md") == DeliverableCategory.FACT_CHECK
    assert infer_item_category("7days_schedule.xlsx") == DeliverableCategory.SCHEDULE
    assert infer_item_category("campaign_strategy.md") == DeliverableCategory.STRATEGY
    assert infer_item_category("xhs_article.md") == DeliverableCategory.COPYWRITING
    assert infer_item_category("banner.png") == DeliverableCategory.VISUAL
    assert infer_item_category("financials.xlsx") == DeliverableCategory.DATA_SHEET
    assert infer_item_category("migrate.py") == DeliverableCategory.CODE
    assert infer_item_category("notes.txt") == DeliverableCategory.OTHER
