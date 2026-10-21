"""Unit tests for Multi-Human Multi-Agent Live Document Co-Authoring Ledger (Item 72).

[INPUT]
- myrm_agent_harness.agent.sub_agents.coauthoring_ledger

[OUTPUT]
- Pytest assertions verifying tripartite collaboration model, block lease locking,
  granular delta ledger with intent attribution, human-priority conflict arbitration,
  and isolated staging proposals.

[POS]
- myrm-agent-harness/tests/agent/sub_agents/test_coauthoring_ledger.py
"""

import pytest
from myrm_agent_harness.agent.sub_agents.coauthoring_ledger import (
    ArbitrationStrategy,
    BlockType,
    CoAuthoringConflictArbitrator,
    CollaboratorProfile,
    CollaboratorType,
    DeltaOperation,
    DocumentBlock,
    LiveDocumentCoAuthoringLedger,
)


def test_collaborator_registration_and_tripartite_model() -> None:
    """Test registering humans and associated AI agents into tripartite space."""
    ledger = LiveDocumentCoAuthoringLedger(
        document_id="doc-arch-001",
        title="Multi-Agent System Architecture Specification",
    )

    # Human A & Agent A
    human_a = CollaboratorProfile(
        collaborator_id="human-alice",
        collaborator_type=CollaboratorType.HUMAN,
        name="Alice (Lead Architect)",
    )
    agent_a = CollaboratorProfile(
        collaborator_id="agent-alice-bot",
        collaborator_type=CollaboratorType.AGENT,
        name="Alice Copilot (Research Agent)",
        principal_human_id="human-alice",
    )

    # Human B & Agent B
    human_b = CollaboratorProfile(
        collaborator_id="human-bob",
        collaborator_type=CollaboratorType.HUMAN,
        name="Bob (Security Reviewer)",
    )
    agent_b = CollaboratorProfile(
        collaborator_id="agent-bob-bot",
        collaborator_type=CollaboratorType.AGENT,
        name="Bob Copilot (Security Scanner)",
        principal_human_id="human-bob",
    )

    for c in [human_a, agent_a, human_b, agent_b]:
        ledger.register_collaborator(c)

    all_collabs = ledger.list_collaborators()
    assert len(all_collabs) == 4

    bot_a = ledger.get_collaborator("agent-alice-bot")
    assert bot_a is not None
    assert bot_a.principal_human_id == "human-alice"
    assert bot_a.collaborator_type == CollaboratorType.AGENT


def test_document_initialization_and_rendering() -> None:
    """Test initializing multi-block document and rendering markdown representation."""
    ledger = LiveDocumentCoAuthoringLedger(
        document_id="doc-spec-002",
        title="Distributed Ledger Whitepaper",
    )

    blocks = [
        DocumentBlock(
            block_id="b-head-1",
            block_type=BlockType.HEADING,
            content="1. Executive Summary",
        ),
        DocumentBlock(
            block_id="b-para-1",
            block_type=BlockType.PARAGRAPH,
            content="This document outlines the state machine design for collaborative AI editing.",
        ),
        DocumentBlock(
            block_id="b-code-1",
            block_type=BlockType.CODE,
            content='def reconcile():\n    return "consistent"',
        ),
        DocumentBlock(
            block_id="b-list-1",
            block_type=BlockType.BULLET_LIST,
            content="Human Priority\nGranular Attribution\nCRDT Reconciliation",
        ),
    ]

    ledger.init_document(blocks)
    assert len(ledger.list_blocks()) == 4

    md = ledger.render_markdown()
    assert "# Distributed Ledger Whitepaper" in md
    assert "## 1. Executive Summary" in md
    assert "def reconcile():" in md
    assert "- Human Priority" in md


def test_block_lease_locking_and_concurrency_guard() -> None:
    """Test acquiring, verifying, and releasing lease locks to prevent write collisions."""
    ledger = LiveDocumentCoAuthoringLedger(document_id="doc-lease-003")
    block = DocumentBlock(
        block_id="b-lock-target",
        block_type=BlockType.PARAGRAPH,
        content="Sensitive section being updated",
    )
    ledger.init_document([block])

    # Human acquires lease
    assert ledger.acquire_block_lease("b-lock-target", "human-alice", duration_seconds=60.0) is True

    # Same author can re-acquire
    assert ledger.acquire_block_lease("b-lock-target", "human-alice") is True

    # Another author blocked
    assert ledger.is_block_locked("b-lock-target", "agent-bob-bot") is True
    assert ledger.acquire_block_lease("b-lock-target", "agent-bob-bot") is False

    # Attempting to mutate locked block raises PermissionError
    with pytest.raises(PermissionError) as exc_info:
        ledger.apply_delta(
            block_id="b-lock-target",
            operation=DeltaOperation.UPDATE_BLOCK,
            author_id="agent-bob-bot",
            new_content="Overwritten unauthorized",
        )
    assert "locked by another author" in str(exc_info.value)

    # Release lease and verify another author can now acquire and mutate
    assert ledger.release_block_lease("b-lock-target", "human-alice") is True
    assert ledger.is_block_locked("b-lock-target", "agent-bob-bot") is False

    updated = ledger.apply_delta(
        block_id="b-lock-target",
        operation=DeltaOperation.UPDATE_BLOCK,
        author_id="agent-bob-bot",
        new_content="Authorized update after release",
        intent_reason="Security scan completed",
    )
    assert updated.content == "Authorized update after release"
    assert updated.version == 2


def test_granular_delta_application_and_attribution_trace() -> None:
    """Test full cycle of insert, update, and delete with immutable delta attribution ledger."""
    ledger = LiveDocumentCoAuthoringLedger(document_id="doc-delta-004")
    human = CollaboratorProfile(
        collaborator_id="human-alice",
        collaborator_type=CollaboratorType.HUMAN,
        name="Alice",
    )
    agent = CollaboratorProfile(
        collaborator_id="agent-bot",
        collaborator_type=CollaboratorType.AGENT,
        name="Assistant",
        principal_human_id="human-alice",
    )
    ledger.register_collaborator(human)
    ledger.register_collaborator(agent)

    # 1. Insert
    b1 = ledger.apply_delta(
        block_id="b-new-1",
        operation=DeltaOperation.INSERT_BLOCK,
        author_id="human-alice",
        new_content="Introduction section written by human.",
        intent_reason="Drafting initial intro",
        block_type=BlockType.PARAGRAPH,
    )
    assert b1.version == 1

    # 2. Update by agent
    b1_up = ledger.apply_delta(
        block_id="b-new-1",
        operation=DeltaOperation.UPDATE_BLOCK,
        author_id="agent-bot",
        new_content="Introduction section polished by AI Copilot with citations.",
        intent_reason="Grammar and citation enrichment",
    )
    assert b1_up.version == 2
    assert b1_up.last_author_id == "agent-bot"

    # 3. Query deltas
    deltas = ledger.get_deltas(block_id="b-new-1")
    assert len(deltas) == 2
    assert deltas[0].author_type == CollaboratorType.HUMAN
    assert deltas[1].author_type == CollaboratorType.AGENT
    assert deltas[1].principal_human_id == "human-alice"

    # 4. Check contributions
    contribs = ledger.get_author_contributions()
    assert contribs["human-alice"] == 1
    assert contribs["agent-bot"] == 1


def test_human_priority_conflict_arbitration() -> None:
    """Test human-priority arbitration when Human and Agent collide on the same block."""
    ledger = LiveDocumentCoAuthoringLedger(document_id="doc-conflict-005")
    human = CollaboratorProfile(
        collaborator_id="human-alice",
        collaborator_type=CollaboratorType.HUMAN,
        name="Alice",
    )
    agent = CollaboratorProfile(
        collaborator_id="agent-bot",
        collaborator_type=CollaboratorType.AGENT,
        name="Bot",
        principal_human_id="human-alice",
    )
    ledger.register_collaborator(human)
    ledger.register_collaborator(agent)

    b = DocumentBlock(
        block_id="b-contested",
        block_type=BlockType.PARAGRAPH,
        content="Original consensus architecture clause.",
    )
    ledger.init_document([b])

    arbitrator = CoAuthoringConflictArbitrator(ledger)

    verdict = arbitrator.detect_and_arbitrate(
        block_id="b-contested",
        first_author_id="human-alice",
        first_content="Human updated clause with legal warranty provisions.",
        first_reason="Mandatory legal requirement compliance",
        second_author_id="agent-bot",
        second_content="Agent summarized clause for conciseness.",
        second_reason="Brevity and token optimization",
        strategy=ArbitrationStrategy.HUMAN_PRIORITY,
    )

    assert verdict.resolved is True
    # Human content wins
    assert "Human updated clause with legal warranty" in verdict.winning_content
    assert "Human author (human-alice) prioritized over Agent" in verdict.summary

    # Agent's proposal was isolated into StagingProposal
    assert len(verdict.staging_proposals) == 1
    prop = verdict.staging_proposals[0]
    assert prop.author_id == "agent-bot"
    assert "Agent summarized clause" in prop.content
    assert prop.status == "pending"

    # Staging proposals retrievable
    proposals = arbitrator.list_proposals(block_id="b-contested")
    assert len(proposals) == 1


def test_isolated_staging_proposal_and_acceptance() -> None:
    """Test isolating competing mutations into staging proposals and explicit human acceptance."""
    ledger = LiveDocumentCoAuthoringLedger(document_id="doc-staging-006")
    b = DocumentBlock(
        block_id="b-table-data",
        block_type=BlockType.TABLE,
        content="| Latency | Throughput |\n| 10ms | 1000 rps |",
    )
    ledger.init_document([b])

    arbitrator = CoAuthoringConflictArbitrator(ledger)

    # Simultaneous agent edits isolated
    verdict = arbitrator.detect_and_arbitrate(
        block_id="b-table-data",
        first_author_id="agent-p99-bench",
        first_content="| Latency (p99) | Throughput |\n| 14ms | 950 rps |",
        first_reason="P99 benchmark measurements",
        second_author_id="agent-p50-bench",
        second_content="| Latency (p50) | Throughput |\n| 4ms | 1200 rps |",
        second_reason="P50 benchmark measurements",
        strategy=ArbitrationStrategy.ISOLATED_STAGING_PROPOSAL,
    )

    assert verdict.resolved is True
    # Neither clobbered active document
    assert len(verdict.staging_proposals) == 2
    p1 = verdict.staging_proposals[0]

    # Human reviewer explicitly accepts proposal 1
    accepted = arbitrator.accept_proposal(p1.proposal_id, reviewer_id="human-lead")
    assert accepted is not None
    assert accepted.status == "accepted"

    # Verify updated in ledger
    updated_block = ledger.get_block("b-table-data")
    assert updated_block is not None
    assert "14ms" in updated_block.content
    assert updated_block.version == 2
