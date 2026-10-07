"""Tests for Browser Automation Batch Processing and Script Synthesis Suite (Item 237)."""

from myrm_agent_harness.agent.context_management.browser_batch_script import (
    ArtifactFormatKind,
    BatchExecutionResult,
    BatchExtractionIntent,
    BatchFieldSpec,
    BrowserBatchProcessingEngine,
    DashboardMetricCard,
    InteractiveDashboardSpec,
    PaginationStrategy,
    SynthesizedBrowserScript,
    synthesize_batch_crawling_script,
)


def test_browser_batch_script_synthesis() -> None:
    """Verify autonomous synthesis of self-contained batch scraping Python program."""
    intent = BatchExtractionIntent(
        target_url="https://example-jobs.com/positions?q=ai-agent",
        target_count=30,
        fields=(
            BatchFieldSpec(field_name="title", css_selector=".job-title", description="Job Title"),
            BatchFieldSpec(field_name="company", css_selector=".company-name", description="Company"),
            BatchFieldSpec(field_name="salary", css_selector=".salary-range", description="Compensation"),
        ),
        pagination_strategy=PaginationStrategy.NEXT_BUTTON_CLICK,
        pagination_selector_or_param=".pagination-next",
        dedup_key="title",
        output_format=ArtifactFormatKind.EXCEL,
        generate_dashboard=True,
        max_pages=5,
    )

    script = synthesize_batch_crawling_script(intent)

    assert script.script_id.startswith("batch-")
    assert script.target_url == intent.target_url
    assert "openpyxl" in script.required_packages
    assert "playwright" in script.required_packages
    assert "pandas" in script.required_packages
    assert script.timeout_seconds >= 60

    code = script.python_code
    assert "FIELD_SELECTORS" in code
    assert "'title': '.job-title'" in code
    assert "'company': '.company-name'" in code
    assert "to_excel" in code
    assert "__BATCH_RESULT__:" in code


def test_browser_batch_single_turn_context_distillation() -> None:
    """Verify that multiple round-trips are eliminated and single-turn context saves >95% tokens."""
    engine = BrowserBatchProcessingEngine()
    intent = BatchExtractionIntent(
        target_url="https://example-jobs.com/positions?q=agent-architect",
        target_count=30,
        fields=(
            BatchFieldSpec(field_name="title", css_selector=".title", description="Job Title"),
            BatchFieldSpec(field_name="salary", css_selector=".salary", description="Salary"),
            BatchFieldSpec(field_name="company", css_selector=".company", description="Company"),
        ),
        pagination_strategy=PaginationStrategy.URL_OFFSET,
        pagination_selector_or_param="page",
        dedup_key="title",
        output_format=ArtifactFormatKind.EXCEL,
        generate_dashboard=True,
    )

    simulated_data = [
        {"title": f"Agent Lead Engineer {i}", "salary": "35k-50k", "company": f"TechCorp_{i % 3}"}
        for i in range(1, 31)
    ]

    result = engine.process_batch_execution(intent=intent, simulated_records=simulated_data)

    assert result.total_extracted == 30
    assert result.intent_url == intent.target_url
    assert result.artifact_path.endswith(".xlsx")
    assert len(result.sample_records) == 3

    # Verify context conservation
    # Traditional multi-turn: 3 pages * 2 steps * 12500 tokens = 75,000 tokens
    # Compact turn: ~350 tokens -> saved > 70,000 tokens!
    assert result.estimated_tokens_saved > 50000
    assert "Batch Web Data Extraction Completed (30 items)" in result.compact_context_text
    assert "Token Conservation" in result.compact_context_text
    assert "artifacts/" in result.compact_context_text


def test_interactive_dashboard_artifact_compilation() -> None:
    """Verify in-situ compilation of interactive React dashboard artifact."""
    engine = BrowserBatchProcessingEngine()
    intent = BatchExtractionIntent(
        target_url="https://example-jobs.com/positions?city=chengdu",
        target_count=20,
        fields=(
            BatchFieldSpec(field_name="role", css_selector=".role", description="Role"),
            BatchFieldSpec(field_name="company", css_selector=".company", description="Company"),
        ),
        pagination_strategy=PaginationStrategy.INFINITE_SCROLL,
        pagination_selector_or_param="window.scrollTo",
        dedup_key="role",
        output_format=ArtifactFormatKind.JSON,
        generate_dashboard=True,
    )

    simulated_data = [
        {"role": f"Embodied AI Dev {i}", "company": "Robotix" if i % 2 == 0 else "ByteFuture"}
        for i in range(1, 21)
    ]

    result = engine.process_batch_execution(intent=intent, simulated_records=simulated_data)

    assert result.dashboard_spec is not None
    dashboard = result.dashboard_spec
    assert "Batch Extraction Dashboard (20 items)" in dashboard.dashboard_title
    assert len(dashboard.summary_cards) == 3
    assert dashboard.summary_cards[0].label == "Total Collected"
    assert dashboard.summary_cards[0].value == "20"
    assert "Robotix" in dashboard.chart_distribution
    assert "ByteFuture" in dashboard.chart_distribution
    assert dashboard.chart_distribution["Robotix"] == 10
    assert "export const BatchDataDashboard" in dashboard.component_tsx_code
