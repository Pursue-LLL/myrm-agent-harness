"""Tests for QueuedDelivery phase persistence in delivery storage."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.infra.delivery.storage import (
    QueuedDelivery,
    ack_delivery,
    load_pending_deliveries,
    save_delivery,
)


@pytest.mark.asyncio
async def test_save_and_load_pending_phase(tmp_path: Path) -> None:
    pending = QueuedDelivery(
        id="feishu_user_1_phase",
        channel="feishu",
        recipient="user_1",
        content={"text": "hello"},
        enqueued_at=1.0,
        phase="pending",
    )
    await save_delivery(pending, base_dir=tmp_path)

    loaded = await load_pending_deliveries(base_dir=tmp_path)
    assert len(loaded) == 1
    assert loaded[0].phase == "pending"


@pytest.mark.asyncio
async def test_save_and_load_attempting_phase(tmp_path: Path) -> None:
    attempting = QueuedDelivery(
        id="feishu_user_1_attempt",
        channel="feishu",
        recipient="user_1",
        content={"text": "in flight"},
        enqueued_at=2.0,
        phase="attempting",
    )
    await save_delivery(attempting, base_dir=tmp_path)

    loaded = await load_pending_deliveries(base_dir=tmp_path)
    assert len(loaded) == 1
    assert loaded[0].phase == "attempting"


@pytest.mark.asyncio
async def test_phase_defaults_to_pending_for_legacy_json(tmp_path: Path) -> None:
    """Entries without phase field deserialize as pending."""
    legacy = QueuedDelivery(
        id="legacy_no_phase",
        channel="feishu",
        recipient="user_1",
        content={"text": "legacy"},
        enqueued_at=3.0,
    )
    await save_delivery(legacy, base_dir=tmp_path)

    loaded = await load_pending_deliveries(base_dir=tmp_path)
    assert loaded[0].phase == "pending"


@pytest.mark.asyncio
async def test_ack_removes_phase_entry(tmp_path: Path) -> None:
    delivery = QueuedDelivery(
        id="to_ack",
        channel="feishu",
        recipient="user_1",
        content={"text": "done"},
        enqueued_at=4.0,
        phase="attempting",
    )
    await save_delivery(delivery, base_dir=tmp_path)
    await ack_delivery("to_ack", base_dir=tmp_path)

    assert await load_pending_deliveries(base_dir=tmp_path) == []


@pytest.mark.asyncio
async def test_save_delivery_requires_base_or_provider() -> None:
    delivery = QueuedDelivery(
        id="missing_base",
        channel="feishu",
        recipient="user_1",
        content={"text": "x"},
        enqueued_at=1.0,
    )
    with pytest.raises(ValueError, match="Either base_dir or storage_provider"):
        await save_delivery(delivery)


@pytest.mark.asyncio
async def test_load_pending_without_args_returns_empty() -> None:
    assert await load_pending_deliveries() == []


@pytest.mark.asyncio
async def test_load_pending_when_queue_dir_missing(tmp_path: Path) -> None:
    assert await load_pending_deliveries(base_dir=tmp_path / "missing") == []


@pytest.mark.asyncio
async def test_load_pending_skips_corrupt_json(tmp_path: Path) -> None:
    from myrm_agent_harness.infra.delivery.storage import (
        QUEUE_DIRNAME,
        _queued_delivery_from_pending_dict,
        delete_failed_delivery,
        generate_delivery_id,
        load_failed_deliveries,
        move_to_failed,
        move_to_pending,
    )

    queue_dir = tmp_path / QUEUE_DIRNAME
    queue_dir.mkdir(parents=True)
    (queue_dir / "bad.json").write_text("{not json", encoding="utf-8")

    good = QueuedDelivery(
        id="good_one",
        channel="feishu",
        recipient="user_1",
        content={"text": "ok"},
        enqueued_at=1.0,
        phase="pending",
    )
    await save_delivery(good, base_dir=tmp_path)

    loaded = await load_pending_deliveries(base_dir=tmp_path)
    assert len(loaded) == 1
    assert loaded[0].id == "good_one"

    assert (
        _queued_delivery_from_pending_dict(
            {
                "id": good.id,
                "channel": good.channel,
                "recipient": good.recipient,
                "content": good.content,
                "enqueued_at": good.enqueued_at,
                "phase": "unknown",
            }
        ).phase
        == "pending"
    )

    delivery_id = generate_delivery_id("feishu", "user_1")
    assert delivery_id.startswith("feishu_user_1_")

    failed = QueuedDelivery(
        id="failed_one",
        channel="feishu",
        recipient="user_1",
        content={"text": "fail"},
        enqueued_at=2.0,
        phase="attempting",
    )
    await save_delivery(failed, base_dir=tmp_path)
    await move_to_failed(failed, base_dir=tmp_path)
    pending_after_fail = await load_pending_deliveries(base_dir=tmp_path)
    assert len(pending_after_fail) == 1
    assert pending_after_fail[0].id == "good_one"

    failed_loaded = await load_failed_deliveries(base_dir=tmp_path)
    assert len(failed_loaded) == 1
    assert failed_loaded[0].id == "failed_one"

    await move_to_pending(failed_loaded[0], base_dir=tmp_path)
    pending_again = await load_pending_deliveries(base_dir=tmp_path)
    assert len(pending_again) == 2

    assert await delete_failed_delivery("nonexistent", base_dir=tmp_path) is False
    to_fail = next(p for p in pending_again if p.id == "failed_one")
    await move_to_failed(to_fail, base_dir=tmp_path)
    assert await delete_failed_delivery("failed_one", base_dir=tmp_path) is True


@pytest.mark.asyncio
async def test_storage_provider_pending_lifecycle(tmp_path: Path) -> None:
    from myrm_agent_harness.infra.delivery.storage import (
        ack_delivery,
        delete_failed_delivery,
        load_failed_deliveries,
        move_to_failed,
        move_to_pending,
    )
    from myrm_agent_harness.toolkits.storage import LocalStorageBackend

    storage = LocalStorageBackend(tmp_path / "cloud-storage")
    delivery = QueuedDelivery(
        id="cloud_one",
        channel="feishu",
        recipient="user_1",
        content={"text": "cloud"},
        enqueued_at=1.0,
        phase="attempting",
    )
    await save_delivery(delivery, storage_provider=storage)
    loaded = await load_pending_deliveries(storage_provider=storage)
    assert len(loaded) == 1
    assert loaded[0].phase == "attempting"

    await ack_delivery("cloud_one", storage_provider=storage)
    assert await load_pending_deliveries(storage_provider=storage) == []

    await save_delivery(delivery, storage_provider=storage)
    await move_to_failed(delivery, storage_provider=storage)
    assert await load_pending_deliveries(storage_provider=storage) == []
    failed = await load_failed_deliveries(storage_provider=storage)
    assert len(failed) == 1

    await move_to_pending(failed[0], storage_provider=storage)
    assert len(await load_pending_deliveries(storage_provider=storage)) == 1
    pending = await load_pending_deliveries(storage_provider=storage)
    await move_to_failed(pending[0], storage_provider=storage)
    assert await delete_failed_delivery("cloud_one", storage_provider=storage) is True


@pytest.mark.asyncio
async def test_load_failed_deliveries_empty_dir(tmp_path: Path) -> None:
    from myrm_agent_harness.infra.delivery.storage import load_failed_deliveries

    assert await load_failed_deliveries(base_dir=tmp_path) == []


@pytest.mark.asyncio
async def test_ack_delivery_missing_file_is_noop(tmp_path: Path) -> None:
    await ack_delivery("missing-id", base_dir=tmp_path)


@pytest.mark.asyncio
async def test_load_failed_skips_corrupt_json(tmp_path: Path) -> None:
    from myrm_agent_harness.infra.delivery.storage import (
        FAILED_DIRNAME,
        QUEUE_DIRNAME,
        load_failed_deliveries,
    )

    failed_dir = tmp_path / QUEUE_DIRNAME / FAILED_DIRNAME
    failed_dir.mkdir(parents=True)
    (failed_dir / "bad.json").write_text("not-json", encoding="utf-8")
    assert await load_failed_deliveries(base_dir=tmp_path) == []


@pytest.mark.asyncio
async def test_delete_failed_storage_provider_not_found() -> None:
    from myrm_agent_harness.infra.delivery.storage import (
        delete_failed_delivery,
    )

    class _MissingDeleteStorage:
        async def delete(self, key: str) -> None:
            raise FileNotFoundError(key)

    storage = _MissingDeleteStorage()
    assert await delete_failed_delivery("x", storage_provider=storage) is False


@pytest.mark.asyncio
async def test_load_failed_without_args_returns_empty() -> None:
    from myrm_agent_harness.infra.delivery.storage import load_failed_deliveries

    assert await load_failed_deliveries() == []


@pytest.mark.asyncio
async def test_ack_delivery_storage_provider_missing_file() -> None:
    class _AckStorage:
        async def delete(self, key: str) -> None:
            raise FileNotFoundError(key)

    await ack_delivery("ghost", storage_provider=_AckStorage())
