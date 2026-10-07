"""Unified Context Engineering Pipeline orchestrating ReAct remediation, ACI linting, and virtual memory.

Coordinates:
- ReAct Trap Remediation (Observation folding, Rule re-anchoring, Error pruning, Thought decay)
- Virtual Memory & CoALA 4-Quadrant Note integration
- ACI Tool and Goldilocks Zone static auditing

[INPUT]
- runtime.context.aci_tool_contract_linter::ACIToolContractLinter (POS: ACI (Agent-Computer Interface) tool
  contract and Goldilocks Zone prompt linter.)
- runtime.context.context_engineering_types::ACILintReport, ACIToolContract, RemediationResult, ScenarioType
  (POS: Context engineering types and data protocols for ReAct trap remediation and ACI design.)
- runtime.context.context_virtual_memory::ContextVirtualMemoryManager (POS: Context Virtual Memory Manager
  and CoALA 4-Quadrant Structured Note-Taking Engine.)
- runtime.context.react_trap_remediator::ReActTrapRemediator (POS: ReAct trap remediation engine for
  production LLM Agent contexts.)

[OUTPUT]
- ContextEngineeringPipeline: Orchestrator providing holistic context engineering for LLM Agent runs.

[POS]
Unified Context Engineering Pipeline orchestrating ReAct remediation, ACI linting, and virtual memory.
"""

from __future__ import annotations

from myrm_agent_harness.runtime.context.aci_tool_contract_linter import (
    ACIToolContractLinter,
)
from myrm_agent_harness.runtime.context.context_engineering_types import (
    ACILintReport,
    ACIToolContract,
    RemediationResult,
    ScenarioType,
)
from myrm_agent_harness.runtime.context.context_virtual_memory import (
    ContextVirtualMemoryManager,
)
from myrm_agent_harness.runtime.context.react_trap_remediator import (
    ReActTrapRemediator,
)


class ContextEngineeringPipeline:
    """Orchestrator providing holistic context engineering for LLM Agent runs."""

    def __init__(
        self,
        scenario: ScenarioType = ScenarioType.GENERAL_OFFICE_CODING,
        custom_rules: list[str] | None = None,
    ) -> None:
        self.vm_manager = ContextVirtualMemoryManager(scenario=scenario)
        self.remediator = ReActTrapRemediator(config=self.vm_manager.profile.config)
        self.linter = ACIToolContractLinter()
        self.core_rules = custom_rules or list(self.vm_manager.profile.core_rules)

    def prepare_context(
        self,
        messages: list[dict[str, str]],
        inject_memory: bool = True,
    ) -> RemediationResult:
        """Run ReAct trap remediation pipeline and inject active memory notes."""
        result = self.remediator.remediate(
            messages=messages,
            core_rules=self.core_rules,
        )

        if not inject_memory:
            return result

        memory_xml = self.vm_manager.render_active_memory_xml()
        if not memory_xml or not result.processed_messages:
            return result

        # Inject memory block into the system message or first user message
        msgs = [dict(m) for m in result.processed_messages]
        target_idx = -1
        for idx, m in enumerate(msgs):
            if m.get("role") == "system":
                target_idx = idx
                break

        if target_idx == -1 and msgs:
            target_idx = 0

        if target_idx != -1:
            curr = msgs[target_idx].get("content", "")
            if "<structured_memory_notes>" not in curr:
                msgs[target_idx]["content"] = f"{curr}\n\n{memory_xml}"

        return RemediationResult(
            processed_messages=msgs,
            folded_tool_count=result.folded_tool_count,
            pruned_failed_trajectories=result.pruned_failed_trajectories,
            reanchored=result.reanchored,
            decayed_thoughts_count=result.decayed_thoughts_count,
            saved_chars_estimate=result.saved_chars_estimate,
        )

    def audit_environment(
        self,
        system_prompt: str,
        tools: list[ACIToolContract],
    ) -> tuple[ACILintReport, ACILintReport]:
        """Perform static ACI tool contract checks and Goldilocks Zone prompt inspection."""
        prompt_report = self.linter.lint_goldilocks_prompt(system_prompt)
        tool_report = self.linter.lint_tools(tools)
        return prompt_report, tool_report
