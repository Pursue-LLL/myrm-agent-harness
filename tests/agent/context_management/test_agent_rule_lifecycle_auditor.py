"""单元测试：智能体长期规则生命周期审计、过时失效嗅探与瘦身清洗套件 (Item 191)。

覆盖测试点：
1. 健康纯净规则基准体检与满分健康度评分 (100.0)
2. 工作区本地陈旧失效路径主动嗅探与降级 (PATH_NOT_FOUND)
3. 正反互斥矛盾规则智能嗅探与对偶仲裁建议 (DIRECT_CONTRADICTION)
4. 长期零命中时效衰减 (OBSOLETE_ZERO_HIT) 与重复冗余标记
5. 规则体系自动化瘦身修剪 (prune_and_slim) 验证
"""

from pathlib import Path
import tempfile

from myrm_agent_harness.agent.context_management.rule_lifecycle import (
    AgentRuleLifecycleAuditor,
    RuleAuditItem,
    RuleConflictPair,
    RuleConflictType,
    RuleLifecycleConfig,
    RuleLifecycleReport,
    RuleLifecycleState,
)


def test_audit_healthy_rule_base() -> None:
    """测试健康活跃规则基准体检。"""
    auditor = AgentRuleLifecycleAuditor()
    rules = [
        RuleAuditItem(
            rule_id="r1",
            rule_text="必须遵循 PEP8 规范并提供具体的 Type Hints。",
            hit_count=45,
            days_since_last_hit=1,
        ),
        RuleAuditItem(
            rule_id="r2",
            rule_text="模块与函数应当保持单一职责与清晰命名。",
            hit_count=20,
            days_since_last_hit=2,
        ),
    ]

    report = auditor.audit_rules(rules)

    assert report.total_rules == 2
    assert report.healthy_rules == 2
    assert report.stale_rules == 0
    assert report.zero_hit_rules == 0
    assert len(report.conflicting_pairs) == 0
    assert report.health_score == 100.0
    assert "clean, agile and healthy" in report.pruning_suggestions[0]


def test_detect_stale_paths_in_workspace() -> None:
    """测试工作区本地路径陈旧失效主动探测。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        # 创建一个有效文件
        valid_file = workspace / "src" / "valid_module.py"
        valid_file.parent.mkdir(parents=True, exist_ok=True)
        valid_file.write_text("# valid", encoding="utf-8")

        auditor = AgentRuleLifecycleAuditor(
            RuleLifecycleConfig(check_local_filesystem_paths=True, critical_stale_penalty=15.0)
        )
        rules = [
            RuleAuditItem(
                rule_id="r_valid",
                rule_text="请参考 src/valid_module.py 中的结构实现。",
                hit_count=10,
            ),
            RuleAuditItem(
                rule_id="r_stale",
                rule_text="必须继承 legacy_archive/obsolete_base.py 中的基类。",
                hit_count=10,
            ),
        ]

        report = auditor.audit_rules(rules, workspace_root=workspace)

        assert report.total_rules == 2
        assert report.healthy_rules == 1
        assert report.stale_rules == 1
        assert report.health_score == 85.0
        assert any("obsolete_base.py" in s for s in report.pruning_suggestions)


def test_detect_polarity_contradiction_between_rules() -> None:
    """测试正反极性互斥矛盾智能嗅探 (正面攻破 catman 关键追问)。"""
    auditor = AgentRuleLifecycleAuditor()
    rules = [
        RuleAuditItem(
            rule_id="r_pos",
            rule_text="必须为所有函数补充详细的中文注释和原理解析。",
            hit_count=15,
        ),
        RuleAuditItem(
            rule_id="r_neg",
            rule_text="禁止在代码中编写冗余注释，保持代码最简纯净。",
            hit_count=12,
        ),
    ]

    report = auditor.audit_rules(rules)

    assert len(report.conflicting_pairs) == 1
    conflict = report.conflicting_pairs[0]
    assert conflict.conflict_type == RuleConflictType.DIRECT_CONTRADICTION
    assert conflict.rule_id_a == "r_pos"
    assert conflict.rule_id_b == "r_neg"
    assert "注释" in conflict.conflict_description
    assert "Explicitly decide" in conflict.resolution_advice
    assert report.health_score <= 80.0


def test_zero_hit_decay_and_duplicate_pruning() -> None:
    """测试长期零命中时效衰减与重复冗余规则识别。"""
    config = RuleLifecycleConfig(stale_days_threshold=30, min_hit_count=1)
    auditor = AgentRuleLifecycleAuditor(config=config)

    rules = [
        RuleAuditItem(
            rule_id="r_zero",
            rule_text="特定一次性临时数据迁移脚本请手动备份。",
            hit_count=0,
            days_since_last_hit=60,
        ),
        RuleAuditItem(
            rule_id="r_dup1",
            rule_text="严禁在任何地方使用 Any 类型。",
            hit_count=5,
        ),
        RuleAuditItem(
            rule_id="r_dup2",
            rule_text="严禁在任何地方使用 Any 类型。",
            hit_count=5,
        ),
    ]

    report = auditor.audit_rules(rules)

    assert report.zero_hit_rules == 1
    assert any("zero hits" in s for s in report.pruning_suggestions)


def test_rule_pruning_and_slimming() -> None:
    """测试规则体系自动化瘦身清洗与修剪。"""
    auditor = AgentRuleLifecycleAuditor()
    rules = [
        RuleAuditItem(
            rule_id="r_keep1",
            rule_text="代码行数单文件严格不超过 400 行。",
            state=RuleLifecycleState.ACTIVE_HEALTHY,
        ),
        RuleAuditItem(
            rule_id="r_stale",
            rule_text="参考已删除的废弃路径 tests/old/suite.py。",
            state=RuleLifecycleState.STALE_PATH_DETECTED,
        ),
        RuleAuditItem(
            rule_id="r_dup",
            rule_text="代码行数单文件严格不超过 400 行。",
            state=RuleLifecycleState.DUPLICATE_REDUNDANT,
        ),
        RuleAuditItem(
            rule_id="r_zero",
            rule_text="90 天前的一次性临时要求。",
            state=RuleLifecycleState.OBSOLETE_ZERO_HIT,
        ),
    ]

    # 1. 默认修剪失效路径与重复
    retained_1, count_1 = auditor.prune_and_slim(
        rules, remove_stale=True, remove_duplicates=True, remove_zero_hits=False
    )
    assert count_1 == 2
    assert len(retained_1) == 2
    assert [r.rule_id for r in retained_1] == ["r_keep1", "r_zero"]

    # 2. 激进瘦身：连同零命中规则一并修剪
    retained_2, count_2 = auditor.prune_and_slim(
        rules, remove_stale=True, remove_duplicates=True, remove_zero_hits=True
    )
    assert count_2 == 3
    assert len(retained_2) == 1
    assert retained_2[0].rule_id == "r_keep1"
