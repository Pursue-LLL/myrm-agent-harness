"""Unit tests for PersonCard and relationship memory layer suite."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from myrm_agent_harness.toolkits.memory.person_card import (
    PersonAttributes,
    PersonCard,
    PersonCardStore,
    PersonInteraction,
    PreActionAttributeChecker,
)


def test_person_card_creation_and_attributes() -> None:
    card = PersonCard(
        person_id="p-001",
        display_name="Alice Smith",
        aliases=["Alice", "小爱"],
        relation_type="colleague",
        org="Acme Corp",
        attributes=PersonAttributes(
            dietary_restrictions=["vegetarian"],
            timezone="UTC+8",
            birthday="1992-05-15",
            custom_notes={"key_project": "Alpha"},
        ),
        commitments=["Deliver Q3 roadmap by Friday"],
        interaction_timeline=[
            PersonInteraction(
                timestamp="2026-10-01T10:00:00Z",
                summary="Discussed roadmap alignment",
                channel="feishu",
            )
        ],
        last_interaction_at="2026-10-01T10:00:00Z",
    )

    assert card.person_id == "p-001"
    assert card.display_name == "Alice Smith"
    assert "vegetarian" in card.attributes.dietary_restrictions
    assert card.decay_status == "active"
    assert len(card.interaction_timeline) == 1


def test_person_card_store_crud_and_alias_lookup(tmp_path: Path) -> None:
    store_file = tmp_path / "persons.json"
    store = PersonCardStore(storage_path=store_file)

    alice = PersonCard(
        person_id="p-001",
        display_name="张三",
        aliases=["San Zhang", "三哥"],
        relation_type="friend",
        attributes=PersonAttributes(dietary_restrictions=["no-pork", "halal"]),
    )
    store.save_person(alice)

    # Fetch by ID
    fetched = store.get_person("p-001")
    assert fetched is not None
    assert fetched.display_name == "张三"

    # Fetch by alias
    matches = store.find_by_name_or_alias("三哥")
    assert len(matches) == 1
    assert matches[0].person_id == "p-001"

    # Case insensitive partial match
    matches2 = store.find_by_name_or_alias("san zhang")
    assert len(matches2) == 1
    assert matches2[0].person_id == "p-001"

    # Reload from disk into fresh store instance
    reloaded_store = PersonCardStore(storage_path=store_file)
    reloaded = reloaded_store.get_person("p-001")
    assert reloaded is not None
    assert reloaded.display_name == "张三"


def test_person_card_gravity_decay_to_weak(tmp_path: Path) -> None:
    store = PersonCardStore(storage_path=tmp_path / "persons.json")
    now = datetime(2026, 10, 10, 12, 0, 0, tzinfo=UTC)

    # Recent interaction
    recent_person = PersonCard(
        person_id="p-recent",
        display_name="Bob",
        last_interaction_at=(now - timedelta(hours=2)).isoformat(),
        confidence=1.0,
    )
    # Old interaction from 6 months ago
    old_person = PersonCard(
        person_id="p-old",
        display_name="Charlie",
        last_interaction_at=(now - timedelta(days=180)).isoformat(),
        confidence=0.5,
    )

    store.save_person(recent_person)
    store.save_person(old_person)

    scores = store.refresh_decay(now=now, weak_threshold=0.3)

    assert "p-recent" in scores
    assert "p-old" in scores
    assert scores["p-recent"] > scores["p-old"]

    updated_recent = store.get_person("p-recent")
    updated_old = store.get_person("p-old")

    assert updated_recent is not None and updated_recent.decay_status == "active"
    assert updated_old is not None and updated_old.decay_status == "weak"


def test_person_card_merge(tmp_path: Path) -> None:
    store = PersonCardStore(storage_path=tmp_path / "persons.json")

    card_a = PersonCard(
        person_id="p-001",
        display_name="David",
        aliases=["Dave"],
        relation_type="colleague",
        attributes=PersonAttributes(
            dietary_restrictions=["peanut-allergy"],
            timezone="UTC+8",
            custom_notes={"note_a": "val_a"},
        ),
        commitments=["Task A"],
        interaction_timeline=[
            PersonInteraction(
                timestamp="2026-09-01T10:00:00Z", summary="Meeting 1"
            )
        ],
        last_interaction_at="2026-09-01T10:00:00Z",
    )

    card_b = PersonCard(
        person_id="p-002",
        display_name="David Miller",
        aliases=["D. Miller"],
        relation_type="colleague",
        attributes=PersonAttributes(
            dietary_restrictions=["vegetarian"],
            birthday="1988-12-01",
            custom_notes={"note_b": "val_b"},
        ),
        commitments=["Task B"],
        interaction_timeline=[
            PersonInteraction(
                timestamp="2026-10-05T10:00:00Z", summary="Meeting 2"
            )
        ],
        last_interaction_at="2026-10-05T10:00:00Z",
    )

    store.save_person(card_a)
    store.save_person(card_b)

    merged = store.merge_persons(source_id="p-001", target_id="p-002")

    assert merged.person_id == "p-002"
    assert "David" in merged.aliases
    assert "Dave" in merged.aliases
    assert sorted(merged.attributes.dietary_restrictions) == [
        "peanut-allergy",
        "vegetarian",
    ]
    assert merged.attributes.timezone == "UTC+8"
    assert merged.attributes.birthday == "1988-12-01"
    assert merged.attributes.custom_notes["note_a"] == "val_a"
    assert merged.attributes.custom_notes["note_b"] == "val_b"
    assert sorted(merged.commitments) == ["Task A", "Task B"]
    assert len(merged.interaction_timeline) == 2
    assert merged.last_interaction_at == "2026-10-05T10:00:00Z"

    # Source marked as archived
    source = store.get_person("p-001")
    assert source is not None
    assert source.decay_status == "archived"


def test_pre_action_attribute_checker(tmp_path: Path) -> None:
    store = PersonCardStore(storage_path=tmp_path / "persons.json")
    now = datetime(2026, 10, 10, 12, 0, 0, tzinfo=UTC)

    # Guest 1: Known vegetarian
    p1 = PersonCard(
        person_id="p-guest1",
        display_name="小李",
        relation_type="friend",
        attributes=PersonAttributes(dietary_restrictions=["vegetarian"]),
        last_interaction_at=now.isoformat(),
    )
    # Guest 2: Weak memory, lactose intolerant
    p2 = PersonCard(
        person_id="p-guest2",
        display_name="王经理",
        relation_type="client",
        attributes=PersonAttributes(dietary_restrictions=["lactose-intolerant"]),
        last_interaction_at=(now - timedelta(days=200)).isoformat(),
    )
    # Guest 3: No dietary restriction info
    p3 = PersonCard(
        person_id="p-guest3",
        display_name="赵工",
        relation_type="colleague",
        attributes=PersonAttributes(),
        last_interaction_at=now.isoformat(),
    )

    store.save_person(p1)
    store.save_person(p2)
    store.save_person(p3)
    store.refresh_decay(now=now, weak_threshold=0.3)

    checker = PreActionAttributeChecker(store)

    result = checker.check_action(
        action_type="send_invite",
        participant_names_or_ids=["小李", "王经理", "赵工", "神秘客人"],
        action_summary="周末答谢晚餐邀请",
    )

    assert result.action_type == "send_invite"
    assert result.has_missing_attributes is True
    assert result.has_weak_memory_warning is True
    assert len(result.participants) == 4

    # Verify prompt cue contents
    cue = result.prompt_cue
    assert "周末答谢晚餐邀请" in cue
    assert "小李" in cue and "vegetarian" in cue
    assert "王经理" in cue and "lactose-intolerant" in cue
    assert "赵工" in cue and "未确认忌口" in cue
    assert "神秘客人" in cue

    # Warnings should advise verification
    assert any("王经理" in w and "弱记忆" in w for w in result.warnings)
    assert any("神秘客人" in w for w in result.warnings)
