# [POS] tests/toolkits/memory/test_memory_self_verification.py
# [INPUT] pytest, runner, types
# [OUTPUT] test_in_place_mutation_probe, test_zero_lexical_probe, test_procedural_anti_drop, test_full_diagnostic_suite


from myrm_agent_harness.toolkits.memory.self_verification import (
    MemorySelfVerificationRunner,
    VerificationHealthGrade,
)


def test_in_place_mutation_probe_success_and_failure() -> None:
    """Test in-place mutation assertion: single latest record vs duplicate conflict."""
    runner = MemorySelfVerificationRunner()

    # 1. Standard success scenario: mutation supersedes old fact
    res_success = runner.run_in_place_mutation_probe(
        entity_key="monthly_income_target",
        initial_fact="目标是月入1万人民币",
        updated_fact="目标改成月入3万人民币",
    )
    assert res_success.success is True
    assert res_success.retained_fact_count == 1
    assert res_success.is_latest_retained is True
    assert res_success.residual_conflict_count == 0

    # 2. Defective scenario: broken store appends instead of updating, leaving duplicate contradiction
    def defective_append_mutator(entity_key: str, initial: str, updated: str) -> list[str]:
        return [initial, updated]

    res_fail = runner.run_in_place_mutation_probe(
        entity_key="monthly_income_target",
        initial_fact="目标是月入1万人民币",
        updated_fact="目标改成月入3万人民币",
        store_mutator=defective_append_mutator,
    )
    assert res_fail.success is False
    assert res_fail.retained_fact_count == 2
    assert res_fail.is_latest_retained is False
    assert res_fail.residual_conflict_count == 1


def test_zero_lexical_probe_canonical_pair_and_overlap_detection() -> None:
    """Test zero lexical overlap calculation and pure semantic recall assertion."""
    runner = MemorySelfVerificationRunner()

    # Canonical pair: zero lexical overlap ("靠什么赚钱" vs "在做 AI 教学、AI 工具、SEO")
    res_zero = runner.run_zero_lexical_probe(
        query="靠什么赚钱",
        memory_text="在做 AI 教学、AI 工具、SEO",
    )
    assert res_zero.is_zero_overlap is True
    assert res_zero.lexical_overlap_ratio == 0.0
    assert res_zero.cosine_similarity >= 0.70
    assert res_zero.recalled is True

    # Overlapping pair: share words ("AI教学", "工具")
    res_overlap = runner.run_zero_lexical_probe(
        query="如何做 AI 教学工具",
        memory_text="在做 AI 教学、AI 工具、SEO",
    )
    assert res_overlap.is_zero_overlap is False
    assert res_overlap.lexical_overlap_ratio > 0.0
    assert res_overlap.recalled is False


def test_procedural_anti_drop_probe_preservation() -> None:
    """Test procedural rule routing and anti-silent-drop verification."""
    runner = MemorySelfVerificationRunner()

    res_proc = runner.run_procedural_anti_drop_probe(
        rule_content="排查容器 503 报错时，必须优先检查端口映射与 IPv4 回环绑定，禁止直接重启服务",
    )
    assert res_proc.routed_track == "procedural"
    assert res_proc.was_dropped is False
    assert res_proc.is_preserved is True
    assert res_proc.drop_reason is None

    # Test dropped rule detection
    def drop_classifier(text: str) -> tuple[str, bool]:
        return ("semantic", True)

    res_dropped = runner.run_procedural_anti_drop_probe(
        rule_content="普通闲聊无指令内容",
        classifier=drop_classifier,
    )
    assert res_dropped.was_dropped is True
    assert res_dropped.is_preserved is False
    assert res_dropped.drop_reason == "silently_discarded_as_low_signal"


def test_full_diagnostic_suite_and_guaranteed_sandbox_cleanup() -> None:
    """Test full benchmark suite execution and guaranteed sandbox rollback cleanup."""
    cleaned_namespaces: list[str] = []

    def mock_cleaner(ns: str) -> bool:
        cleaned_namespaces.append(ns)
        return True

    runner = MemorySelfVerificationRunner(cleanup_callback=mock_cleaner)
    report = runner.run_full_diagnostic_suite(custom_namespace="_test_bench_sandbox_01")

    assert report.grade == VerificationHealthGrade.EXCELLENT
    assert report.score == 100.0
    assert report.total_probes == 3
    assert report.passed_probes == 3
    assert report.sandbox_cleaned is True
    assert "_test_bench_sandbox_01" in cleaned_namespaces
    assert report.fact_mutation_result.success is True
    assert report.zero_lexical_result.recalled is True
    assert report.procedural_anti_drop_result.is_preserved is True
