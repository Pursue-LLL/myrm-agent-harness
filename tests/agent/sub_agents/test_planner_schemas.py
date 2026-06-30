"""Tests for sub_agents/planner/schemas.py — plan models and validation."""

from __future__ import annotations

from myrm_agent_harness.agent.sub_agents.planner.schemas import ErrorRecord, Plan, PlannerInput, PlanStep


class TestErrorRecord:
    def test_default_values(self):
        e = ErrorRecord(error_type="TypeError", description="bad type")
        assert e.error_type == "TypeError"
        assert e.retry_count == 0
        assert e.impact == "medium"
        assert e.escalated_to_user is False
        assert e.attempt_history == []

    def test_full_error_record(self):
        e = ErrorRecord(
            step_id="s1",
            error_type="FileNotFoundError",
            description="missing file",
            context="open('x.txt')",
            resolution="create file",
            resolution_success=True,
            retry_count=2,
            impact="high",
            attempt_history=["try1", "try2"],
            escalated_to_user=False,
        )
        assert e.resolution_success is True
        assert len(e.attempt_history) == 2


class TestPlanStep:
    def test_basic_step(self):
        step = PlanStep(step_id="s1", description="Research the codebase", expected_output="Summary of code structure")
        assert step.step_id == "s1"
        assert step.status == "pending"
        assert step.dependencies == []

    def test_step_with_dependencies(self):
        step = PlanStep(
            step_id="s2", description="Implement feature", expected_output="Working code", dependencies=["s1"]
        )
        assert len(step.dependencies) == 1
        assert step.dependencies[0] == "s1"

    def test_step_status_variants(self):
        for status in ("pending", "in_progress", "completed", "skipped", "failed"):
            step = PlanStep(step_id="s1", description="x", expected_output="x", status=status)
            assert step.status == status

    def test_step_rejects_invalid_status(self):
        import pytest

        with pytest.raises(Exception):
            PlanStep(step_id="s1", description="x", expected_output="x", status="invalid")

    def test_allow_failure_default(self):
        step = PlanStep(step_id="s1", description="x", expected_output="x")
        assert step.allow_failure is False

    def test_allow_failure_true(self):
        step = PlanStep(step_id="s1", description="x", expected_output="x", allow_failure=True)
        assert step.allow_failure is True

    def test_allow_failure_serialization(self):
        step = PlanStep(step_id="s1", description="x", expected_output="x", allow_failure=True)
        data = step.model_dump()
        assert data["allow_failure"] is True
        restored = PlanStep.model_validate(data)
        assert restored.allow_failure is True

    def test_allow_failure_backward_compat(self):
        data = {"step_id": "s1", "description": "x", "expected_output": "x"}
        step = PlanStep.model_validate(data)
        assert step.allow_failure is False


class TestPlan:
    def test_minimal_plan(self):
        plan = Plan(
            goal="Fix auth bug",
            reasoning="Auth is broken",
            steps=[PlanStep(step_id="s1", description="Fix it", expected_output="Fixed")],
        )
        assert plan.goal == "Fix auth bug"
        assert len(plan.steps) == 1
        assert plan.key_findings == []
        assert plan.pending_issues == []
        assert plan.errors_encountered == []

    def test_plan_add_error(self):
        plan = Plan(goal="Test", reasoning="Test", steps=[PlanStep(step_id="s1", description="x", expected_output="x")])
        plan.add_error("FileNotFoundError", "Missing config", step_id="s1", impact="high")
        assert len(plan.errors_encountered) == 1
        assert plan.errors_encountered[0].error_type == "FileNotFoundError"
        assert plan.errors_encountered[0].impact == "high"

    def test_plan_with_findings_and_issues(self):
        plan = Plan(
            goal="Research",
            reasoning="Need data",
            steps=[],
            key_findings=["Bug at line 42"],
            pending_issues=["Review needed"],
        )
        assert len(plan.key_findings) == 1
        assert len(plan.pending_issues) == 1

    def test_plan_serialization(self):
        plan = Plan(goal="Test", reasoning="Test", steps=[PlanStep(step_id="s1", description="x", expected_output="x")])
        json_str = plan.model_dump_json()
        loaded = Plan.model_validate_json(json_str)
        assert loaded.goal == plan.goal
        assert len(loaded.steps) == 1


class TestPlanMethods:
    def _plan_with_steps(self) -> Plan:
        return Plan(
            goal="Test",
            reasoning="Reason",
            steps=[
                PlanStep(step_id="s1", description="Step 1", expected_output="R1", status="completed"),
                PlanStep(step_id="s2", description="Step 2", expected_output="R2", dependencies=["s1"]),
                PlanStep(step_id="s3", description="Step 3", expected_output="R3", dependencies=["s2"]),
            ],
            current_step_id="s2",
        )

    def test_get_current_step(self):
        plan = self._plan_with_steps()
        current = plan.get_current_step()
        assert current is not None
        assert current.step_id == "s2"

    def test_get_current_step_none(self):
        plan = Plan(goal="g", reasoning="r", steps=[])
        assert plan.get_current_step() is None

    def test_get_next_step(self):
        plan = self._plan_with_steps()
        next_step = plan.get_next_step()
        assert next_step is not None
        assert next_step.step_id == "s2"

    def test_mark_step_completed(self):
        plan = self._plan_with_steps()
        assert plan.mark_step_completed("s2")
        assert plan.steps[1].status == "completed"
        assert plan.current_step_id == "s3"

    def test_mark_step_completed_not_found(self):
        plan = self._plan_with_steps()
        assert not plan.mark_step_completed("nonexistent")

    def test_to_summary(self):
        plan = self._plan_with_steps()
        summary = plan.to_summary()
        assert "Phase 2/3" in summary
        assert "Step 2" in summary

    def test_to_line_format(self):
        plan = self._plan_with_steps()
        lines = plan.to_line_format()
        assert "PLAN" in lines
        assert "GOAL: Test" in lines
        assert "[x]" in lines
        assert "<CURRENT>" in lines

    def test_to_line_format_with_errors(self):
        plan = self._plan_with_steps()
        plan.add_error("TypeError", "bad type", step_id="s1")
        lines = plan.to_line_format()
        assert "ERRORS:" in lines
        assert "TypeError" in lines

    def test_to_line_format_with_findings_and_issues(self):
        plan = self._plan_with_steps()
        plan.key_findings = ["Found important thing"]
        plan.pending_issues = ["Need review"]
        plan.notes = "Extra note"
        lines = plan.to_line_format()
        assert "FINDING: Found important thing" in lines
        assert "ISSUE: Need review" in lines
        assert "NOTE: Extra note" in lines

    def test_get_recent_errors(self):
        plan = self._plan_with_steps()
        plan.add_error("E1", "err1", step_id="s1")
        plan.add_error("E2", "err2", step_id="s2")
        recent = plan.get_recent_errors(limit=1)
        assert len(recent) == 1

    def test_should_escalate_error(self):
        plan = self._plan_with_steps()
        err = ErrorRecord(error_type="E", description="d", retry_count=3)
        assert plan.should_escalate_error(err)
        err2 = ErrorRecord(error_type="E", description="d", retry_count=2)
        assert not plan.should_escalate_error(err2)

    def test_get_unique_attempt_methods(self):
        plan = self._plan_with_steps()
        err = ErrorRecord(error_type="E", description="d", attempt_history=["a", "b", "a"])
        methods = plan.get_unique_attempt_methods(err)
        assert methods == {"a", "b"}

    def test_add_error_attempt_new(self):
        plan = self._plan_with_steps()
        err = plan.add_error_attempt("s1", "FileNotFoundError", "missing", "try open()")
        assert err.retry_count == 1
        assert len(plan.errors_encountered) == 1

    def test_add_error_attempt_existing(self):
        plan = self._plan_with_steps()
        plan.add_error_attempt("s1", "FileNotFoundError", "missing", "try1")
        err = plan.add_error_attempt("s1", "FileNotFoundError", "still missing", "try2")
        assert err.retry_count == 2
        assert len(err.attempt_history) == 2
        assert len(plan.errors_encountered) == 1

    def test_add_error_attempt_escalation(self):
        plan = self._plan_with_steps()
        plan.add_error_attempt("s1", "E", "d", "try1")
        plan.add_error_attempt("s1", "E", "d", "try2")
        err = plan.add_error_attempt("s1", "E", "d", "try3")
        assert err.escalated_to_user is True


class TestPlanAllowFailure:
    """Tests for allow_failure / failed status in Plan methods."""

    def _mk(self, sid: str, **kw) -> PlanStep:
        return PlanStep(step_id=sid, description=f"step {sid}", expected_output="output", **kw)

    def _mkplan(self, steps: list[PlanStep]) -> Plan:
        return Plan(goal="test", reasoning="test", steps=steps)

    def test_get_ready_steps_skipped_dep_unblocks(self):
        plan = self._mkplan([self._mk("s1", status="skipped"), self._mk("s2", dependencies=["s1"])])
        ready_ids = [s.step_id for s in plan.get_ready_steps()]
        assert "s2" in ready_ids

    def test_get_next_step_skipped_dep_unblocks(self):
        plan = self._mkplan([self._mk("s1", status="skipped"), self._mk("s2", dependencies=["s1"])])
        nxt = plan.get_next_step()
        assert nxt is not None
        assert nxt.step_id == "s2"

    def test_get_ready_steps_failed_dep_blocks(self):
        plan = self._mkplan([self._mk("s1", status="failed"), self._mk("s2", dependencies=["s1"])])
        ready_ids = [s.step_id for s in plan.get_ready_steps()]
        assert "s2" not in ready_ids

    def test_mixed_deps_optional_skipped_and_completed(self):
        plan = self._mkplan([
            self._mk("a", status="completed"),
            self._mk("b", status="skipped", allow_failure=True),
            self._mk("c", dependencies=["a", "b"]),
        ])
        ready_ids = [s.step_id for s in plan.get_ready_steps()]
        assert "c" in ready_ids

    def test_multi_level_deps_with_optional_skip(self):
        plan = self._mkplan([
            self._mk("a", status="completed"),
            self._mk("b", status="skipped", allow_failure=True, dependencies=["a"]),
            self._mk("c", dependencies=["b"]),
            self._mk("d", dependencies=["a"]),
        ])
        ready_ids = [s.step_id for s in plan.get_ready_steps()]
        assert "c" in ready_ids
        assert "d" in ready_ids

    def test_to_line_format_failed_marker(self):
        plan = self._mkplan([self._mk("s1", status="failed")])
        lines = plan.to_line_format()
        assert "[!]" in lines

    def test_to_line_format_no_failed_marker_when_all_completed(self):
        plan = self._mkplan([self._mk("s1", status="completed")])
        lines = plan.to_line_format()
        assert "[!]" not in lines

    def test_to_markdown_failed_emoji(self):
        plan = self._mkplan([self._mk("s1", status="failed")])
        md = plan.to_markdown()
        assert "❌" in md
        assert "failed" in md

    def test_to_markdown_no_failed_emoji_when_all_completed(self):
        plan = self._mkplan([self._mk("s1", status="completed")])
        md = plan.to_markdown()
        assert "❌" not in md

    def test_plan_serialization_with_allow_failure(self):
        plan = self._mkplan([self._mk("s1", allow_failure=True, status="skipped")])
        json_str = plan.model_dump_json()
        loaded = Plan.model_validate_json(json_str)
        assert loaded.steps[0].allow_failure is True
        assert loaded.steps[0].status == "skipped"

    def test_plan_serialization_with_failed_status(self):
        plan = self._mkplan([self._mk("s1", status="failed")])
        json_str = plan.model_dump_json()
        loaded = Plan.model_validate_json(json_str)
        assert loaded.steps[0].status == "failed"


class TestPlanToMarkdown:
    def test_basic_markdown(self):
        plan = Plan(
            goal="Fix bug",
            reasoning="It's broken",
            steps=[
                PlanStep(step_id="s1", description="Research", expected_output="Info", status="completed"),
                PlanStep(step_id="s2", description="Implement", expected_output="Code", dependencies=["s1"]),
            ],
            current_step_id="s2",
        )
        md = plan.to_markdown()
        assert "# " in md
        assert "Fix bug" in md
        assert "Research" in md
        assert "CURRENT" in md

    def test_markdown_with_findings_and_issues(self):
        plan = Plan(
            goal="g",
            reasoning="r",
            steps=[],
            key_findings=["Found X"],
            pending_issues=["Review Y"],
            notes="Important note",
        )
        md = plan.to_markdown()
        assert "Key Findings" in md
        assert "Found X" in md
        assert "Pending Issues" in md
        assert "Review Y" in md
        assert "Notes" in md
        assert "Important note" in md

    def test_markdown_with_errors(self):
        plan = Plan(goal="g", reasoning="r", steps=[])
        plan.add_error("TypeError", "bad type", step_id="s1")
        md = plan.to_markdown()
        assert "Errors Encountered" in md
        assert "TypeError" in md

    def test_markdown_with_deps(self):
        plan = Plan(
            goal="g",
            reasoning="r",
            steps=[PlanStep(step_id="s2", description="d", expected_output="o", dependencies=["s1"])],
        )
        md = plan.to_markdown()
        assert "Dependencies" in md


class TestPlanStepRiskLevel:
    def test_risk_level_default_none(self):
        step = PlanStep(step_id="s1", description="d", expected_output="o")
        assert step.risk_level is None

    def test_risk_level_valid_values(self):
        for level in ("low", "medium", "high"):
            step = PlanStep(step_id="s1", description="d", expected_output="o", risk_level=level)
            assert step.risk_level == level

    def test_risk_level_serialization(self):
        step = PlanStep(step_id="s1", description="d", expected_output="o", risk_level="high")
        data = step.model_dump()
        assert data["risk_level"] == "high"

        step_none = PlanStep(step_id="s2", description="d", expected_output="o")
        data_none = step_none.model_dump()
        assert data_none["risk_level"] is None

    def test_risk_level_deserialization(self):
        plan = Plan(
            goal="g",
            reasoning="r",
            steps=[PlanStep(step_id="s1", description="d", expected_output="o", risk_level="medium")],
        )
        json_str = plan.model_dump_json()
        loaded = Plan.model_validate_json(json_str)
        assert loaded.steps[0].risk_level == "medium"

    def test_to_line_format_hides_low_risk(self):
        plan = Plan(
            goal="g",
            reasoning="r",
            steps=[PlanStep(step_id="s1", description="Safe task", expected_output="o", risk_level="low")],
            current_step_id="s1",
        )
        lines = plan.to_line_format()
        assert "[RISK:" not in lines

    def test_to_line_format_shows_medium_risk(self):
        plan = Plan(
            goal="g",
            reasoning="r",
            steps=[PlanStep(step_id="s1", description="Multi-file edit", expected_output="o", risk_level="medium")],
            current_step_id="s1",
        )
        lines = plan.to_line_format()
        assert "[RISK:MEDIUM]" in lines

    def test_to_line_format_shows_high_risk(self):
        plan = Plan(
            goal="g",
            reasoning="r",
            steps=[PlanStep(step_id="s1", description="Prod migration", expected_output="o", risk_level="high")],
            current_step_id="s1",
        )
        lines = plan.to_line_format()
        assert "[RISK:HIGH]" in lines

    def test_to_line_format_hides_none_risk(self):
        plan = Plan(
            goal="g",
            reasoning="r",
            steps=[PlanStep(step_id="s1", description="Unknown", expected_output="o", risk_level=None)],
            current_step_id="s1",
        )
        lines = plan.to_line_format()
        assert "[RISK:" not in lines

    def test_to_markdown_shows_medium_risk(self):
        plan = Plan(
            goal="g",
            reasoning="r",
            steps=[PlanStep(step_id="s1", description="d", expected_output="o", risk_level="medium")],
        )
        md = plan.to_markdown()
        assert "**Risk:** medium" in md

    def test_to_markdown_shows_high_risk(self):
        plan = Plan(
            goal="g",
            reasoning="r",
            steps=[PlanStep(step_id="s1", description="d", expected_output="o", risk_level="high")],
        )
        md = plan.to_markdown()
        assert "**Risk:** high" in md

    def test_to_markdown_hides_low_risk(self):
        plan = Plan(
            goal="g",
            reasoning="r",
            steps=[PlanStep(step_id="s1", description="d", expected_output="o", risk_level="low")],
        )
        md = plan.to_markdown()
        assert "**Risk:**" not in md

    def test_to_markdown_hides_none_risk(self):
        plan = Plan(
            goal="g",
            reasoning="r",
            steps=[PlanStep(step_id="s1", description="d", expected_output="o", risk_level=None)],
        )
        md = plan.to_markdown()
        assert "**Risk:**" not in md


class TestPlannerInput:
    def test_create_action(self):
        pi = PlannerInput(action="create", task_description="Create a plan")
        assert pi.action == "create"
        assert pi.task_description == "Create a plan"

    def test_get_action(self):
        pi = PlannerInput(action="get")
        assert pi.action == "get"
        assert pi.task_description is None

    def test_update_action(self):
        pi = PlannerInput(action="update", completed_step_id="s1", feedback="done")
        assert pi.action == "update"
        assert pi.completed_step_id == "s1"
