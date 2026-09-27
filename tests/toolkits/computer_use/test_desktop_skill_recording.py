"""Tests for Desktop Workflow Skill Recording & Synthesizer in myrm_agent_harness."""

from __future__ import annotations

from myrm_agent_harness.toolkits.computer_use.recording import (
    DesktopRecordedEvent,
    RecordedActionType,
    cluster_and_debounce_events,
    detect_tool_lifting_candidates,
    extract_parameter_slots,
    synthesize_desktop_skill_draft,
)


def test_cluster_and_debounce_events() -> None:
    events = [
        DesktopRecordedEvent(
            seq=1,
            action=RecordedActionType.WINDOW_FOCUS.value,
            app_name="Excel",
            window_title="Book1",
        ),
        DesktopRecordedEvent(
            seq=2,
            action=RecordedActionType.WINDOW_FOCUS.value,
            app_name="Excel",
            window_title="Book1",
        ),
        DesktopRecordedEvent(
            seq=3,
            action=RecordedActionType.TYPE.value,
            app_name="Excel",
            dref_id="@dref:10",
            value="Hello ",
        ),
        DesktopRecordedEvent(
            seq=4,
            action=RecordedActionType.TYPE.value,
            app_name="Excel",
            dref_id="@dref:10",
            value="World",
        ),
    ]

    clustered = cluster_and_debounce_events(events)
    assert len(clustered) == 2
    assert clustered[0].action == RecordedActionType.WINDOW_FOCUS.value
    assert clustered[1].action == RecordedActionType.TYPE.value
    assert clustered[1].value == "Hello World"
    assert clustered[1].seq == 2


def test_detect_tool_lifting_candidates() -> None:
    events = [
        DesktopRecordedEvent(
            seq=1,
            action=RecordedActionType.TYPE.value,
            app_name="iTerm2",
            value="git status && git pull",
        ),
        DesktopRecordedEvent(
            seq=2,
            action=RecordedActionType.TYPE.value,
            app_name="TextEdit",
            value="This is a long content to be saved to a file",
        ),
    ]

    candidates = detect_tool_lifting_candidates(events)
    assert len(candidates) == 2
    assert candidates[0].lifted_tool == "bash_code_execute_tool"
    assert candidates[0].code_snippet == "git status && git pull"
    assert candidates[1].lifted_tool == "file_write_tool"


def test_extract_parameter_slots() -> None:
    events = [
        DesktopRecordedEvent(
            seq=1,
            action=RecordedActionType.TYPE.value,
            app_name="ERP Client",
            value="/Users/demo/documents/invoices_2026_08.xlsx",
        ),
        DesktopRecordedEvent(
            seq=2,
            action=RecordedActionType.TYPE.value,
            app_name="Mail",
            value="finance@corp.example.com",
        ),
    ]

    slots = extract_parameter_slots(events)
    slot_names = {s["name"] for s in slots}
    assert "input_file_path" in slot_names
    assert "recipient_email" in slot_names


def test_synthesize_desktop_skill_draft_full_flow() -> None:
    events = [
        DesktopRecordedEvent(
            seq=1,
            action=RecordedActionType.WINDOW_FOCUS.value,
            app_name="Excel",
            window_title="Monthly Report",
        ),
        DesktopRecordedEvent(
            seq=2,
            action=RecordedActionType.CLICK.value,
            app_name="Excel",
            dref_id="@dref:42",
            element_title="Export Monthly Summary",
        ),
        DesktopRecordedEvent(
            seq=3,
            action=RecordedActionType.TYPE.value,
            app_name="Terminal",
            value="python script.py --input /data/2026-08-15.csv",
        ),
    ]

    draft = synthesize_desktop_skill_draft(
        events=events,
        skill_name="monthly_report_automation",
        description="Automate export and processing of monthly summary reports",
    )

    assert draft.skill_name == "monthly_report_automation"
    assert len(draft.steps) >= 2
    assert "---" in draft.markdown_content
    assert "name: monthly_report_automation" in draft.markdown_content
    assert "## Workflow Execution Steps" in draft.markdown_content


def test_lifted_tools_are_registered_tool_names() -> None:
    """Tool lifting must elevate to real tool names, not plausible-looking placeholders.

    A lifted step is executed by name; ``shell_command`` / ``write_file`` / ``execute_code`` do
    not exist in the tool registry, so a compiled skill would reference un-callable tools.
    """
    from myrm_agent_harness.agent.tool_management.tool_layers import _TOOL_LAYERS

    events = [
        DesktopRecordedEvent(
            seq=1,
            action=RecordedActionType.TYPE.value,
            app_name="Terminal",
            value="ls -la /tmp",
        ),
        DesktopRecordedEvent(
            seq=2,
            action=RecordedActionType.TYPE.value,
            app_name="TextEdit",
            value="some longer document body",
        ),
        DesktopRecordedEvent(
            seq=3,
            action=RecordedActionType.CLICK.value,
            app_name="Microsoft Excel",
            element_title="Export",
        ),
    ]

    candidates = detect_tool_lifting_candidates(events)
    assert candidates, "these events must produce lifting candidates"

    registered = set(_TOOL_LAYERS)
    unknown = sorted({c.lifted_tool for c in candidates if c.lifted_tool not in registered})
    assert unknown == [], f"tool lifting emitted unregistered tool names: {unknown}"


def test_password_value_is_masked_in_draft_markdown() -> None:
    """A recorded secure-field entry must never appear in the generated SKILL.md."""
    events = [
        DesktopRecordedEvent(
            seq=1,
            action=RecordedActionType.TYPE.value,
            app_name="SignIn",
            element_title="Password",
            value="hunter2",
            is_password=True,
        )
    ]

    draft = synthesize_desktop_skill_draft(
        events=events,
        skill_name="secure_login_flow",
        description="Sign in and continue",
    )

    assert "hunter2" not in draft.markdown_content
    assert "***" in draft.markdown_content
