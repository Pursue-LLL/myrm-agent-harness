"""System Prompt Guidance 验证测试

验证System Prompt中包含必要的subagent结果查询指导
"""

import json

from myrm_agent_harness.agent.sub_agents.prompts import (
    DEFAULT_COORDINATOR_PROMPT,
    DEFAULT_VERIFIER_PROMPT,
    DEFAULT_WORKER_PROMPT,
)


def test_system_prompt_contains_active_query_guidance():
    """验证System Prompt包含主动查询async subagent结果的指导"""
    prompt = DEFAULT_COORDINATOR_PROMPT

    # 关键词验证：必须明确告知LLM要主动查询
    assert "subagent_control_tool" in prompt, "System Prompt must mention subagent_control_tool"
    assert "MUST" in prompt or "must" in prompt, "System Prompt must use imperative language"

    # 验证关键概念存在
    keywords = [
        "async",  # 异步概念
        "wait=false",  # async mode标识
        "stored in memory",  # 结果存储方式
        "NOT",  # 强调不是自动注入
    ]

    for keyword in keywords:
        assert keyword in prompt, f"System Prompt must contain keyword: {keyword}"

    print("\n System Prompt Guidance Validation PASSED:")
    print("  - Mentions subagent_control_tool ")
    print("  - Uses imperative language (MUST/must) ")
    print("  - Contains key concepts (async, wait=false, NOT injected) ")


def test_system_prompt_explains_cache_rationale():
    """验证System Prompt解释了Cache保护的原因"""
    prompt = DEFAULT_COORDINATOR_PROMPT

    # 应该提到cache相关的概念
    cache_keywords = ["cache", "Cache", "prompt cache", "Prompt Cache"]
    has_cache_mention = any(kw in prompt for kw in cache_keywords)

    assert has_cache_mention, "System Prompt should explain why this design preserves cache"

    print("\n Cache Rationale Explanation PASSED")


def test_system_prompt_contains_delegation_guardrails():
    """Verify DEFAULT_COORDINATOR_PROMPT contains anti-abuse delegation guardrails."""
    prompt = DEFAULT_COORDINATOR_PROMPT

    assert "2+ independent parallel" in prompt, "Must include decomposability criterion for delegation"
    assert "sequential dependencies" in prompt, "Must warn against forcing sequential tasks into parallel workers"
    assert "Ultra-simple actions" in prompt, "Must mention ultra-simple actions should not be delegated"
    assert "Do NOT spawn a worker" in prompt, "Must have explicit Do NOT spawn section"
    assert 'delegate_task_tool(task="Run the test suite"' in prompt, "Must include wrong delegation example"
    assert 'bash("pytest tests/")' in prompt, "Must include right direct-execution example"


def test_system_prompt_token_optimized():
    """验证System Prompt经过Token优化但保留核心指导"""
    prompt = DEFAULT_COORDINATOR_PROMPT

    # 核心指导必须保留
    core_guidance = [
        "subagent_control_tool",
        "async",
        "wait=false",
    ]

    for guidance in core_guidance:
        assert guidance in prompt, f"Core guidance '{guidance}' must be preserved"

    # 检查Token优化：不应有过度冗长的重复
    lines = prompt.split("\n")
    non_empty_lines = [line.strip() for line in lines if line.strip()]

    # 简单启发式：每行平均长度不应过长（Token优化的体现）
    avg_line_length = sum(len(line) for line in non_empty_lines) / max(len(non_empty_lines), 1)
    assert avg_line_length < 200, (
        f"Average line length {avg_line_length:.0f} chars suggests verbose prompts. "
        "Consider further token optimization."
    )

    print("\n Token Optimization Validation PASSED")
    print("  - Core guidance preserved ")
    print(f"  - Average line length: {avg_line_length:.0f} chars ")


# ---------------------------------------------------------------------------
# DEFAULT_VERIFIER_PROMPT tests
# ---------------------------------------------------------------------------


class TestVerifierPrompt:
    """Verify DEFAULT_VERIFIER_PROMPT contains all required modules."""

    def test_importable(self):
        assert isinstance(DEFAULT_VERIFIER_PROMPT, str)
        assert len(DEFAULT_VERIFIER_PROMPT) > 500

    def test_adversarial_mindset(self):
        assert "red team" in DEFAULT_VERIFIER_PROMPT
        assert "try to break it" in DEFAULT_VERIFIER_PROMPT
        assert "last 20%" in DEFAULT_VERIFIER_PROMPT

    def test_anti_laziness_rules(self):
        laziness_patterns = [
            "The code looks correct",
            "The implementer's tests pass",
            "This would take too long",
            "Run it",
        ]
        for pat in laziness_patterns:
            assert pat in DEFAULT_VERIFIER_PROMPT, f"Anti-laziness pattern missing: {pat}"

    def test_verification_by_change_type(self):
        change_types = [
            "Code / Logic changes",
            "Frontend / UI changes",
            "API changes",
            "Bug fixes",
            "Database / Migration changes",
            "Performance changes",
            "Security changes",
            "Refactoring",
            "Configuration changes",
            "Algorithm / Data processing",
        ]
        for ct in change_types:
            assert ct in DEFAULT_VERIFIER_PROMPT, f"Change type missing: {ct}"

    def test_cross_validation(self):
        assert "Cross-Validation" in DEFAULT_VERIFIER_PROMPT
        assert "multiple independent paths" in DEFAULT_VERIFIER_PROMPT

    def test_severity_classification(self):
        for level in ("CRITICAL", "MAJOR", "MINOR", "INFO"):
            assert level in DEFAULT_VERIFIER_PROMPT, f"Severity level missing: {level}"

    def test_coverage_completeness(self):
        assert "Coverage Completeness" in DEFAULT_VERIFIER_PROMPT
        assert "go back and fill the gap" in DEFAULT_VERIFIER_PROMPT

    def test_json_report_format(self):
        assert '"verdict"' in DEFAULT_VERIFIER_PROMPT
        assert '"findings"' in DEFAULT_VERIFIER_PROMPT
        assert '"severity"' in DEFAULT_VERIFIER_PROMPT
        assert '"evidence"' in DEFAULT_VERIFIER_PROMPT
        assert '"confidence"' in DEFAULT_VERIFIER_PROMPT

    def test_json_example_is_valid(self):
        """The JSON example in the prompt must be syntactically valid."""
        start = DEFAULT_VERIFIER_PROMPT.index("```json")
        end = DEFAULT_VERIFIER_PROMPT.index("```", start + 7)
        json_block = DEFAULT_VERIFIER_PROMPT[start + 7 : end].strip()
        parsed = json.loads(json_block)
        assert "verdict" in parsed
        assert "findings" in parsed
        assert isinstance(parsed["findings"], list)

    def test_verdict_rules(self):
        assert "FAIL" in DEFAULT_VERIFIER_PROMPT
        assert "PASS" in DEFAULT_VERIFIER_PROMPT
        assert "false PASS" in DEFAULT_VERIFIER_PROMPT

    def test_readonly_constraint(self):
        assert "read-only" in DEFAULT_VERIFIER_PROMPT
        assert "Do not create, edit, or delete" in DEFAULT_VERIFIER_PROMPT

    def test_no_subagent_constraint(self):
        assert "do not spawn subagents" in DEFAULT_VERIFIER_PROMPT.lower()

    def test_evidence_required(self):
        assert "evidence" in DEFAULT_VERIFIER_PROMPT.lower()
        assert "concrete" in DEFAULT_VERIFIER_PROMPT.lower()


# ---------------------------------------------------------------------------
# DEFAULT_WORKER_PROMPT tests
# ---------------------------------------------------------------------------


class TestWorkerPrompt:
    """Verify DEFAULT_WORKER_PROMPT contains essential worker guidance."""

    def test_importable(self):
        assert isinstance(DEFAULT_WORKER_PROMPT, str)
        assert len(DEFAULT_WORKER_PROMPT) > 100

    def test_core_guidelines(self):
        assert "Follow the spec exactly" in DEFAULT_WORKER_PROMPT
        assert "Self-verify" in DEFAULT_WORKER_PROMPT

    def test_report_structure(self):
        assert "Commit hash" in DEFAULT_WORKER_PROMPT or "commit hash" in DEFAULT_WORKER_PROMPT.lower()


# ---------------------------------------------------------------------------
# All three prompts cross-check
# ---------------------------------------------------------------------------


class TestPromptModuleCoverage:
    """Verify all three prompt constants are distinct and non-empty."""

    def test_all_prompts_non_empty(self):
        for name, prompt in [
            ("COORDINATOR", DEFAULT_COORDINATOR_PROMPT),
            ("WORKER", DEFAULT_WORKER_PROMPT),
            ("VERIFIER", DEFAULT_VERIFIER_PROMPT),
        ]:
            assert prompt.strip(), f"{name} prompt must not be empty"

    def test_all_prompts_distinct(self):
        prompts = [DEFAULT_COORDINATOR_PROMPT, DEFAULT_WORKER_PROMPT, DEFAULT_VERIFIER_PROMPT]
        assert len(set(prompts)) == 3, "All three prompts must be distinct"

    def test_verifier_is_readonly_coordinator_is_not(self):
        """Verifier must be read-only, coordinator must have write capability."""
        assert "read-only" in DEFAULT_VERIFIER_PROMPT.lower()
        assert "delegate_task_tool" in DEFAULT_COORDINATOR_PROMPT
