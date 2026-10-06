# [POS] tests/toolkits/memory/test_experience_gene_evolution.py
# [INPUT] CausalGeneExtractor, ExecutionStepSnapshot, MultiTurnTaskTrace, ExperienceGeneLedger, ExperienceGene, GeneMatchQuery
# [OUTPUT] pytest test suite for Causal Experience Gene Synthesizer and Evolution Ledger

"""Unit and integration tests for Causal Experience Gene Synthesizer and Evolution Ledger."""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.evolution import (
    CausalGeneExtractor,
    ExecutionStepSnapshot,
    ExperienceGeneLedger,
    GeneMatchQuery,
    GenePolarity,
    MultiTurnTaskTrace,
)


def test_causal_gene_extraction_from_multiturn_trace() -> None:
    """Verify extracting causal experience gene from trial-error-success debugging trace."""
    trace = MultiTurnTaskTrace(
        session_id="debug-session-101",
        task_goal="Fix nginx package installation failure on Ubuntu container",
        steps=[
            ExecutionStepSnapshot(
                step_index=1,
                tool_name="bash",
                tool_input_summary="apt-get install -y nginx",
                tool_output_snippet="E: Could not open lock file /var/lib/dpkg/lock-frontend - open (13: Permission denied)",
                is_failure=True,
                error_signature="Could not open lock file /var/lib/dpkg/lock-frontend (13: Permission denied)",
            ),
            ExecutionStepSnapshot(
                step_index=2,
                tool_name="bash",
                tool_input_summary="kill -9 9872",
                tool_output_snippet="kill: (9872): No such process",
                is_failure=True,
                error_signature="kill: No such process pid 9872",
            ),
            ExecutionStepSnapshot(
                step_index=3,
                tool_name="bash",
                tool_input_summary="fuser -v /var/lib/dpkg/lock-frontend && sleep 2",
                tool_output_snippet="Waiting for package manager background sync to complete...",
                is_failure=False,
            ),
            ExecutionStepSnapshot(
                step_index=4,
                tool_name="bash",
                tool_input_summary="sudo apt-get install -y nginx",
                tool_output_snippet="Setting up nginx (1.18.0) ... done",
                is_failure=False,
            ),
        ],
        success_verified=True,
        final_solution_summary="Inspect lock holder with fuser and run with appropriate privileges after lock release",
    )

    gene = CausalGeneExtractor.extract_gene(trace=trace, domain_tag="devops")
    assert gene is not None
    assert gene.gene_id.startswith("gene_devops_")
    assert "tool:bash" in gene.trigger_signals
    assert gene.polarity == GenePolarity.POSITIVE
    assert gene.confidence_score == 0.8
    assert gene.proof_count == 1
    assert len(gene.hypotheses_refuted) == 2
    assert "apt-get install -y nginx" in gene.hypotheses_refuted[0]
    assert "kill -9 9872" in gene.hypotheses_refuted[1]
    assert "fuser" in gene.proven_resolution.lower()


def test_gene_ledger_registration_and_confidence_reinforcement() -> None:
    """Verify Darwinian confidence gain upon cross-session re-validation and proof count increment."""
    ledger = ExperienceGeneLedger()

    trace1 = MultiTurnTaskTrace(
        session_id="session-a",
        task_goal="Resolve port bind collision",
        steps=[
            ExecutionStepSnapshot(
                step_index=1,
                tool_name="bash",
                tool_input_summary="python -m http.server 8080",
                tool_output_snippet="OSError: [Errno 48] Address already in use",
                is_failure=True,
                error_signature="Address already in use: 8080",
            ),
            ExecutionStepSnapshot(
                step_index=2,
                tool_name="bash",
                tool_input_summary="lsof -ti:8080 | xargs kill -9",
                tool_output_snippet="Killed stale listener",
                is_failure=False,
            ),
        ],
        success_verified=True,
        final_solution_summary="Find listener on port and cleanly terminate stale process",
    )

    gene1 = CausalGeneExtractor.extract_gene(trace1, domain_tag="network")
    assert gene1 is not None

    # First registration
    saved1 = ledger.register_or_reinforce(gene1)
    assert saved1.proof_count == 1
    assert saved1.confidence_score == 0.8

    # Second occurrence in another session
    trace2 = MultiTurnTaskTrace(
        session_id="session-b",
        task_goal="Resolve port bind collision on another daemon",
        steps=[
            ExecutionStepSnapshot(
                step_index=1,
                tool_name="bash",
                tool_input_summary="node server.js --port 8080",
                tool_output_snippet="Error: listen EADDRINUSE: address already in use :::8080",
                is_failure=True,
                error_signature="Address already in use: 8080",
            ),
            ExecutionStepSnapshot(
                step_index=2,
                tool_name="bash",
                tool_input_summary="killall node",
                tool_output_snippet="Success",
                is_failure=False,
            ),
        ],
        success_verified=True,
        final_solution_summary="Free up conflicting port listener",
    )
    gene2 = CausalGeneExtractor.extract_gene(trace2, domain_tag="network")
    assert gene2 is not None

    reinforced = ledger.register_or_reinforce(gene2)
    assert reinforced.gene_id == saved1.gene_id
    assert reinforced.proof_count == 2
    # Confidence should increase asymptotically (0.8 + 0.2 * 0.15 = 0.83)
    assert reinforced.confidence_score > 0.8


def test_gene_informed_planning_advice_generation() -> None:
    """Verify gene-informed planning advice matches active signals and preempts refuted dead-ends."""
    ledger = ExperienceGeneLedger()

    trace = MultiTurnTaskTrace(
        session_id="session-c",
        task_goal="Debug git lock error",
        steps=[
            ExecutionStepSnapshot(
                step_index=1,
                tool_name="git",
                tool_input_summary="git commit -m 'update'",
                tool_output_snippet="fatal: Unable to create '.git/index.lock': File exists.",
                is_failure=True,
                error_signature="fatal: Unable to create '.git/index.lock': File exists",
            ),
        ],
        success_verified=True,
        final_solution_summary="Check if another git process is active, else remove stale .git/index.lock",
    )
    gene = CausalGeneExtractor.extract_gene(trace, domain_tag="git")
    assert gene is not None
    ledger.register_or_reinforce(gene)

    # In a new session with similar symptoms
    active_signals = ["tool:git", "fatal: Unable to create '.git/index.lock': File exists"]
    advice_list = ledger.generate_planning_mutation_advice(active_signals=active_signals)

    assert len(advice_list) == 1
    advice = advice_list[0]
    assert advice.gene_id == gene.gene_id
    assert "tool:git" in advice.matched_signals
    assert len(advice.refuted_paths) >= 1
    assert "index.lock" in advice.recommended_resolution


def test_gene_penalization_negative_feedback() -> None:
    """Verify negative feedback penalty decrements confidence score."""
    ledger = ExperienceGeneLedger()

    trace = MultiTurnTaskTrace(
        session_id="session-d",
        task_goal="Fix database timeout",
        steps=[
            ExecutionStepSnapshot(
                step_index=1,
                tool_name="db",
                tool_input_summary="SELECT * FROM big_table",
                tool_output_snippet="Query timeout after 30s",
                is_failure=True,
                error_signature="Query timeout after 30s",
            )
        ],
        success_verified=True,
        final_solution_summary="Increase timeout to 300s",
    )
    gene = CausalGeneExtractor.extract_gene(trace, domain_tag="database")
    assert gene is not None
    ledger.register_or_reinforce(gene)

    # Now simulate proposal failed in actual run
    penalized = ledger.penalize_gene(gene.gene_id, penalty=0.25)
    assert penalized is not None
    assert penalized.confidence_score == 0.55  # 0.8 - 0.25

    # Should not match under higher confidence filter
    query = GeneMatchQuery(active_signals=gene.trigger_signals, min_confidence=0.7)
    assert len(ledger.match_genes(query)) == 0
