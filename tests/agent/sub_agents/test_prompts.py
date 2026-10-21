"""Tests for sub_agents/prompts.py — verify prompt constants are importable,
non-empty, and contain required anti-conformity directives."""

from myrm_agent_harness.agent.sub_agents.prompts import (
    DEFAULT_COORDINATOR_PROMPT,
    DEFAULT_VERIFIER_PROMPT,
    DEFAULT_WORKER_PROMPT,
)


class TestPromptConstants:
    def test_coordinator_prompt_not_empty(self) -> None:
        assert isinstance(DEFAULT_COORDINATOR_PROMPT, str)
        assert len(DEFAULT_COORDINATOR_PROMPT) > 100

    def test_worker_prompt_not_empty(self) -> None:
        assert isinstance(DEFAULT_WORKER_PROMPT, str)
        assert len(DEFAULT_WORKER_PROMPT) > 50

    def test_verifier_prompt_not_empty(self) -> None:
        assert isinstance(DEFAULT_VERIFIER_PROMPT, str)
        assert len(DEFAULT_VERIFIER_PROMPT) > 100

    def test_coordinator_contains_key_sections(self) -> None:
        assert "delegate_task_tool" in DEFAULT_COORDINATOR_PROMPT
        assert "subagent_control_tool" in DEFAULT_COORDINATOR_PROMPT
        assert "parallel" in DEFAULT_COORDINATOR_PROMPT.lower()

    def test_verifier_contains_anti_laziness(self) -> None:
        assert "Anti-Laziness" in DEFAULT_VERIFIER_PROMPT
        assert "CRITICAL" in DEFAULT_VERIFIER_PROMPT
        assert "MAJOR" in DEFAULT_VERIFIER_PROMPT
        assert "read-only" in DEFAULT_VERIFIER_PROMPT.lower()

    def test_worker_contains_guidelines(self) -> None:
        assert "Guidelines" in DEFAULT_WORKER_PROMPT
        assert "self-verify" in DEFAULT_WORKER_PROMPT.lower() or "Self-verify" in DEFAULT_WORKER_PROMPT


class TestAntiConformityDirectives:
    """Verify that anti-conformity directives from B-01 are present in all
    three prompt templates. These directives defend against the 'bystander
    effect' documented in arXiv:2605.10698."""

    def test_worker_has_evidence_priority_section(self) -> None:
        assert "Evidence Priority" in DEFAULT_WORKER_PROMPT

    def test_worker_evidence_over_spec(self) -> None:
        prompt_lower = DEFAULT_WORKER_PROMPT.lower()
        assert "objective evidence" in prompt_lower
        assert "report the contradiction" in prompt_lower

    def test_worker_has_anti_pattern_table(self) -> None:
        assert "Wrong response" in DEFAULT_WORKER_PROMPT
        assert "Correct response" in DEFAULT_WORKER_PROMPT

    def test_worker_spec_contradiction_example(self) -> None:
        assert "Spec says X, but tests show Y" in DEFAULT_WORKER_PROMPT

    def test_coordinator_has_critical_synthesis(self) -> None:
        assert "Critical Synthesis" in DEFAULT_COORDINATOR_PROMPT

    def test_coordinator_consensus_not_correctness(self) -> None:
        assert "Consensus" in DEFAULT_COORDINATOR_PROMPT
        assert "correctness" in DEFAULT_COORDINATOR_PROMPT

    def test_coordinator_shared_blind_spots(self) -> None:
        assert "blind spots" in DEFAULT_COORDINATOR_PROMPT.lower()

    def test_coordinator_has_trap_table(self) -> None:
        assert "False consensus" in DEFAULT_COORDINATOR_PROMPT
        assert "Inherited error" in DEFAULT_COORDINATOR_PROMPT

    def test_verifier_has_consensus_resistance_row(self) -> None:
        assert "All checks passed, everything looks good" in DEFAULT_VERIFIER_PROMPT

    def test_verifier_red_flag_not_green_light(self) -> None:
        assert "red flag, not a green light" in DEFAULT_VERIFIER_PROMPT

    def test_verifier_anti_laziness_table_has_seven_rows(self) -> None:
        """Anti-Laziness table should have exactly 7 data rows (6 original + 1 new)."""
        table_section = DEFAULT_VERIFIER_PROMPT.split("Anti-Laziness Rules")[1]
        table_section = table_section.split("## 3.")[0]
        data_rows = [
            line
            for line in table_section.strip().split("\n")
            if line.startswith("|") and "tempted" not in line and "---" not in line
        ]
        assert len(data_rows) == 7, f"Expected 7 data rows, got {len(data_rows)}"

    def test_all_prompts_are_static(self) -> None:
        """Anti-conformity content must be static text (no dynamic templates)
        to preserve prompt prefix caching."""
        for prompt in (DEFAULT_WORKER_PROMPT, DEFAULT_COORDINATOR_PROMPT, DEFAULT_VERIFIER_PROMPT):
            sections_to_check = []
            if "Evidence Priority" in prompt:
                sections_to_check.append(prompt.split("Evidence Priority")[1].split("## On")[0])
            if "Critical Synthesis" in prompt:
                sections_to_check.append(prompt.split("Critical Synthesis")[1].split("## 4.")[0])
            for section in sections_to_check:
                assert "{" not in section or "{{" in section, (
                    "Anti-conformity sections must not contain template variables"
                )
