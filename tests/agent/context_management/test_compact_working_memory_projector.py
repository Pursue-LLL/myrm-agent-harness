"""单元测试：极紧凑 Working Memory 投影器、显式 Resource Loader 与超低 Harness Tax 控制套件。

[INPUT]
- CompactWorkingMemoryProjector 及相关领域契约

[OUTPUT]
- 验证显式资源预编译、最小工具暴露收缩、工作记忆紧凑投影、框架税审计节约。

[POS]
- 位于 tests/agent/context_management/test_compact_working_memory_projector.py
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
import pytest

from myrm_agent_harness.agent.context_management.harness_tax import (
    CompactWorkingMemoryProjector,
    HarnessTaxConfig,
    ToolDescriptor,
    ToolExposurePolicy,
)


def test_explicit_resource_loader_compilation() -> None:
    """验证显式 Resource Loader 运行前预编译装配，杜绝全量规则动态倾倒。"""
    projector = CompactWorkingMemoryProjector()

    bundle = projector.compile_resource_bundle(
        profile_id="coding_specialist",
        enabled_skills=["code_analysis", "test_runner"],
        custom_instructions="Focus on performance and zero any type hints.",
        prompt_template="[Task Context Template]",
    )

    assert bundle.profile_id == "coding_specialist"
    assert "code_analysis" in bundle.system_instructions
    assert "test_runner" in bundle.system_instructions
    assert "Focus on performance" in bundle.system_instructions
    assert bundle.loaded_tokens > 0
    assert bundle.active_skill_names == ["code_analysis", "test_runner"]


def test_minimal_core_tool_exposure_pareto() -> None:
    """验证 Pareto 4 工具极简暴露与非活跃工具动态收缩，削减工具 Schema 的 Harness Tax。"""
    config = HarnessTaxConfig(
        max_active_tools=4,
        exposure_policy=ToolExposurePolicy.MINIMAL_CORE_ONLY,
    )
    projector = CompactWorkingMemoryProjector(config=config)

    tools = [
        ToolDescriptor(name="read_file", description="Read file", schema_tokens_estimate=150, is_core=True),
        ToolDescriptor(name="write_file", description="Write file", schema_tokens_estimate=200, is_core=True),
        ToolDescriptor(name="edit_file", description="Edit file", schema_tokens_estimate=220, is_core=True),
        ToolDescriptor(name="bash_run", description="Execute bash", schema_tokens_estimate=300, is_core=True),
        ToolDescriptor(name="search_web", description="Web search", schema_tokens_estimate=180, category="research"),
        ToolDescriptor(name="git_push", description="Git push", schema_tokens_estimate=160, category="git"),
        ToolDescriptor(name="db_migrate", description="Migrate DB", schema_tokens_estimate=250, category="db"),
        ToolDescriptor(name="send_email", description="Send email", schema_tokens_estimate=140, category="notification"),
    ]

    # 1. 最小核心暴露：严格收敛为 4 个核心工具
    active_tools = projector.filter_active_tools(tools)
    assert len(active_tools) == 4
    active_names = [t.name for t in active_tools]
    assert active_names == ["read_file", "write_file", "edit_file", "bash_run"]

    # 2. 意图自适应策略：进入 research 阶段时动态暴露研究工具
    config_adaptive = HarnessTaxConfig(
        max_active_tools=4,
        exposure_policy=ToolExposurePolicy.INTENT_ADAPTIVE,
    )
    projector_adaptive = CompactWorkingMemoryProjector(config=config_adaptive)
    adaptive_tools = projector_adaptive.filter_active_tools(tools, current_phase="research")
    adaptive_names = [t.name for t in adaptive_tools]
    assert "search_web" in adaptive_names
    assert "read_file" in adaptive_names


def test_compact_working_memory_projection() -> None:
    """验证将底层完整历史投影为极紧凑的当前 Working Memory 视图与目标锚点注入。"""
    config = HarnessTaxConfig(
        recent_turns_retention=1,
        enable_active_branch_projection=True,
    )
    projector = CompactWorkingMemoryProjector(config=config)

    long_filler = "Verbose intermediate discussion and brainstorming text without key decisions. " * 10
    messages = [
        SystemMessage(content="System instruction base"),
        HumanMessage(content=f"Initial goal: migrate database schema. {long_filler}"),
        AIMessage(content=f"Plan confirmed: start table migration. {long_filler}"),
        HumanMessage(content=f"Reviewing columns. {long_filler}"),
        AIMessage(content=f"Columns inspected successfully. {long_filler}"),
        # 最近一轮受保护
        HumanMessage(content="Proceed with applying indices"),
        AIMessage(content="Applying indices now"),
    ]

    view = projector.project_working_memory(
        session_id="sess_tax_1",
        raw_messages=messages,
        current_goal="Apply database index migration",
    )

    assert view.original_tokens > view.projected_tokens
    assert view.harness_tax_saved_tokens > 0
    assert view.reduction_ratio > 0.3

    # 验证目标锚点显式注入
    assert any("[Current Active Goal Milestone]" in str(m.content) for m in view.projected_messages)
    # 验证历史中间闲聊被折叠为紧凑投影节点
    assert any("[Compact Working Memory Projection]" in str(m.content) for m in view.projected_messages)
    # 验证最新活跃轮次完整保留
    assert view.projected_messages[-2].content == "Proceed with applying indices"
    assert view.projected_messages[-1].content == "Applying indices now"


def test_harness_tax_audit_report() -> None:
    """验证框架税开销审计与节约比例计算。"""
    projector = CompactWorkingMemoryProjector()

    raw_tools = [
        ToolDescriptor(name="t1", description="", schema_tokens_estimate=300),
        ToolDescriptor(name="t2", description="", schema_tokens_estimate=300),
        ToolDescriptor(name="t3", description="", schema_tokens_estimate=300),
        ToolDescriptor(name="t4", description="", schema_tokens_estimate=300),
        ToolDescriptor(name="t5", description="", schema_tokens_estimate=300),
        ToolDescriptor(name="t6", description="", schema_tokens_estimate=300),
    ]
    projected_tools = raw_tools[:3]

    report = projector.audit_harness_tax(
        raw_tools=raw_tools,
        projected_tools=projected_tools,
        original_context_tokens=1500,
        projected_context_tokens=600,
    )

    assert report.base_tool_schema_tokens == 1800
    assert report.projected_tool_schema_tokens == 900
    assert report.tool_tokens_saved == 900
    assert report.context_tokens_saved == 900
    assert report.total_tokens_saved == 1800
    assert report.estimated_cost_savings_pct > 50.0
