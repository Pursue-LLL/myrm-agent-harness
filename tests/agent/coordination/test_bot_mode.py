"""[INPUT] Harness bot_mode submodule exports.
[OUTPUT] Unit tests verifying NamedBotRoster indexing, @mention dispatching, inter-bot mailbox delivery, and unread management.
[POS] Unit tests for Bot Mode Named Profile Roster & Inter-Bot Mailbox Protocol (Item 33).
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.coordination.bot_mode import (
    BotProfile,
    BotStatus,
    InterBotMailboxRelay,
    MessagePriority,
    NamedBotRoster,
)


def test_bot_profile_creation_and_handle_normalization() -> None:
    # 1. Handle without '@' automatically normalized to '@' prefix and lowercase
    bot1 = BotProfile(
        bot_id="bot_001",
        handle="CodeReviewer",
        display_name="Code Reviewer",
        role_description="Performs adversarial code quality audits",
        avatar_seed="seed_reviewer",
        model_tier="strong_reasoning",
    )
    assert bot1.handle == "@codereviewer"
    assert bot1.status == BotStatus.IDLE
    assert bot1.active_task_id is None

    # 2. Handle with '@' preserved
    bot2 = BotProfile(
        bot_id="bot_002",
        handle="@TestEngineer",
        display_name="Test Engineer",
        role_description="Writes pytest unit and integration suites",
        avatar_seed="seed_tester",
        model_tier="fast_worker",
    )
    assert bot2.handle == "@testengineer"


def test_named_bot_roster_registration_and_lookup() -> None:
    roster = NamedBotRoster()

    bot_coder = BotProfile(
        bot_id="coder_id",
        handle="@coder",
        display_name="Fullstack Coder",
        role_description="Implements core fullstack features",
        avatar_seed="coder_1",
        model_tier="balanced",
    )
    bot_reviewer = BotProfile(
        bot_id="reviewer_id",
        handle="@reviewer",
        display_name="Code Reviewer",
        role_description="Reviews code diffs",
        avatar_seed="rev_1",
        model_tier="strong_reasoning",
    )

    roster.register_bot(bot_coder)
    roster.register_bot(bot_reviewer)
    assert roster.count() == 2

    # Lookup by id
    assert roster.get_bot_by_id("coder_id") == bot_coder

    # Lookup by handle (with and without '@')
    assert roster.get_bot_by_handle("@coder") == bot_coder
    assert roster.get_bot_by_handle("coder") == bot_coder

    # Resolve mention
    assert roster.resolve_mention("@reviewer") == bot_reviewer
    assert roster.resolve_mention("reviewer_id") == bot_reviewer

    # Update status
    updated = roster.update_status("coder_id", BotStatus.BUSY, active_task_id="task_build_01")
    assert updated is True
    coder_busy = roster.get_bot_by_id("coder_id")
    assert coder_busy is not None
    assert coder_busy.status == BotStatus.BUSY
    assert coder_busy.active_task_id == "task_build_01"

    # Filter by status
    busy_bots = roster.list_bots(status_filter=BotStatus.BUSY)
    assert len(busy_bots) == 1
    assert busy_bots[0].bot_id == "coder_id"

    idle_bots = roster.list_bots(status_filter=BotStatus.IDLE)
    assert len(idle_bots) == 1
    assert idle_bots[0].bot_id == "reviewer_id"

    # Unregister
    assert roster.unregister_bot("coder_id") is True
    assert roster.count() == 1
    assert roster.get_bot_by_id("coder_id") is None
    assert roster.get_bot_by_handle("@coder") is None


def test_inter_bot_mailbox_relay_send_and_inbox() -> None:
    roster = NamedBotRoster()
    bot_a = BotProfile(
        bot_id="bot_a",
        handle="@alice",
        display_name="Alice",
        role_description="Researcher",
        avatar_seed="alice",
        model_tier="fast",
    )
    bot_b = BotProfile(
        bot_id="bot_b",
        handle="@bob",
        display_name="Bob",
        role_description="Implementer",
        avatar_seed="bob",
        model_tier="balanced",
    )
    roster.register_bot(bot_a)
    roster.register_bot(bot_b)

    relay = InterBotMailboxRelay(roster=roster)

    # 1. Send message from Alice to Bob
    msg = relay.send_message(
        from_bot="@alice",
        to_bot="@bob",
        subject="Task Assignment",
        body="Please implement API router",
        priority=MessagePriority.HIGH,
        task_payload={"task_type": "api_routing", "lines_budget": 200},
        thread_id="thread_proj_01",
    )

    assert msg.from_bot == "@alice"
    assert msg.to_bot == "@bob"
    assert msg.subject == "Task Assignment"
    assert msg.is_read is False

    # 2. Check Bob's inbox
    assert relay.get_unread_count("bot_b") == 1
    inbox = relay.get_inbox("bot_b")
    assert len(inbox) == 1
    assert inbox[0].message_id == msg.message_id
    assert inbox[0].task_payload["lines_budget"] == 200

    # 3. Check Alice's outbox
    outbox = relay.get_outbox("bot_a")
    assert len(outbox) == 1
    assert outbox[0].message_id == msg.message_id

    # 4. Mark message as read
    read_count = relay.mark_as_read("bot_b", (msg.message_id,))
    assert read_count == 1
    assert relay.get_unread_count("bot_b") == 0
    assert len(relay.get_inbox("bot_b", unread_only=True)) == 0

    # 5. Sending to non-existent bot raises ValueError
    with pytest.raises(ValueError, match="not registered in the roster"):
        relay.send_message(from_bot="@alice", to_bot="@charlie", subject="Hi", body="Hello")


def test_dispatch_mentions_parsing_and_auto_delivery() -> None:
    roster = NamedBotRoster()
    qa = BotProfile(
        bot_id="qa_01",
        handle="@qa_lead",
        display_name="QA Lead",
        role_description="Test planner",
        avatar_seed="qa",
        model_tier="balanced",
    )
    arch = BotProfile(
        bot_id="arch_01",
        handle="@architect",
        display_name="Software Architect",
        role_description="System design",
        avatar_seed="arch",
        model_tier="strong",
    )
    roster.register_bot(qa)
    roster.register_bot(arch)

    relay = InterBotMailboxRelay(roster=roster)

    text = "Team notice: cc @qa_lead and @architect on PR #42, please ignore @ghost_bot."
    dispatch_results = relay.dispatch_mentions(
        text=text,
        from_bot="@lead_dev",
        thread_id="pr_review_42",
        task_payload={"pr_number": 42},
    )

    assert len(dispatch_results) == 3

    # QA Lead delivered
    qa_res = next(r for r in dispatch_results if r.target_handle == "@qa_lead")
    assert qa_res.dispatched is True
    assert qa_res.target_bot_id == "qa_01"
    assert relay.get_unread_count("qa_01") == 1

    # Architect delivered
    arch_res = next(r for r in dispatch_results if r.target_handle == "@architect")
    assert arch_res.dispatched is True
    assert arch_res.target_bot_id == "arch_01"
    assert relay.get_unread_count("arch_01") == 1

    # Ghost Bot not found
    ghost_res = next(r for r in dispatch_results if r.target_handle == "@ghost_bot")
    assert ghost_res.dispatched is False
    assert "not found in active bot roster" in ghost_res.note


def test_mailbox_clear_and_reset() -> None:
    roster = NamedBotRoster()
    bot = BotProfile(
        bot_id="b1",
        handle="@bot1",
        display_name="Bot 1",
        role_description="Helper",
        avatar_seed="b1",
        model_tier="fast",
    )
    roster.register_bot(bot)
    relay = InterBotMailboxRelay(roster=roster)

    relay.send_message(from_bot="@system", to_bot="@bot1", subject="Welcome", body="Init")
    assert relay.get_unread_count("b1") == 1

    # Clear individual mailbox
    relay.clear_mailbox("b1")
    assert relay.get_unread_count("b1") == 0
    assert len(relay.get_inbox("b1")) == 0

    # Reset all
    relay.send_message(from_bot="@system", to_bot="@bot1", subject="Ping", body="Pong")
    assert relay.get_unread_count("b1") == 1
    relay.reset_all()
    assert relay.get_unread_count("b1") == 0
