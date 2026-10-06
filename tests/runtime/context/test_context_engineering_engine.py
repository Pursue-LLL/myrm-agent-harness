"""Comprehensive tests for Context Engineering Engine, ReAct Trap Remediation, and ACI Tool Design."""

from __future__ import annotations

from myrm_agent_harness.runtime.context.aci_tool_contract_linter import (
    ACIToolContractLinter,
)
from myrm_agent_harness.runtime.context.context_engineering_pipeline import (
    ContextEngineeringPipeline,
)
from myrm_agent_harness.runtime.context.context_engineering_types import (
    ACIToolContract,
    ACIToolParam,
    ContextRemediationConfig,
    NoteType,
    ScenarioType,
)
from myrm_agent_harness.runtime.context.context_virtual_memory import (
    ContextVirtualMemoryManager,
)
from myrm_agent_harness.runtime.context.react_trap_remediator import (
    ReActTrapRemediator,
)


def test_post_consumption_tool_folding() -> None:
    """Verify bulky historical tool results are folded while recent ones are preserved."""
    config = ContextRemediationConfig(
        fold_tool_length_threshold=100,
        keep_recent_raw_tool_turns=1,
    )
    remediator = ReActTrapRemediator(config)

    messages: list[dict[str, str]] = [
        {"role": "user", "content": "Fetch market data"},
        {
            "role": "tool",
            "name": "web_search",
            "content": "A" * 600,  # Old bulky tool result -> should fold
        },
        {"role": "assistant", "content": "I see the market data. Now getting stock price."},
        {
            "role": "tool",
            "name": "get_stock",
            "content": "B" * 500,  # Most recent tool result -> must NOT fold
        },
        {"role": "assistant", "content": "Analysis complete."},
    ]

    res = remediator.remediate(messages)
    assert res.folded_tool_count == 1
    assert "folded payload" in res.processed_messages[1]["content"]
    assert "B" * 500 in res.processed_messages[3]["content"]
    assert res.saved_chars_estimate > 400


def test_prune_failed_trajectories() -> None:
    """Verify failed retry stack traces are pruned after subsequent success."""
    remediator = ReActTrapRemediator()

    messages: list[dict[str, str]] = [
        {"role": "user", "content": "Read configuration file"},
        {
            "role": "tool",
            "name": "read_file",
            "content": (
                "Traceback (most recent call last):\n"
                "  File 'agent.py', line 42, in run\n"
                "FileNotFoundError: [Errno 2] No such file or directory: 'config.json'\n"
                + "X" * 150
            ),
        },
        {"role": "assistant", "content": "Let me try reading 'config.yaml' instead."},
        {
            "role": "tool",
            "name": "read_file",
            "content": "database_url: postgres://localhost:5432/app",
        },
        {"role": "assistant", "content": "Configuration loaded successfully."},
    ]

    res = remediator.remediate(messages)
    assert res.pruned_failed_trajectories == 1
    assert "Tool Recovery: Prior error pruned after subsequent success" in res.processed_messages[1]["content"]
    assert "Traceback" not in res.processed_messages[1]["content"]


def test_thought_decay() -> None:
    """Verify older thoughts decay while recent thought chains remain intact."""
    config = ContextRemediationConfig(max_active_thoughts_turns=1)
    remediator = ReActTrapRemediator(config)

    messages: list[dict[str, str]] = [
        {"role": "user", "content": "Start project step 1"},
        {
            "role": "assistant",
            "content": "<thought>Deep analysis of step 1 architecture...</thought>Step 1 done.",
        },
        {"role": "user", "content": "Proceed to step 2"},
        {
            "role": "assistant",
            "content": "<thought>Current active thought for step 2.</thought>Step 2 done.",
        },
    ]

    res = remediator.remediate(messages)
    assert res.decayed_thoughts_count == 1
    assert 'status="decayed"' in res.processed_messages[1]["content"]
    assert "Current active thought for step 2." in res.processed_messages[3]["content"]


def test_rule_reanchoring() -> None:
    """Verify critical constraints are re-anchored at tail after long turn intervals."""
    config = ContextRemediationConfig(reanchor_turn_interval=4)
    remediator = ReActTrapRemediator(config)

    messages: list[dict[str, str]] = [
        {"role": "user", "content": "Turn 1"},
        {"role": "assistant", "content": "Reply 1"},
        {"role": "user", "content": "Turn 2"},
        {"role": "assistant", "content": "Reply 2"},
        {"role": "user", "content": "Turn 3 latest instruction"},
    ]

    rules = ["Do not delete production tables.", "Strictly format all numbers as cents."]
    res = remediator.remediate(messages, core_rules=rules)

    assert res.reanchored is True
    assert "<anchored_system_rules>" in res.processed_messages[4]["content"]
    assert "Do not delete production tables." in res.processed_messages[4]["content"]


def test_aci_tool_contract_linter() -> None:
    """Verify static linting catches vague names, prohibited Any types, and semantic overlaps."""
    linter = ACIToolContractLinter()

    tools = [
        ACIToolContract(
            name="run",  # Vague name
            description="Executes arbitrary things",
            parameters=[
                ACIToolParam(name="arg1", type_str="Any", description=""),  # Any type + empty desc
            ],
        ),
        ACIToolContract(
            name="fetch_webpage_content",
            description="Fetches raw HTML and documents from public web URLs via HTTP request.",
            parameters=[
                ACIToolParam(name="url", type_str="str", description="Target URL"),
            ],
        ),
        ACIToolContract(
            name="download_web_page_html",
            description="Fetches raw HTML and documents from public web URLs via HTTP request.",
            parameters=[
                ACIToolParam(name="url", type_str="str", description="Target URL"),
            ],
        ),
    ]

    report = linter.lint_tools(tools)
    assert report.passed is False
    codes = {issue.rule_code for issue in report.issues}
    assert "ACI_TOOL_NAME_TOO_VAGUE" in codes
    assert "ACI_PARAM_ANY_TYPE_PROHIBITED" in codes
    assert "ACI_TOOL_SEMANTIC_OVERLAP" in codes


def test_goldilocks_prompt_linter() -> None:
    """Verify Goldilocks Zone prompts require structured XML partitions."""
    linter = ACIToolContractLinter()

    # Incomplete prompt
    bad_prompt = "You are an assistant. Please answer questions accurately."
    report_bad = linter.lint_goldilocks_prompt(bad_prompt)
    assert report_bad.passed is False
    assert any(i.rule_code == "GOLDILOCKS_MISSING_XML_PARTITION" for i in report_bad.issues)

    # Valid Goldilocks prompt
    good_prompt = (
        "<role>Expert Architect</role>\n"
        "<principles>1. High performance. 2. 0 Any type hints. 3. Zero regressions.</principles>\n"
        "<boundaries>Never delete databases. Require confirmation on destructive mutations.</boundaries>\n"
        "<tools_guidance>Use ripgrep for fast searching and read_file before writing code.</tools_guidance>"
    )
    report_good = linter.lint_goldilocks_prompt(good_prompt)
    assert report_good.passed is True
    assert len(report_good.issues) == 0


def test_context_virtual_memory_paging_and_coala() -> None:
    """Verify RAM vs Disk paging and JIT swap-in of CoALA structured notes."""
    vm = ContextVirtualMemoryManager(scenario=ScenarioType.GENERAL_OFFICE_CODING)

    vm.add_note(
        note_id="n1",
        note_type=NoteType.DECISION,
        title="Database Choice",
        content="Decided to use SQLite for single-node embedded storage.",
        turn_index=2,
        tags={"database", "sqlite"},
    )
    vm.add_note(
        note_id="n2",
        note_type=NoteType.PROGRESS,
        title="Auth Implementation",
        content="Completed JWT middleware.",
        turn_index=4,
        tags={"auth", "jwt"},
    )

    assert len(vm.get_ram_notes()) == 2
    xml_rendered = vm.render_active_memory_xml()
    assert "<structured_memory_notes>" in xml_rendered
    assert 'type="decision"' in xml_rendered

    # Page out n1 to disk
    assert vm.page_out("n1") is True
    assert len(vm.get_ram_notes()) == 1
    assert len(vm.get_disk_notes()) == 1

    # JIT search page in
    retrieved = vm.page_in_by_query("sqlite database")
    assert len(retrieved) == 1
    assert retrieved[0].note_id == "n1"
    assert len(vm.get_ram_notes()) == 2


def test_context_engineering_pipeline_end_to_end() -> None:
    """Verify end-to-end context preparation with ReAct remediation and note integration."""
    pipeline = ContextEngineeringPipeline(
        scenario=ScenarioType.GENERAL_OFFICE_CODING,
        custom_rules=["Never emit Any types in Python."],
    )

    pipeline.vm_manager.add_note(
        note_id="n_strat",
        note_type=NoteType.STRATEGY,
        title="Refactor Plan",
        content="Extract sub-processors to keep files under 400 lines.",
        turn_index=1,
    )

    messages: list[dict[str, str]] = [
        {"role": "system", "content": "You are a senior engineer."},
        {"role": "user", "content": "Begin refactor."},
        {"role": "tool", "content": "Detailed log " * 80},  # Bulky tool result
        {"role": "assistant", "content": "Completed phase 1."},
        {"role": "tool", "content": "Short status ok"},
        {"role": "user", "content": "Next phase please."},
    ]

    res = pipeline.prepare_context(messages)
    assert res.folded_tool_count == 1
    assert "<structured_memory_notes>" in res.processed_messages[0]["content"]
    assert "Refactor Plan" in res.processed_messages[0]["content"]
