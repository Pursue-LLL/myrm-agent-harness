"""Unit tests for Project Experience & ADR Flywheel suite (Item 154).

[INPUT]
- Mock task traces, execution plans, temporary workspace directories.

[OUTPUT]
- Asserts on Bug/ADR extraction, causal flywheel ingestion, dongle synchronization, and minefield pre-sniffing.

[POS]
- Harness test suite for Item 154 ProjectExperienceAndADRFlywheelSuite.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from myrm_agent_harness.toolkits.memory.experience_flywheel import (
    BugExperienceAndADRExtractor,
    CausalFlywheelStore,
    EngineeringExperience,
    ExperienceKind,
    MinefieldPreSniffingGuard,
)
from myrm_agent_harness.toolkits.memory.project_dongle import (
    ProjectContextDongleManager,
)


def test_extract_bug_experience_and_adr() -> None:
    extractor = BugExperienceAndADRExtractor()
    narrative = """
    模块: `sqlite3_driver`。踩坑记录：触发条件: 在 Python 3.13 下开启 autocommit=True 同时执行手动 BEGIN IMMEDIATE 事务。根因: 驱动内部事务状态与底层 C 驱动冲突报错。有效解法: 统一设置 isolation_level=None 并纯用显式 SQL 事务。

    模块: `project_dongle`。架构决策 ADR：论据: 纯文本四维 Markdown Bullet 拥有最高跨 Agent 可移植性。约定: 单个文件严格不超过 400 行且包含标准唯一 Block ID。
    """

    experiences = extractor.extract_from_trace(narrative)
    assert len(experiences) >= 2

    # Verify bug experience
    bug_item = next(e for e in experiences if e.kind == ExperienceKind.BUG_EXPERIENCE)
    assert "sqlite3" in bug_item.target_entity.lower()
    assert "autocommit=True" in bug_item.trigger_condition
    assert "isolation_level=None" in bug_item.convention_or_remedy

    # Verify ADR
    adr_item = next(e for e in experiences if e.kind == ExperienceKind.ARCHITECTURAL_DECISION)
    assert "project_dongle" in adr_item.target_entity.lower()
    assert "400 行" in adr_item.convention_or_remedy


def test_causal_flywheel_store_and_dongle_sync() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        workspace_path = Path(tmp_dir)
        dongle_mgr = ProjectContextDongleManager()
        store = CausalFlywheelStore(dongle_manager=dongle_mgr)

        bug_exp = EngineeringExperience(
            experience_id="exp_01",
            kind=ExperienceKind.BUG_EXPERIENCE,
            target_entity="auth_cache",
            trigger_condition="高并发时未持读写锁",
            root_cause_or_rationale="内存竞争导致脏读",
            convention_or_remedy="使用 asyncio.Lock() 包裹原子读写",
            created_date="2026-09-28",
        )

        res = store.ingest_experience(bug_exp, workspace_dir=workspace_path)
        assert res.persisted is True
        assert res.bound_dongle_block_id == "exp_01"

        # Verify dongle LESSONS.md reflects the lesson
        state = dongle_mgr.load_state(workspace_path)
        assert len(state.lesson_blocks) == 1
        assert "auth_cache" in state.lesson_blocks[0].content
        assert "asyncio.Lock" in state.lesson_blocks[0].content


def test_minefield_pre_sniffing_guard() -> None:
    store = CausalFlywheelStore()
    store.ingest_experience(
        EngineeringExperience(
            experience_id="blk_deadlock",
            kind=ExperienceKind.BUG_EXPERIENCE,
            target_entity="payment_table",
            trigger_condition="直接执行 UPDATE 没有加锁",
            root_cause_or_rationale="多事务并发死锁",
            convention_or_remedy="必须经由 PaymentSagaService 协调执行",
            created_date="2026-09-28",
        )
    )
    store.ingest_experience(
        EngineeringExperience(
            experience_id="blk_adr_auth",
            kind=ExperienceKind.ARCHITECTURAL_DECISION,
            target_entity="jwt_verifier",
            trigger_condition="签发第三方令牌",
            root_cause_or_rationale="增强防重放攻击能力",
            convention_or_remedy="必须携带 jti 并校验时间窗不超过 300s",
            created_date="2026-09-28",
        )
    )

    guard = MinefieldPreSniffingGuard(store)

    # 1. Plan mentions high-risk entity
    plan = "计划在 payment_table 中添加一笔扣费记录并更新余额"
    alerts = guard.sniff(plan)
    assert len(alerts) >= 1
    assert alerts[0].entity_matched == "payment_table"
    assert alerts[0].severity == "critical"
    assert "PaymentSagaService" in alerts[0].convention_to_follow

    # 2. Format system prompt advisory
    prompt = guard.format_alerts_prompt(alerts)
    assert "HISTORICAL MINEFIELD" in prompt
    assert "payment_table" in prompt
    assert "PaymentSagaService" in prompt


def test_find_by_entity_and_filter_by_kind() -> None:
    store = CausalFlywheelStore()
    exp1 = EngineeringExperience(
        experience_id="e1",
        kind=ExperienceKind.BUG_EXPERIENCE,
        target_entity="qdrant_client",
        trigger_condition="localhost 解析为 ::1",
        root_cause_or_rationale="IPv6 监听缺失",
        convention_or_remedy="规范化为 127.0.0.1",
        created_date="2026-09-28",
    )
    exp2 = EngineeringExperience(
        experience_id="e2",
        kind=ExperienceKind.ARCHITECTURAL_DECISION,
        target_entity="qdrant_client",
        trigger_condition="选择向量存储底座",
        root_cause_or_rationale="单机与沙箱轻量自愈能力强",
        convention_or_remedy="默认优先使用本地 Qdrant 容器",
        created_date="2026-09-28",
    )
    store.ingest_experience(exp1)
    store.ingest_experience(exp2)

    by_entity = store.find_by_entity("qdrant_client")
    assert len(by_entity) == 2

    bugs = store.list_all(kind=ExperienceKind.BUG_EXPERIENCE)
    assert len(bugs) == 1
    assert bugs[0].experience_id == "e1"

    adrs = store.list_all(kind=ExperienceKind.ARCHITECTURAL_DECISION)
    assert len(adrs) == 1
    assert adrs[0].experience_id == "e2"
