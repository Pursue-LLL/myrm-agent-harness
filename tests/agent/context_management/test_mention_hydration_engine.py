"""Tests for GUI-First @-Mention Zero-Turn Context Hydration Suite (Item 239)."""

from myrm_agent_harness.agent.context_management.mention_hydration import (
    HydratedTurnPayload,
    MentionHydrationConfig,
    MentionHydrationEngine,
    MentionKind,
    ParsedMention,
    PreHydratedAttachment,
    compute_content_hash,
    parse_mentions_from_prompt,
)


def test_parse_mentions_from_prompt() -> None:
    """Verify regex extraction of explicit and implicit mentions while disregarding emails."""
    prompt = (
        "Please check @file:src/auth/jwt.py and @models/user.ts for vulnerabilities. "
        "Also refer to @artifact:dashboard-77 and @wiki:encryption-policy. "
        "Do not parse email addresses like security-lead@example.com or admin@corp.net."
    )

    mentions = parse_mentions_from_prompt(prompt)
    target_paths = {m.target_path for m in mentions}

    assert "src/auth/jwt.py" in target_paths
    assert "models/user.ts" in target_paths
    assert "dashboard-77" in target_paths
    assert "encryption-policy" in target_paths

    # Email addresses must NOT be recognized as mentions
    for m in mentions:
        assert "@example.com" not in m.target_path
        assert "@corp.net" not in m.target_path
        assert "security-lead" not in m.target_path

    # Check kind classification
    explicit_file = next(m for m in mentions if m.target_path == "src/auth/jwt.py")
    assert explicit_file.kind == MentionKind.FILE
    artifact_mention = next(m for m in mentions if m.target_path == "dashboard-77")
    assert artifact_mention.kind == MentionKind.ARTIFACT


def test_zero_turn_context_hydration_and_token_savings() -> None:
    """Verify zero-turn pre-attachment eliminates read tool calls and calculates savings."""
    engine = MentionHydrationEngine()
    session_id = "sess-mention-01"

    files_mock = {
        "src/core/config.py": "PORT = 8080\nDEBUG = False\nDB_URL = 'sqlite:///app.db'",
        "src/api/auth.py": "def verify_token(token: str) -> bool:\n    return len(token) > 16",
    }

    def mock_file_reader(path: str) -> str | None:
        return files_mock.get(path)

    prompt = "Review authentication in @src/api/auth.py and verify settings in @src/core/config.py."
    result = engine.hydrate_prompt(
        session_id=session_id,
        prompt=prompt,
        file_reader=mock_file_reader,
    )

    assert result.session_id == session_id
    assert len(result.attachments) == 2
    assert result.estimated_roundtrips_saved == 2
    assert result.estimated_tokens_saved == 700  # 2 * 350
    assert result.deduped_attachments_count == 0

    # Hydrated prompt must enclose files in standard XML blocks ahead of user query
    hydrated_text = result.hydrated_prompt
    assert '<user_attached_file path="src/api/auth.py"' in hydrated_text
    assert '<user_attached_file path="src/core/config.py"' in hydrated_text
    assert "PORT = 8080" in hydrated_text
    assert "def verify_token" in hydrated_text
    # Original prompt appended at the bottom
    assert hydrated_text.endswith(prompt)


def test_hash_deduplication_and_truncation_shield() -> None:
    """Verify in-session hash deduplication prevents duplicate bloat and oversized files are truncated."""
    config = MentionHydrationConfig(
        max_file_bytes=200,
        head_preserve_bytes=50,
        tail_preserve_bytes=50,
        enable_hash_dedup=True,
    )
    engine = MentionHydrationEngine(config=config)
    session_id = "sess-dedup-02"

    small_content = "const APP_VERSION = '2.4.0';"
    large_content = "X" * 500  # 500 bytes exceeds 200 byte limit

    files_mock = {
        "src/version.ts": small_content,
        "logs/app.log": large_content,
    }

    def mock_reader(path: str) -> str | None:
        return files_mock.get(path)

    # Turn 1: Initial hydration of both files
    turn_1 = engine.hydrate_prompt(
        session_id=session_id,
        prompt="Check @src/version.ts and examine @logs/app.log",
        file_reader=mock_reader,
    )
    assert len(turn_1.attachments) == 2
    assert turn_1.deduped_attachments_count == 0

    # Verify truncation on the oversized file
    log_att = next(a for a in turn_1.attachments if a.path == "logs/app.log")
    assert log_att.is_truncated
    assert "Content Truncated by Safety Gate" in log_att.content
    assert len(log_att.content) < 500

    # Turn 2: Mention version.ts again in the SAME session
    turn_2 = engine.hydrate_prompt(
        session_id=session_id,
        prompt="What was the version in @src/version.ts again?",
        file_reader=mock_reader,
    )
    # Deduplication must activate!
    assert turn_2.deduped_attachments_count == 1
    assert 'status="already_cached_in_context"' in turn_2.hydrated_prompt
    assert small_content not in turn_2.hydrated_prompt  # Content not repeated!
