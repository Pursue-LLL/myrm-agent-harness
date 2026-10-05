"""Unit tests for User Intervention to Procedural Memory Distillation Engine."""

from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.procedural import (
    HumanInterventionEvent,
    InterventionMemoryExtractor,
    InterventionType,
    ProceduralRuleInjector,
    RuleScope,
)


def _make_event(
    instruction: str,
    tool_name: str | None = None,
    args: dict[str, str] | None = None,
    workspace: str | None = "/projects/my-app",
    event_type: InterventionType = InterventionType.NEGATIVE_CONSTRAINT,
) -> HumanInterventionEvent:
    """Helper to instantiate HumanInterventionEvent with clean defaults."""
    return HumanInterventionEvent(
        event_id="ev-01",
        session_id="sess-01",
        user_instruction=instruction,
        interrupted_tool_name=tool_name,
        interrupted_arguments=args or {},
        intervention_type=event_type,
        workspace_root=workspace,
        timestamp=datetime.now(UTC),
    )


class TestInterventionMemoryExtractor:
    """Test suite for extracting procedural rules from runtime human intervention events."""

    def test_negative_constraint_extraction(self) -> None:
        """Extractor must identify negative constraint directives and identify protected assets."""
        extractor = InterventionMemoryExtractor()
        event = _make_event(
            instruction="千万不要修改 .env.production 配置文件",
            tool_name="edit_file",
            args={"target_file": "/projects/my-app/.env.production"},
        )

        rule = extractor.extract_from_event(event)

        assert rule.rule_type == InterventionType.NEGATIVE_CONSTRAINT
        assert rule.prohibited_action is not None
        assert ".env.production" in rule.prohibited_action
        assert rule.scope == RuleScope.WORKSPACE
        assert rule.scope_target == "/projects/my-app"

    def test_prerequisite_enforcement_extraction(self) -> None:
        """Extractor must identify prerequisite demands and convert into required preflights."""
        extractor = InterventionMemoryExtractor()
        event = _make_event(
            instruction="在更新应用插件之前必须先关闭宿主服务",
            tool_name="bash",
            args={"command": "npm run install-plugin"},
            event_type=InterventionType.PREREQUISITE_ENFORCEMENT,
        )

        rule = extractor.extract_from_event(event)

        assert rule.rule_type == InterventionType.PREREQUISITE_ENFORCEMENT
        assert rule.required_preflight is not None
        assert "关闭宿主服务" in rule.required_preflight

    def test_corrective_action_extraction(self) -> None:
        """Extractor must identify corrective preference overrides."""
        extractor = InterventionMemoryExtractor()
        event = _make_event(
            instruction="采用 uv 而不是 pip 进行依赖安装",
            tool_name="bash",
            args={"command": "pip install requests"},
            event_type=InterventionType.CORRECTIVE_ACTION,
        )

        rule = extractor.extract_from_event(event)

        assert rule.rule_type == InterventionType.CORRECTIVE_ACTION
        assert rule.prohibited_action is not None
        assert "pip" in rule.prohibited_action
        assert "uv" in rule.prohibited_action

    def test_distill_events_deduplication_and_reinforcement(self) -> None:
        """Repeated events targeting the same constraint must reinforce confidence rather than duplicate."""
        extractor = InterventionMemoryExtractor()
        events = [
            _make_event(instruction="千万不要修改 .env.production"),
            _make_event(instruction="严禁编辑 .env.production"),
        ]

        result = extractor.distill_events(events)

        assert len(result.extracted_rules) == 1
        rule = result.extracted_rules[0]
        assert rule.confidence > 0.95
        assert result.merged_count == 1


class TestProceduralRuleInjector:
    """Test suite for scoped matching, prompt safety guard synthesis, and action preflight checks."""

    def test_scoped_rule_matching(self) -> None:
        """Rules must strictly apply only to matching workspaces unless marked GLOBAL."""
        extractor = InterventionMemoryExtractor()
        injector = ProceduralRuleInjector()

        ev_ws1 = _make_event(
            instruction="不要修改 config.json",
            workspace="/workspaces/repo-alpha",
        )
        rule_ws1 = extractor.extract_from_event(ev_ws1)

        ev_global = _make_event(
            instruction="严禁删除系统证书",
            workspace=None,
        )
        rule_global = extractor.extract_from_event(ev_global)

        catalog = [rule_ws1, rule_global]

        # In repo-alpha: both workspace rule and global rule match
        matched_alpha = injector.match_rules(
            catalog,
            target_tool="edit_file",
            target_path="config.json",
            workspace="/workspaces/repo-alpha",
        )
        assert len(matched_alpha) == 2

        # In repo-beta: workspace rule does not match, global rule matches
        matched_beta = injector.match_rules(
            catalog,
            target_tool="edit_file",
            target_path="config.json",
            workspace="/workspaces/repo-beta",
        )
        assert len(matched_beta) == 1
        assert matched_beta[0].rule_id == rule_global.rule_id

    def test_assemble_prompt_guard(self) -> None:
        """Matched rules must synthesize into authoritative prompt safety guard segment."""
        extractor = InterventionMemoryExtractor()
        injector = ProceduralRuleInjector()

        rule1 = extractor.extract_from_event(
            _make_event(instruction="不要修改 .env.production")
        )
        rule2 = extractor.extract_from_event(
            _make_event(
                instruction="在更新插件前必须先关闭宿主服务",
                event_type=InterventionType.PREREQUISITE_ENFORCEMENT,
            )
        )

        context = injector.assemble_prompt_guard([rule1, rule2])

        assert len(context.injected_rules) == 2
        assert "[PROCEDURAL SAFETY GUARD" in context.prompt_segment
        assert "STRICTLY PROHIBITED ACTIONS:" in context.prompt_segment
        assert "MANDATORY PREFLIGHT REQUIREMENTS:" in context.prompt_segment
        assert len(context.blocked_actions) == 1
        assert len(context.enforced_preflights) == 1

    def test_validate_action_blocking(self) -> None:
        """Tool call that directly violates prohibited procedural constraints must be blocked."""
        extractor = InterventionMemoryExtractor()
        injector = ProceduralRuleInjector()

        rule = extractor.extract_from_event(
            _make_event(instruction="千万不要修改 .env.production")
        )

        # Prohibited invocation targeting .env.production
        allowed, reason = injector.validate_action(
            rule,
            tool_name="write_file",
            arguments={"target": "/projects/my-app/.env.production", "content": "SECRET=123"},
        )
        assert allowed is False
        assert "BLOCKED by procedural rule" in reason

        # Allowed safe invocation targeting harmless file
        allowed_safe, _ = injector.validate_action(
            rule,
            tool_name="write_file",
            arguments={"target": "/projects/my-app/README.md", "content": "# Hello"},
        )
        assert allowed_safe is True
