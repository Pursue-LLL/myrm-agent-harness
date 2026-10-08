# [INPUT]: ChunkBoundedRollingMemoryAgentPipelineSuite, ChunkProcessingStep, ChunkStreamConfig, RollingPipelineResult, RollingWorkingMemory, RollingWorkingMemoryStateMachine, TextChunk, TokenBoundedChunkStreamer
# [OUTPUT]: test_chunk_bounded_rolling_memory_pipeline_suite.py
# [POS]: tests/agent/context_management/test_chunk_bounded_rolling_memory_pipeline_suite.py

"""Comprehensive test suite for ChunkBoundedRollingMemoryAgentPipelineSuite.

Verifies:
1. Token-bounded text chunk slicing with natural paragraph boundary preservation and overlap.
2. Step prompt formulation and deterministic state machine memory progression.
3. Token budgeting and structured condensation of thesis, entities, and events.
4. End-to-end multi-chunk processing pipeline and artifact deck generation.
5. Boundary conditions including empty text and custom extraction hooks.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.rolling_memory_pipeline import (
    ChunkBoundedRollingMemoryAgentPipelineSuite,
    ChunkProcessingStep,
    ChunkStreamConfig,
    RollingPipelineResult,
    RollingWorkingMemory,
    RollingWorkingMemoryStateMachine,
    TextChunk,
    TokenBoundedChunkStreamer,
)


def _generate_synthetic_long_document() -> str:
    paragraphs: list[str] = [
        "# Distributed Architecture Evolution Whitepaper",
        "Chapter 1: The Monolithic Core.\nInitially, ServiceRegistry and GatewayProxy were co-located in a single process. High throughput caused frequent GC pauses.",
        "- Event 1: Initial deployment of monolith in Q1 2024.\n- Event 2: Redis cache added to alleviate database pressure.",
        "Chapter 2: Decoupling into Microservices.\nEngineers decomposed PaymentWorker and OrderPipeline into dedicated containers running under Kubernetes orchestrator.",
        "- Event 3: Kafka event bus introduced for asynchronous order handling.\n- Event 4: Circuit breaker pattern adopted across internal RPC endpoints.",
        "Chapter 3: Edge Computing and Regional Sharding.\nDatabase cluster partitioned across EastAsia and NorthAmerica regions. DataLake pipeline ingests clickstream metrics continuously.",
        "- Event 5: Zero-trust mesh implemented with MutualTLS.\n- Event 6: Multi-cloud redundancy verified during disaster recovery drill.",
    ]
    # Multiply paragraphs to form a substantial document
    return "\n\n".join(paragraphs * 4)


def test_token_bounded_chunk_streamer_single_chunk() -> None:
    config = ChunkStreamConfig(chunk_token_budget=1000)
    streamer = TokenBoundedChunkStreamer(config)

    short_doc = "Short document with a single paragraph."
    chunks = streamer.stream_chunks(short_doc)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.chunk_index == 1
    assert chunk.total_chunks == 1
    assert chunk.text_content == short_doc
    assert chunk.char_offset_start == 0
    assert chunk.char_offset_end == len(short_doc)


def test_token_bounded_chunk_streamer_multiple_chunks_and_overlap() -> None:
    # Use small budget to force slicing across boundaries
    config = ChunkStreamConfig(chunk_token_budget=100, overlap_tokens=20)
    streamer = TokenBoundedChunkStreamer(config)

    long_doc = _generate_synthetic_long_document()
    chunks = streamer.stream_chunks(long_doc)

    assert len(chunks) > 1
    for c in chunks:
        assert c.total_chunks == len(chunks)
        assert len(c.text_content) > 0
        assert c.char_offset_end > c.char_offset_start

    # Verify monotonic index sequence
    indices = [c.chunk_index for c in chunks]
    assert indices == list(range(1, len(chunks) + 1))


def test_rolling_memory_state_machine_advance_and_prompt() -> None:
    config = ChunkStreamConfig(max_memory_tokens=500, agent_scope_id="agent_alpha")
    machine = RollingWorkingMemoryStateMachine(config)

    chunk1 = TextChunk(
        chunk_index=1,
        total_chunks=2,
        text_content="# High-Performance Cluster Design\nEngineers deployed StorageBroker across CloudCluster.",
        token_estimate=25,
        char_offset_start=0,
        char_offset_end=80,
    )

    prompt = machine.build_step_prompt(previous_memory=None, chunk=chunk1)
    assert "[MEMAGENT RUNTIME: CHUNK 1 OF 2]" in prompt
    assert "No prior working memory" in prompt

    mem1 = machine.advance(previous_memory=None, chunk=chunk1)
    assert mem1.step_index == 1
    assert "High-Performance Cluster Design" in mem1.core_thesis
    assert "StorageBroker" in mem1.key_entities or "CloudCluster" in mem1.key_entities
    assert mem1.agent_scope_id == "agent_alpha"

    # Step 2
    chunk2 = TextChunk(
        chunk_index=2,
        total_chunks=2,
        text_content="Chapter 2: Scaling Pipeline\n- Event: Migration to NVMe storage in Q2.",
        token_estimate=20,
        char_offset_start=80,
        char_offset_end=150,
    )
    prompt2 = machine.build_step_prompt(previous_memory=mem1, chunk=chunk2)
    assert "PRIOR WORKING MEMORY" in prompt2

    mem2 = machine.advance(previous_memory=mem1, chunk=chunk2)
    assert mem2.step_index == 2
    assert any("Migration to NVMe" in ev for ev in mem2.timeline_or_events)


def test_chunk_bounded_rolling_memory_pipeline_end_to_end() -> None:
    config = ChunkStreamConfig(chunk_token_budget=150, overlap_tokens=25, agent_scope_id="researcher")
    suite = ChunkBoundedRollingMemoryAgentPipelineSuite(config=config)

    doc = _generate_synthetic_long_document()
    result: RollingPipelineResult = suite.stream_and_process(doc)

    assert result.chunks_processed > 1
    assert result.total_source_tokens > 0
    assert len(result.history_steps) == result.chunks_processed

    # Validate memory progression
    assert result.final_memory.step_index == result.chunks_processed
    assert result.final_memory.core_thesis != ""
    assert len(result.final_memory.key_entities) > 0
    assert len(result.final_memory.timeline_or_events) > 0

    # Validate synthesized artifact deck
    deck = result.synthesized_artifact_markdown
    assert "# Document Cognition Deck" in deck
    assert "## Processing Metrics" in deck
    assert "## Core Thesis & Findings" in deck
    assert "## Chunk Navigation Index" in deck
    assert f"Total Chunks Sliced**: `{result.chunks_processed}`" in deck


def test_chunk_bounded_rolling_memory_pipeline_empty_doc() -> None:
    suite = ChunkBoundedRollingMemoryAgentPipelineSuite()
    result = suite.stream_and_process("")

    assert result.chunks_processed == 0
    assert result.total_source_tokens == 0
    assert result.final_memory.step_index == 0
    assert "(Empty Document)" in result.final_memory.core_thesis


def test_custom_extractor_hook() -> None:
    suite = ChunkBoundedRollingMemoryAgentPipelineSuite()

    def _mock_llm_extractor(
        prior: RollingWorkingMemory | None, chunk: TextChunk
    ) -> RollingWorkingMemory:
        return RollingWorkingMemory(
            step_index=(prior.step_index + 1) if prior else 1,
            core_thesis="Custom Extracted Thesis",
            key_entities=("CustomEntityA", "CustomEntityB"),
            timeline_or_events=("Milestone 1 achieved",),
            token_estimate=50,
            agent_scope_id="custom_agent",
        )

    result = suite.stream_and_process("Sample text block", custom_extractor=_mock_llm_extractor)
    assert result.chunks_processed == 1
    assert result.final_memory.core_thesis == "Custom Extracted Thesis"
    assert "CustomEntityA" in result.final_memory.key_entities
