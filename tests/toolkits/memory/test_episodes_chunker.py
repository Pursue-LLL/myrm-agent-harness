"""Tests for ConversationEpisode and EpisodesChunker in memory toolkit."""

from datetime import UTC, datetime, timedelta

import pytest

from myrm_agent_harness.toolkits.memory.chunking import (
    ChunkingStrategy,
    EpisodesChunker,
    chunk_conversation,
)


def test_episodes_chunker_empty() -> None:
    """Empty message sequence returns empty episodes list."""
    chunker = EpisodesChunker()
    assert chunker.split_into_episodes([]) == []


def test_episodes_chunker_single_turn() -> None:
    """Single Q&A pair forms one episode."""
    messages = [
        {"role": "user", "content": "Hello, how do I configure database?"},
        {"role": "assistant", "content": "Use port 5432 with Postgres."},
    ]
    chunker = EpisodesChunker()
    episodes = chunker.split_into_episodes(messages)

    assert len(episodes) == 1
    ep = episodes[0]
    assert ep.index == 0
    assert ep.turn_count == 1
    assert len(ep.messages) == 2
    assert "port 5432" in ep.messages[1]["content"]


def test_episodes_chunker_idle_gap_split() -> None:
    """Messages separated by idle time gap form distinct episodes."""
    base_time = datetime(2026, 9, 14, 10, 0, 0, tzinfo=UTC)
    t1 = base_time.isoformat()
    t2 = (base_time + timedelta(minutes=1)).isoformat()
    # 45 minutes later (> 30 min default idle gap)
    t3 = (base_time + timedelta(minutes=46)).isoformat()
    t4 = (base_time + timedelta(minutes=47)).isoformat()

    messages = [
        {"role": "user", "content": "Topic A question", "timestamp": t1},
        {"role": "assistant", "content": "Topic A answer", "timestamp": t2},
        {"role": "user", "content": "Topic B question after break", "timestamp": t3},
        {"role": "assistant", "content": "Topic B answer", "timestamp": t4},
    ]

    chunker = EpisodesChunker(idle_time_gap_minutes=30.0, overlap_turns=0)
    episodes = chunker.split_into_episodes(messages)

    assert len(episodes) == 2
    assert episodes[0].index == 0
    assert episodes[0].turn_count == 1
    assert episodes[1].index == 1
    assert episodes[1].turn_count == 1
    assert "Topic A" in episodes[0].messages[0]["content"]
    assert "Topic B" in episodes[1].messages[0]["content"]


def test_episodes_chunker_causal_sliding_overlap() -> None:
    """Subsequent episodes contain overlap turns from previous episode."""
    base_time = datetime(2026, 9, 14, 10, 0, 0, tzinfo=UTC)
    messages = [
        {
            "role": "user",
            "content": "Turn 1: set PORT=8080",
            "timestamp": base_time.isoformat(),
        },
        {
            "role": "assistant",
            "content": "Turn 1 reply: acknowledged PORT 8080",
            "timestamp": (base_time + timedelta(seconds=5)).isoformat(),
        },
        {
            "role": "user",
            "content": "Turn 2: configure JWT secret",
            "timestamp": (base_time + timedelta(minutes=40)).isoformat(),
        },
        {
            "role": "assistant",
            "content": "Turn 2 reply: secret saved",
            "timestamp": (base_time + timedelta(minutes=41)).isoformat(),
        },
    ]

    # overlap_turns=1 injects Turn 1 into Episode 2
    chunker = EpisodesChunker(idle_time_gap_minutes=30.0, overlap_turns=1)
    episodes = chunker.split_into_episodes(messages)

    assert len(episodes) == 2
    # Episode 1 has Turn 1
    assert len(episodes[0].messages) == 2
    # Episode 2 has Turn 1 (as overlap) + Turn 2
    assert len(episodes[1].messages) == 4
    assert "PORT=8080" in episodes[1].messages[0]["content"]
    assert "JWT secret" in episodes[1].messages[2]["content"]


def test_episodes_chunker_soft_max_chars_budget() -> None:
    """Dialog exceeding soft_max_chars partitions while preserving turn atomicity."""
    long_text = "x" * 600
    messages = [
        {"role": "user", "content": f"Turn 1 user {long_text}"},
        {"role": "assistant", "content": f"Turn 1 ai {long_text}"},
        {"role": "user", "content": f"Turn 2 user {long_text}"},
        {"role": "assistant", "content": f"Turn 2 ai {long_text}"},
    ]

    # soft_max_chars = 1000 forces cut after Turn 1 (total ~1200 chars)
    chunker = EpisodesChunker(soft_max_chars=1000, overlap_turns=0)
    episodes = chunker.split_into_episodes(messages)

    assert len(episodes) == 2
    assert episodes[0].turn_count == 1
    assert episodes[1].turn_count == 1


def test_episodes_chunker_oversized_message_protection() -> None:
    """Massive message with multiple paragraphs is split safely without crash."""
    p1 = "Paragraph 1: " + "a" * 800
    p2 = "Paragraph 2: " + "b" * 800
    content = f"{p1}\n\n{p2}"

    messages = [
        {"role": "user", "content": content},
        {"role": "assistant", "content": "Processed large payload."},
    ]

    chunker = EpisodesChunker(soft_max_chars=1000)
    episodes = chunker.split_into_episodes(messages)

    assert len(episodes) >= 1
    total_text = "".join(m["content"] for ep in episodes for m in ep.messages)
    assert "Paragraph 1" in total_text
    assert "Paragraph 2" in total_text


def test_chunk_conversation_strategy_episodes() -> None:
    """chunk_conversation with EPISODES strategy produces valid ConversationChunks."""
    messages = [
        {"role": "user", "content": "How to deploy?"},
        {"role": "assistant", "content": "Run docker compose up."},
    ]
    chunks = chunk_conversation(messages, strategy=ChunkingStrategy.EPISODES)
    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert "How to deploy?" in chunks[0].user_turn
    assert "docker compose" in (chunks[0].ai_turn or "")


@pytest.mark.asyncio
async def test_extractor_multi_episode_last_write_precedence() -> None:
    """Later episode's profile update overwrites earlier episode's update (Last-Write-Wins)."""
    import json

    from myrm_agent_harness.toolkits.memory.strategies.extractor import ExtractionConfig, MemoryExtractor

    # Two distinct message pairs with idle gap to guarantee 2 episodes
    base_time = datetime(2026, 9, 14, 10, 0, 0, tzinfo=UTC)
    t1 = base_time.isoformat()
    t2 = (base_time + timedelta(hours=2)).isoformat()

    messages = [
        {"role": "user", "content": "Use double quotes please", "created_at": t1},
        {"role": "assistant", "content": "Understood, using double quotes", "created_at": t1},
        {"role": "user", "content": "Changed mind, switch to single quotes now", "created_at": t2},
        {"role": "assistant", "content": "Got it, switching to single quotes", "created_at": t2},
    ]

    call_count = 0

    async def mock_llm_func(prompt: str, user_content: str) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Episode 1 extraction
            return json.dumps([
                {
                    "memory_type": "profile",
                    "content": "User prefers double quotes",
                    "confidence": 0.9,
                    "importance": 0.8,
                    "profile_key": "quote_style",
                    "profile_value": "double",
                }
            ])
        else:
            # Episode 2 extraction (corrected preference)
            return json.dumps([
                {
                    "memory_type": "profile",
                    "content": "User prefers single quotes",
                    "confidence": 0.95,
                    "importance": 0.85,
                    "profile_key": "quote_style",
                    "profile_value": "single",
                },
                {
                    "memory_type": "semantic",
                    "content": "Project uses TypeScript",
                    "confidence": 0.9,
                    "importance": 0.8,
                }
            ])

    extractor = MemoryExtractor(config=ExtractionConfig(max_input_chars=50), llm_func=mock_llm_func)
    result = await extractor.extract(messages)

    # 1. Total memories should be 2 (1 profile + 1 semantic)
    assert len(result.memories) == 2

    # 2. Find the profile entry
    profile_entries = [m for m in result.memories if m.profile_key == "quote_style"]
    assert len(profile_entries) == 1, "Must have exactly 1 profile entry for quote_style without collision"
    assert profile_entries[0].profile_value == "single", "Later episode (single) must overwrite earlier (double)"

    # 3. General semantic memory is retained
    semantic_entries = [m for m in result.memories if m.profile_key is None]
    assert len(semantic_entries) == 1
    assert "TypeScript" in semantic_entries[0].content
