"""Unit tests for MultimodalVisionAndArtifactMemorySuite in harness.

[INPUT]
- myrm_agent_harness.toolkits.memory.multimodal

[OUTPUT]
- Pytest test cases verifying multimodal ingestion, feature extraction, cross-modal retrieval, and card projection.

[POS]
tests/toolkits/memory/test_multimodal_vision_artifact_memory_suite.py
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.memory import (
    ArtifactKind,
    AssetModality,
    CrossModalRetriever,
    MultimodalFeatureExtractor,
    MultimodalIngestRequest,
    MultimodalMemoryOrchestrator,
    MultimodalMemoryStore,
    MultimodalSearchQuery,
)


@pytest.fixture
def extractor() -> MultimodalFeatureExtractor:
    return MultimodalFeatureExtractor()


@pytest.fixture
def store() -> MultimodalMemoryStore:
    return MultimodalMemoryStore()


@pytest.fixture
def retriever(extractor: MultimodalFeatureExtractor) -> CrossModalRetriever:
    return CrossModalRetriever(extractor=extractor)


@pytest.fixture
def orchestrator() -> MultimodalMemoryOrchestrator:
    return MultimodalMemoryOrchestrator()


def test_extractor_infers_image_and_artifact_types(extractor: MultimodalFeatureExtractor) -> None:
    # 1. Image inference
    img_req = MultimodalIngestRequest(
        title="系统架构拓扑图",
        description="微服务调用链路与边界网关示意图",
        file_path="/sandbox/workspace/diagrams/arch_topology.png",
    )
    img_item = extractor.extract_item(img_req)
    assert img_item.modality == AssetModality.IMAGE
    assert img_item.artifact_kind == ArtifactKind.DIAGRAM
    assert img_item.mime_type == "image/png"
    assert "image" in img_item.tags

    # 2. HTML report inference
    html_req = MultimodalIngestRequest(
        title="压力测试报告",
        description="QPS 达到 10000 时的吞吐与延迟指标分析",
        file_path="/sandbox/workspace/reports/perf_test_summary.html",
    )
    html_item = extractor.extract_item(html_req)
    assert html_item.modality == AssetModality.ARTIFACT
    assert html_item.artifact_kind == ArtifactKind.REPORT_HTML
    assert html_item.mime_type == "text/html"

    # 3. Card preview verification
    card = extractor.build_card_preview(html_item)
    assert card["title"] == "压力测试报告"
    assert card["path_status"] == "available"
    assert card["mime_type"] == "text/html"


def test_store_crud_and_scoping(store: MultimodalMemoryStore, extractor: MultimodalFeatureExtractor) -> None:
    item1 = extractor.extract_item(
        MultimodalIngestRequest(
            title="订单时序图",
            description="下单到支付流程时序",
            file_path="/sandbox/workspace/order_flow.svg",
            session_id="session_01",
        )
    )
    item2 = extractor.extract_item(
        MultimodalIngestRequest(
            title="财务对账单",
            description="2026年Q3度账单",
            file_path="/sandbox/workspace/finance.csv",
            session_id="session_02",
        )
    )

    store.add(item1)
    store.add(item2)
    assert store.count() == 2

    # Scoped query by session
    session_items = store.list_all(session_id="session_01")
    assert len(session_items) == 1
    assert session_items[0].title == "订单时序图"

    # Scoped query by modality
    artifacts = store.list_all(modality=AssetModality.ARTIFACT)
    assert len(artifacts) == 1
    assert artifacts[0].title == "财务对账单"

    # Delete
    assert store.delete(item1.item_id) is True
    assert store.count() == 1


def test_cross_modal_retrieval(orchestrator: MultimodalMemoryOrchestrator) -> None:
    orchestrator.ingest_asset(
        MultimodalIngestRequest(
            title="用户增长折线图",
            description="过去半年活跃用户与留存趋势",
            visual_summary="折线呈现上升趋势，留存率稳定在 45%",
            file_path="/sandbox/volume/user_growth.png",
        )
    )
    orchestrator.ingest_asset(
        MultimodalIngestRequest(
            title="数据库ER拓扑图",
            description="用户表与订单表外键拓扑",
            visual_summary="包含 users, orders, payments 实体关系",
            file_path="/sandbox/volume/db_er.svg",
        )
    )
    orchestrator.ingest_asset(
        MultimodalIngestRequest(
            title="性能基准测试HTML报告",
            description="Locust 压测指标导出",
            file_path="/sandbox/volume/locust_report.html",
        )
    )

    # 1. Search for user growth chart
    hits1 = orchestrator.search_assets(
        MultimodalSearchQuery(query_text="用户增长折线图")
    )
    assert len(hits1) >= 1
    assert hits1[0].item.title == "用户增长折线图"
    assert hits1[0].relevance_score >= 0.8
    assert hits1[0].card_preview["path_status"] == "available"

    # 2. Search by visual summary text
    hits2 = orchestrator.search_assets(
        MultimodalSearchQuery(query_text="包含 users orders 实体关系")
    )
    assert len(hits2) >= 1
    assert hits2[0].item.title == "数据库ER拓扑图"

    # 3. Filter by artifact kind
    hits_filtered = orchestrator.search_assets(
        MultimodalSearchQuery(
            query_text="报告",
            artifact_kind_filter=ArtifactKind.REPORT_HTML,
        )
    )
    assert len(hits_filtered) == 1
    assert hits_filtered[0].item.title == "性能基准测试HTML报告"

    # 4. Empty query safety
    assert orchestrator.search_assets(MultimodalSearchQuery(query_text="")) == []


def test_orchestrator_card_retrieval(orchestrator: MultimodalMemoryOrchestrator) -> None:
    item = orchestrator.ingest_asset(
        MultimodalIngestRequest(
            title="代码重构Diff文件",
            description="重构旧模块产生的增量补丁",
            file_path="/sandbox/volume/diff.patch",
        )
    )

    card = orchestrator.get_asset_card(item.item_id)
    assert card is not None
    assert card["item_id"] == item.item_id
    assert card["title"] == "代码重构Diff文件"

    # Non-existent item returns None
    assert orchestrator.get_asset_card("non_existent_id") is None
