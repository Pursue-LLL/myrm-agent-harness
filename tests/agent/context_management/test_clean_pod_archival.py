"""单元测试：单任务瞬态上下文防污染隔离、最终产物干净汇流与夜间定时无损资产沉淀套件 (Item 192)。

覆盖测试点：
1. 瞬态纯净上下文隔离舱派生与无污染指令注入 (SPAWNED_ISOLATED)
2. 结构化交付物无损提取、汇流至主会话与隔离舱自动退役 (RETIRED_DISCARDED)
3. 会话活跃隔离舱并发上限阈值拦截防御 (max_active_pods_per_session)
4. 夜间闲时资产沉淀任务注册与自动化归集落盘执行 (COMPLETED_INDEXED)
5. 错误边界处理与不存在对象的防御性抛错
"""

import pytest

from myrm_agent_harness.agent.context_management.clean_pod_archival import (
    CleanPodArchivalConfig,
    CleanPodArchivalEngine,
    EphemeralCleanPodDescriptor,
    NightlyArchivalJob,
    NightlyArchivalStatus,
    PodLifecycleState,
    TaskDeliverableContract,
)


def test_spawn_clean_pod_isolated_instructions() -> None:
    """测试瞬态纯净上下文隔离舱派生与无污染独立指令构建。"""
    engine = CleanPodArchivalEngine()
    parent_sid = "main_session_cinema_workbench"
    topic = "拉片拆解：第 3 幕光影与色调分析"
    instructions = "请仅针对第 3 幕 45:10 - 52:30 区间提取光比数值与主色调十六进制代码。"

    pod = engine.spawn_clean_pod(
        parent_session_id=parent_sid,
        task_topic=topic,
        isolated_instructions=instructions,
    )

    assert pod.parent_session_id == parent_sid
    assert pod.task_topic == topic
    assert pod.state == PodLifecycleState.SPAWNED_ISOLATED
    assert "CLEAN_POD_TASK_TOPIC" in pod.isolated_instructions
    assert "45:10 - 52:30" in pod.isolated_instructions
    assert len(pod.deliverables) == 0
    assert engine.get_pod(pod.pod_id) is not None


def test_extract_deliverable_and_retire_pod() -> None:
    """测试结构化最终产物提取汇流，并自动退役销毁瞬态试错上下文。"""
    engine = CleanPodArchivalEngine(
        CleanPodArchivalConfig(auto_retire_on_deliverable=True)
    )
    parent_sid = "main_session_film"
    pod = engine.spawn_clean_pod(
        parent_session_id=parent_sid,
        task_topic="分镜绘制参数提炼",
        isolated_instructions="提炼 5 个关键镜头 Prompt 与负面提示词。",
    )

    deliverable = TaskDeliverableContract(
        deliverable_id="deliv_shot_01",
        task_topic="分镜绘制参数提炼",
        content_payload="镜头 1: 广角仰拍赛博朋克雨夜巷道; 镜头 2: 特写霓虹反光眼眸",
        media_uris=("file:///workspace/shots/preview1.png", "file:///workspace/shots/preview2.png"),
        extracted_metadata=(("aspect_ratio", "2.39:1"), ("color_grade", "teal_orange")),
    )

    updated_pod, stamped = engine.extract_deliverable_and_retire_pod(
        pod_id=pod.pod_id,
        deliverable=deliverable,
    )

    # 验证 Pod 状态已安全退役销毁
    assert updated_pod.state == PodLifecycleState.RETIRED_DISCARDED
    assert updated_pod.retired_at_iso != ""
    assert len(updated_pod.deliverables) == 1

    # 验证交付物已干净汇流至主会话
    consolidated = engine.list_pod_deliverables(parent_sid)
    assert len(consolidated) == 1
    assert consolidated[0].deliverable_id == "deliv_shot_01"
    assert len(consolidated[0].media_uris) == 2
    assert dict(consolidated[0].extracted_metadata)["color_grade"] == "teal_orange"


def test_max_active_pods_limit_enforcement() -> None:
    """测试单会话活跃隔离舱配额上限拦截防御。"""
    config = CleanPodArchivalConfig(max_active_pods_per_session=2)
    engine = CleanPodArchivalEngine(config=config)
    parent_sid = "session_quota_test"

    # 派生 2 个活跃隔离舱
    pod1 = engine.spawn_clean_pod(parent_sid, "任务1", "指令1")
    engine.spawn_clean_pod(parent_sid, "任务2", "指令2")

    # 试图派生第 3 个应该被拦截
    with pytest.raises(ValueError, match="Maximum active clean pods limit"):
        engine.spawn_clean_pod(parent_sid, "任务3", "指令3")

    # 退役第 1 个之后应该可以继续派生
    engine.extract_deliverable_and_retire_pod(
        pod_id=pod1.pod_id,
        deliverable=TaskDeliverableContract(
            deliverable_id="d1", task_topic="任务1", content_payload="完成"
        ),
    )
    pod3 = engine.spawn_clean_pod(parent_sid, "任务3", "指令3")
    assert pod3.state == PodLifecycleState.SPAWNED_ISOLATED


def test_nightly_archival_job_scheduling_and_sweep() -> None:
    """测试夜间闲时自动化资产归集调度与多维落盘大盘报告生成。"""
    engine = CleanPodArchivalEngine()
    s1 = "session_daily_a"
    s2 = "session_daily_b"

    # 在两个会话中分别派生 Pod 并产出交付物
    p1 = engine.spawn_clean_pod(s1, "主题A", "指令A")
    engine.extract_deliverable_and_retire_pod(
        p1.pod_id,
        TaskDeliverableContract(
            deliverable_id="da_1",
            task_topic="主题A",
            content_payload="分析报告正文",
            media_uris=("file:///media/chart1.png",),
        ),
    )

    p2 = engine.spawn_clean_pod(s2, "主题B", "指令B")
    engine.extract_deliverable_and_retire_pod(
        p2.pod_id,
        TaskDeliverableContract(
            deliverable_id="db_1",
            task_topic="主题B",
            content_payload="分镜汇总",
            media_uris=("file:///media/shot1.png", "file:///media/shot2.png"),
        ),
    )

    # 注册夜间归集任务
    job = engine.register_nightly_archival_job(
        session_ids=(s1, s2),
        target_storage_prefix="cine_studio_vault",
        scheduled_hour_utc=3,
        job_id="job_nightly_cine_01",
    )
    assert job.status == NightlyArchivalStatus.SCHEDULED_IDLE
    assert job.scheduled_hour_utc == 3

    # 执行夜间资产盘点归集
    completed_job = engine.execute_nightly_archival_sweep("job_nightly_cine_01")
    assert completed_job.status == NightlyArchivalStatus.COMPLETED_INDEXED
    assert completed_job.table_records_count == 2
    # 2 个 deliverable + 3 个 media_uris = 5 个 assets
    assert completed_job.harvested_assets_count == 5
    assert "Successfully harvested 5 structured assets" in completed_job.summary_report
    assert "cine_studio_vault/bitable" in completed_job.summary_report


def test_clean_pod_errors_and_edge_cases() -> None:
    """测试错误边界与防御性容错。"""
    engine = CleanPodArchivalEngine()

    with pytest.raises(KeyError, match="Clean pod unknown_pod not found"):
        engine.extract_deliverable_and_retire_pod(
            "unknown_pod",
            TaskDeliverableContract(deliverable_id="x", task_topic="x", content_payload="x"),
        )

    with pytest.raises(KeyError, match="Nightly archival job unknown_job not found"):
        engine.execute_nightly_archival_sweep("unknown_job")

    assert engine.get_pod("none") is None
    assert engine.get_nightly_job("none") is None
