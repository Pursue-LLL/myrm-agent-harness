"""Unit tests for Desktop Workflow Skill Compiler."""

from myrm_agent_harness.backends.skills.workflow_compiler import (
    DesktopEvent,
    WorkflowIntentPlan,
    WorkflowPlanStep,
    WorkflowSkillCompiler,
    compile_workflow_plan_to_skill_markdown,
    slugify_skill_name,
)


def test_slugify_skill_name() -> None:
    assert (
        slugify_skill_name("ERP Financial Reconciliation")
        == "erp-financial-reconciliation"
    )
    assert slugify_skill_name("  Batch Export 2026!  ") == "batch-export-2026"
    assert slugify_skill_name("") == "desktop-workflow-skill"


def test_desktop_event_serialization() -> None:
    event = DesktopEvent(
        event_type="app_switch",
        timestamp_ms=1724650000000,
        app_name="Microsoft Excel",
        window_title="Q3_Financial_Ledger.xlsx",
        clipboard_preview="ORD-998231",
        detail="Switched to Excel sheet",
    )
    data = event.to_dict()
    assert data["app_name"] == "Microsoft Excel"
    assert data["event_type"] == "app_switch"

    restored = DesktopEvent.from_dict(data)
    assert restored.app_name == event.app_name
    assert restored.timestamp_ms == event.timestamp_ms


def test_workflow_plan_step_serialization() -> None:
    step = WorkflowPlanStep(
        step_id="step-1",
        title="Copy order number from spreadsheet",
        description="Extract order ID cell value and place into clipboard",
        tool_hint="read_file",
        target_app="Microsoft Excel",
        variables_used=["order_id"],
    )
    data = step.to_dict()
    assert data["step_id"] == "step-1"
    assert data["variables_used"] == ["order_id"]

    restored = WorkflowPlanStep.from_dict(data)
    assert restored.step_id == step.step_id
    assert restored.variables_used == ["order_id"]


def test_workflow_intent_plan_serialization() -> None:
    plan = WorkflowIntentPlan(
        name="Custom Tax Declaration Workflow",
        description="Automate monthly tax invoice submission",
        intent="Reads Excel invoice and submits via web portal",
        steps=[
            WorkflowPlanStep(
                step_id="s1",
                title="Extract invoice data",
                description="Read rows from invoice.xlsx",
                tool_hint="file_parser",
            )
        ],
        variables={"tax_year": "The current taxation year"},
        allowed_tools=["browser_navigate_tool", "shell_execute"],
    )
    data = plan.to_dict()
    assert data["name"] == "Custom Tax Declaration Workflow"
    assert len(data["steps"]) == 1

    restored = WorkflowIntentPlan.from_dict(data)
    assert restored.name == plan.name
    assert restored.variables["tax_year"] == "The current taxation year"


def test_compile_workflow_plan_to_skill_markdown() -> None:
    plan = WorkflowIntentPlan(
        name="Batch Customs Verification",
        description="Query customs clearance status and notify team",
        intent="Automates batch tracking of container status across portal and IM",
        steps=[
            WorkflowPlanStep(
                step_id="s1",
                title="Fetch bill of lading ID",
                description="Query recent tracking ID from Excel roster",
                target_app="Excel",
                variables_used=["tracking_id"],
            ),
            WorkflowPlanStep(
                step_id="s2",
                title="Submit search on portal",
                description="Navigate to customs portal and submit query with {{tracking_id}}",
                tool_hint="browser_navigate_tool",
                target_app="Chrome",
                variables_used=["tracking_id"],
            ),
        ],
        variables={"tracking_id": "Target container tracking identifier"},
        allowed_tools=["browser_navigate_tool", "http_request", "shell_execute"],
    )

    markdown = compile_workflow_plan_to_skill_markdown(plan)

    assert "name: batch-customs-verification" in markdown
    assert "description: Query customs clearance status and notify team" in markdown
    assert "version: 1.0.0" in markdown
    assert "allowed-tools: browser_navigate_tool http_request shell_execute" in markdown
    assert "# Batch Customs Verification" in markdown
    assert "## Parameters & Variables" in markdown
    assert "- `{{tracking_id}}`: Target container tracking identifier" in markdown
    assert "### 1. Fetch bill of lading ID (Target: Excel)" in markdown
    assert "### 2. Submit search on portal (Target: Chrome)" in markdown
    assert "- **Suggested Tool**: `browser_navigate_tool`" in markdown
    assert "## Guidelines & Fallback" in markdown


def test_workflow_compiler_validation() -> None:
    valid_plan = WorkflowIntentPlan(
        name="Valid Workflow",
        description="A valid description",
        intent="Do something useful",
        steps=[
            WorkflowPlanStep(
                step_id="s1",
                title="Step 1",
                description="Detail 1",
            )
        ],
    )
    assert WorkflowSkillCompiler.validate_plan(valid_plan) == []

    invalid_plan = WorkflowIntentPlan(
        name="",
        description="",
        intent="",
        steps=[],
    )
    errors = WorkflowSkillCompiler.validate_plan(invalid_plan)
    assert len(errors) >= 2
    assert any("name" in e.lower() for e in errors)
    assert any("step" in e.lower() for e in errors)
