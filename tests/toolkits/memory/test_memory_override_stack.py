# [POS] tests/toolkits/memory/test_memory_override_stack.py
# [INPUT] types, detector, gate, ProceduralMemory
# [OUTPUT] test_ephemeral_bypass_on_explicit_mandated_dependency, test_explicit_rule_id_bypass_directive, test_unconflicted_prompts_pass_through_without_bypass, test_zero_mutation_guarantee_on_candidate_rules

from myrm_agent_harness.toolkits.memory.override_stack import (
    DynamicUserOverrideStack,
    EphemeralBypassGate,
    PlaybookConflictDetector,
    PriorityLevel,
)
from myrm_agent_harness.toolkits.memory.types import ProceduralMemory


def _create_rule(
    rule_id: str,
    action: str,
    trigger: str = "when coding",
    content: str = "",
    facets: list[str] | None = None,
) -> ProceduralMemory:
    """Helper to instantiate a ProceduralMemory instance for override stack tests."""
    return ProceduralMemory(
        id=rule_id,
        user_id="test_user",
        trigger=trigger,
        action=action,
        content=content,
        facets=facets or ["coding"],
        is_active=True,
    )


def test_ephemeral_bypass_on_explicit_mandated_dependency() -> None:
    """Verify turn prompt mandating lodash bypasses the rule restricting lodash and injects transparent note."""
    stack = DynamicUserOverrideStack()
    rule_no_lodash = _create_rule(
        rule_id="rule_strict_native",
        action="一律使用原生函数，严禁引入 lodash",
        content="禁止使用 lodash 库，必须用 ES6 原生数组方法",
    )
    rule_logging = _create_rule(
        rule_id="rule_logging_standard",
        action="统一使用 logger.info 输出结构化日志",
        content="记录请求开始与结束状态",
    )

    turn_prompt = "本次旧系统数据迁移测试脚本，必须使用 lodash 进行深度克隆与对象合并"
    eval_result = stack.resolve(
        turn_prompt=turn_prompt, rules=[rule_no_lodash, rule_logging]
    )

    assert eval_result.has_conflicts is True
    assert len(eval_result.active_rules) == 1
    assert eval_result.active_rules[0].id == "rule_logging_standard"

    assert len(eval_result.bypassed_records) == 1
    bypassed = eval_result.bypassed_records[0]
    assert bypassed.rule_id == "rule_strict_native"
    assert bypassed.bypassed_in_current_turn is True
    assert "lodash" in bypassed.bypass_reason.lower()

    assert "规约单次豁免注记" in eval_result.injected_context_note
    assert "rule_strict_native" in eval_result.injected_context_note


def test_explicit_rule_id_bypass_directive() -> None:
    """Verify explicit bypass of a specific rule ID relieves the constraint."""
    gate = EphemeralBypassGate()
    rule_deploy = _create_rule(
        rule_id="rule_deploy_safe",
        action="部署前必须等待人工审批",
        content="生产环境部署红线",
    )
    rule_lint = _create_rule(
        rule_id="rule_code_lint",
        action="提交前执行 ruff 检查",
        content="格式规范",
    )

    turn_prompt = "本次紧急修复请跳过规则: rule_deploy_safe，直接发布容器镜像"
    eval_result = gate.evaluate(
        query=turn_prompt, candidate_rules=[rule_deploy, rule_lint]
    )

    assert eval_result.has_conflicts is True
    active_ids = [r.id for r in eval_result.active_rules]
    assert "rule_deploy_safe" not in active_ids
    assert "rule_code_lint" in active_ids
    assert eval_result.bypassed_records[0].rule_id == "rule_deploy_safe"


def test_unconflicted_prompts_pass_through_without_bypass() -> None:
    """Verify routine instructions pass all candidate rules without triggering bypass."""
    stack = DynamicUserOverrideStack()
    rule_1 = _create_rule(
        rule_id="rule_1",
        action="严禁引入 lodash",
        content="禁止使用 lodash",
    )
    rule_2 = _create_rule(
        rule_id="rule_2",
        action="使用 ruff 检查代码",
        content="代码格式规范",
    )

    turn_prompt = "请帮我重构一下用户服务的接口异常处理逻辑"
    eval_result = stack.resolve(turn_prompt=turn_prompt, rules=[rule_1, rule_2])

    assert eval_result.has_conflicts is False
    assert len(eval_result.active_rules) == 2
    assert len(eval_result.bypassed_records) == 0
    assert eval_result.injected_context_note == ""


def test_zero_mutation_guarantee_on_candidate_rules() -> None:
    """Verify ephemeral bypass leaves candidate ProceduralMemory objects completely unmutated."""
    detector = PlaybookConflictDetector()
    rule = _create_rule(
        rule_id="rule_restricted_target",
        action="避免使用 host 模式",
        content="严禁使用 host 网络",
    )

    turn_prompt = "本次排查必须使用 host 网络进行本地端口嗅探"
    record = detector.detect_conflict(query=turn_prompt, rule=rule)

    assert record is not None
    assert record.rule_id == "rule_restricted_target"
    # Ensure underlying rule status and properties are pristine
    assert rule.is_active is True
    assert rule.id == "rule_restricted_target"
    assert PriorityLevel.LEVEL_1_TURN_OVERRIDE == "level_1_turn_override"
