"""Unit tests for DeliverableManifest and DeliverableBundle contracts in Harness."""

import time
import pytest
from myrm_agent_harness.core.artifacts.manifest import (
    DeliverableCategory,
    DeliverableItem,
    DeliverableManifest,
)
from myrm_agent_harness.agent.artifacts.vault import ArtifactVault


def test_deliverable_manifest_contract():
    item1 = DeliverableItem(
        id="item-1",
        filename="wechat.md",
        relative_path="02_copywriting_and_content/wechat.md",
        title="微信公众号发布长文",
        category=DeliverableCategory.COPYWRITING,
        vault_uri="vault://uuid-1",
        size_bytes=1024,
        mime_type="text/markdown",
    )
    item2 = DeliverableItem(
        id="item-2",
        filename="schedule.xlsx",
        relative_path="06_schedule_and_plans/schedule.xlsx",
        title="7天发布排期表",
        category=DeliverableCategory.SCHEDULE,
        vault_uri="vault://uuid-2",
        size_bytes=2048,
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    manifest = DeliverableManifest(
        bundle_id="bundle-123",
        session_id="session-456",
        title="9月宣发全案交付包",
        items=[item1, item2],
    )

    assert manifest.total_count == 2
    assert manifest.total_size_bytes == 3072
    summary = manifest.category_summary()
    assert summary["copywriting"] == 1
    assert summary["schedule"] == 1


def test_artifact_vault_manifest_persistence(tmp_path):
    vault = ArtifactVault(str(tmp_path))

    manifest_data = {
        "bundle_id": "bundle-abc",
        "session_id": "session-xyz",
        "title": "测试全案包",
        "items": [],
    }

    saved_path = vault.save_manifest(manifest_data)
    assert saved_path.exists()

    loaded = vault.get_manifest("bundle-abc")
    assert loaded is not None
    assert loaded["title"] == "测试全案包"

    missing = vault.get_manifest("non-existent")
    assert missing is None
