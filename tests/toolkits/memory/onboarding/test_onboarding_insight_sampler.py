"""Unit tests for onboarding insight sampling, entropy scanning, secret redaction, and distillation.

[INPUT]
- pytest
- pathlib: Path
- json
- myrm_agent_harness.toolkits.memory.onboarding: models, entropy_inspector, redactor, adapters, registry, sampler, distiller

[OUTPUT]
- Test suite verifying complete end-to-end functionality of onboarding insight suite.

[POS]
Harness framework test suite for FirstEncounterOnboardingInsightReportSuite.
"""

from __future__ import annotations

import json
from pathlib import Path

from myrm_agent_harness.toolkits.memory.onboarding import (
    FirstEncounterReport,
    LocalSecretRedactor,
    MultiSourceOnboardingSampler,
    OnboardingConversationWindow,
    OnboardingInsightDistiller,
    OnboardingSampleOptions,
    OnboardingSourceRegistry,
    SampledTurnMessage,
    ShannonEntropyInspector,
)
from myrm_agent_harness.toolkits.memory.onboarding.adapters import (
    CursorSourceAdapter,
)


def test_shannon_entropy_inspector() -> None:
    """Verify that ShannonEntropyInspector identifies un-prefixed high-entropy credentials."""
    inspector = ShannonEntropyInspector(entropy_threshold=4.5, min_token_len=24)

    # Regular English sentence should have low entropy candidate tokens
    normal_text = "This is a normal English sentence about implementing clean code."
    assert inspector.inspect_text(normal_text) == []

    # High-entropy random cryptographic token (without known prefix)
    secret_token = "7xK9pQ2mW8vL5nB3jH1tG4dF6sA0zC9e"
    text_with_secret = f"Use internal key {secret_token} for authentication."
    results = inspector.inspect_text(text_with_secret)
    assert len(results) == 1
    assert results[0][0] == secret_token
    assert results[0][1] >= 4.5

    redacted_text, count = inspector.redact_high_entropy_tokens(text_with_secret)
    assert count == 1
    assert "[REDACTED_HIGH_ENTROPY_SECRET]" in redacted_text
    assert secret_token not in redacted_text


def test_local_secret_redactor() -> None:
    """Verify dual-tier redaction: known regex patterns + Shannon entropy inspection."""
    redactor = LocalSecretRedactor(enable_entropy=True, entropy_threshold=4.5)

    raw_text = (
        "Here is my OpenAI key sk-1234567890abcdef1234567890abcdef and "
        "GitHub token ghp_1234567890abcdef1234567890abcdef1234 and "
        "unprefixed secret 9xZ7qP3mW1vL8nB4jH2tG5dF7sA0zC9k"
    )
    sanitized, count = redactor.scrub(raw_text)
    assert count >= 3
    assert "[REDACTED_API_KEY]" in sanitized
    assert "[REDACTED_GITHUB_TOKEN]" in sanitized
    assert "[REDACTED_HIGH_ENTROPY_SECRET]" in sanitized
    assert "sk-" not in sanitized
    assert "ghp_" not in sanitized


def test_sliding_window_sampler() -> None:
    """Verify first-2 and last-12 turns keyframe selection and character budget caps."""
    options = OnboardingSampleOptions(
        first_conversation_turns=2,
        last_conversation_turns=12,
        max_user_chars=500,
        max_assistant_chars=800,
        max_window_chars=5000,
    )
    registry = OnboardingSourceRegistry(register_defaults=False)
    sampler = MultiSourceOnboardingSampler(registry, options)

    # Create 20 mock conversation turns
    messages: list[SampledTurnMessage] = []
    for i in range(20):
        role = "user" if i % 2 == 0 else "assistant"
        messages.append(
            SampledTurnMessage(
                source_id="test_source",
                conversation_id="conv_1",
                message_id=f"msg_{i}",
                role=role,
                text=f"Turn message {i} with payload data:image/png;base64," + ("A" * 120),
                created_at="2026-10-07T12:00:00Z",
            )
        )

    sampled, truncated, _ = sampler.sample_messages(messages)
    assert truncated is False
    # 2 first turns (0, 1) + 12 last turns (8..19) = 14 turns total
    assert len(sampled) == 14
    assert sampled[0].message_id == "msg_0"
    assert sampled[1].message_id == "msg_1"
    assert sampled[2].message_id == "msg_8"
    assert sampled[-1].message_id == "msg_19"
    # Ensure inline media payload was stripped
    assert "[INLINE_MEDIA_PAYLOAD_REDACTED]" in sampled[0].text


def test_adapters_and_registry(tmp_path: Path) -> None:
    """Verify source adapter discovery and file message extraction."""
    chat_dir = tmp_path / "chats"
    chat_dir.mkdir(parents=True)
    sample_file = chat_dir / "session1.json"
    sample_data = {
        "messages": [
            {"role": "user", "text": "We prefer FastAPI and Pydantic v2", "createdAt": "2026-10-07"},
            {"role": "assistant", "text": "Resolved by using HTTP 206 for streaming", "createdAt": "2026-10-07"},
        ]
    }
    sample_file.write_text(json.dumps(sample_data), encoding="utf-8")

    adapter = CursorSourceAdapter(base_dir=chat_dir)
    assert adapter.detect_active() is True
    recent_sessions = adapter.scan_recent_sessions(limit=5)
    assert len(recent_sessions) == 1

    extracted = adapter.extract_turn_messages(sample_file)
    assert len(extracted) == 2
    assert extracted[0].role == "user"
    assert "FastAPI" in extracted[0].text


def test_insight_distiller_and_report() -> None:
    """Verify extraction of tech preferences, pitfalls, active goals, and report aggregation."""
    distiller = OnboardingInsightDistiller()
    window = OnboardingConversationWindow(
        source_id="cursor",
        conversation_id="session_alpha",
        display_name="Cursor IDE",
        file_path="/mock/path.json",
        messages=[
            SampledTurnMessage(
                source_id="cursor",
                conversation_id="session_alpha",
                message_id="m1",
                role="user",
                text="In this project, always use TypeScript with strict typing.",
                created_at="2026-10-07T10:00:00Z",
            ),
            SampledTurnMessage(
                source_id="cursor",
                conversation_id="session_alpha",
                message_id="m2",
                role="assistant",
                text="Resolved by implementing idempotent token caching to prevent race conditions.",
                created_at="2026-10-07T10:01:00Z",
            ),
            SampledTurnMessage(
                source_id="cursor",
                conversation_id="session_alpha",
                message_id="m3",
                role="user",
                text="We are currently working on memory onboarding pipelines.",
                created_at="2026-10-07T10:02:00Z",
            ),
        ],
    )

    facts = distiller.distill_window(window)
    assert len(facts) >= 3

    categories = {f.category for f in facts}
    assert "tech_stack_preference" in categories
    assert "hard_learned_lesson" in categories
    assert "active_project_goal" in categories

    # Fingerprint deduplication test
    report = distiller.generate_report([window, window])
    assert isinstance(report, FirstEncounterReport)
    # Duplicate facts across windows should be deduplicated by SHA256 fingerprint
    assert len(report.facts) == len(facts)
    assert "cursor" in report.probed_sources
