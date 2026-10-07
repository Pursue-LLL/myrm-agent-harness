"""Unit tests for Grounded Dreaming, Provenance Anchors, and Governance Scheduler.

[POS]
Harness 记忆做梦与溯源测试套件。验证双向溯源锚点生成与指纹防篡改、
敏感凭据红线 100% 阻断、跨项目隔离门禁、闲时做梦调度与 REM 回溯重放管道。

[INPUT]
- 构造跨会话碎片与包含敏感 Key/正常业务事实的数据

[OUTPUT]
- 严格断言溯源锚点不可篡改性、敏感词彻底拦截、项目物理隔离、做梦条目锁定与撤回状态
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

from myrm_agent_harness.toolkits.memory.dreaming import (
    DreamDiaryEntry,
    DreamDiaryStatus,
    DreamingTriggerReason,
    DreamSessionFragment,
    GroundedDreamingEngine,
    GroundedDreamingScheduler,
    MemoryProvenanceAnchor,
    ProjectScopeIsolationGuard,
    SensitiveProvenanceGuard,
)


def test_provenance_anchor_immutability_and_serialization() -> None:
    """Test MemoryProvenanceAnchor auto-generates SHA256 digest and serializes correctly."""
    now = datetime.now(UTC)
    anchor = MemoryProvenanceAnchor(
        session_id="sess_101",
        message_id="msg_001",
        speaker="user",
        timestamp=now,
        verbatim_quote="Please always use TypeScript strict mode",
        char_span=(10, 52),
        project_id="proj_alpha",
        is_personal_profile=False,
    )

    assert len(anchor.hash_digest) == 16
    as_dict = anchor.to_dict()
    assert as_dict["session_id"] == "sess_101"
    assert as_dict["message_id"] == "msg_001"
    assert as_dict["verbatim_quote"] == "Please always use TypeScript strict mode"
    assert as_dict["hash_digest"] == anchor.hash_digest

    restored = MemoryProvenanceAnchor.from_dict(as_dict)
    assert restored.session_id == anchor.session_id
    assert restored.hash_digest == anchor.hash_digest
    assert restored.verbatim_quote == anchor.verbatim_quote


def test_sensitive_provenance_guard_redlines() -> None:
    """Test sensitive credentials (API keys, bearer tokens, private keys) are 100% blocked."""
    assert SensitiveProvenanceGuard.contains_sensitive_content("My apiKey = 'sk-1234567890abcdef1234567890'")
    assert SensitiveProvenanceGuard.contains_sensitive_content("Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6")
    assert SensitiveProvenanceGuard.contains_sensitive_content("ghp_123456789012345678901234567890123456")
    assert SensitiveProvenanceGuard.contains_sensitive_content("password='SuperSecretPass123!'")

    # Clean text should pass
    clean_text = "The user prefers Tailwind CSS over Bootstrap for dashboard layout"
    assert not SensitiveProvenanceGuard.contains_sensitive_content(clean_text)
    assert SensitiveProvenanceGuard.sanitize_or_reject(clean_text) == clean_text
    assert SensitiveProvenanceGuard.sanitize_or_reject("api_key='sk-abcdef1234567890123456'") is None


def test_project_scope_isolation_guard() -> None:
    """Test ProjectScopeIsolationGuard blocks foreign project facts while allowing personal profiles."""
    assert ProjectScopeIsolationGuard.validate_scope("proj_a", "proj_a", is_personal_profile=False)
    assert not ProjectScopeIsolationGuard.validate_scope("proj_b", "proj_a", is_personal_profile=False)
    # Global personal profile visible anywhere
    assert ProjectScopeIsolationGuard.validate_scope("proj_b", "proj_a", is_personal_profile=True)
    # None target allows everything
    assert ProjectScopeIsolationGuard.validate_scope("proj_b", None, is_personal_profile=False)


def test_grounded_dreaming_engine_consolidation_and_provenance() -> None:
    """Test engine clusters similar facts, blocks sensitive leaks, and populates provenance anchors."""
    engine = GroundedDreamingEngine(similarity_threshold=0.3)

    frag1 = DreamSessionFragment(
        session_id="sess_1",
        project_id="proj_main",
        memories=[
            {
                "content": "Prefers Next.js App Router for frontend architecture",
                "confidence": 0.8,
                "evidence": [
                    {
                        "message_id": "m1",
                        "speaker": "user",
                        "quote_snippet": "We decided to adopt Next.js App Router for frontend",
                    }
                ],
            },
            {
                "content": "Secret API token api_key='sk-1234567890abcdef1234567890'",
                "confidence": 0.9,
            },
        ],
    )

    frag2 = DreamSessionFragment(
        session_id="sess_2",
        project_id="proj_main",
        memories=[
            {
                "content": "Confirmed Next.js App Router for frontend layout",
                "confidence": 0.85,
                "evidence": [
                    {
                        "message_id": "m2",
                        "speaker": "user",
                        "quote_snippet": "Next.js App Router layout confirmed for dashboard",
                    }
                ],
            }
        ],
    )

    entries = engine.process_fragments([frag1, frag2], target_project_id="proj_main")
    assert len(entries) == 1
    entry = entries[0]

    # Sensitive memory should be completely blocked
    assert "sk-1234567890" not in str(entry.to_dict())

    # Should be cross-session validated
    assert "[Cross-Session Validated]" in entry.cognitive_statement
    assert "sess_1" in entry.source_session_ids
    assert "sess_2" in entry.source_session_ids
    assert len(entry.provenance_anchors) >= 1
    assert entry.provenance_anchors[0].session_id in ("sess_1", "sess_2")


def test_grounded_dreaming_scheduler_and_rem_backfill() -> None:
    """Test scheduler idle detection, nightly window evaluation, and REM backfill pipeline."""
    scheduler = GroundedDreamingScheduler(
        idle_inactivity_seconds=60,
        nightly_start_time=time(hour=2, minute=0),
        nightly_end_time=time(hour=5, minute=0),
    )

    # Idle evaluation
    now = datetime.now(UTC)
    scheduler.record_interaction(now - timedelta(seconds=70))
    assert scheduler.is_idle(now)

    should_trigger, reason = scheduler.should_trigger_dreaming(now)
    assert should_trigger
    assert reason in (DreamingTriggerReason.IDLE_TIMEOUT, DreamingTriggerReason.NIGHTLY_WINDOW)

    # REM backfill pipeline over historical fragments
    hist_frag = DreamSessionFragment(
        session_id="sess_hist",
        project_id="proj_rem",
        extracted_at=now - timedelta(days=2),
        memories=[
            {
                "content": "SQLite foreign keys must be enabled on every connection",
                "confidence": 0.9,
                "evidence": ["PRAGMA foreign_keys = ON"],
            }
        ],
    )

    entries = scheduler.run_rem_backfill(
        historical_fragments=[hist_frag],
        lookback_days=7,
        target_project_id="proj_rem",
    )
    assert len(entries) == 1
    assert "SQLite foreign keys" in entries[0].cognitive_statement


def test_dream_diary_entry_status_and_lock_governance() -> None:
    """Test dream diary entry status lifecycle including LOCKED and REVOKED states."""
    entry = DreamDiaryEntry.create(
        cognitive_statement="Never mutate production database directly",
        source_session_ids=["sess_alpha"],
        evidence_snippets=["Use migrations only"],
        project_id="proj_core",
    )

    assert entry.status == DreamDiaryStatus.PENDING
    assert not entry.is_locked

    # Lock entry
    entry.status = DreamDiaryStatus.LOCKED
    entry.is_locked = True
    entry.amended_statement = "Never mutate production DB without signed migration"

    d = entry.to_dict()
    assert d["status"] == "locked"
    assert d["is_locked"] is True
    assert d["amended_statement"] == "Never mutate production DB without signed migration"

    restored = DreamDiaryEntry.from_dict(d)
    assert restored.status == DreamDiaryStatus.LOCKED
    assert restored.is_locked is True
    assert restored.amended_statement == entry.amended_statement
