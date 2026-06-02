"""Delivery queue storage layer.

Handles disk persistence of queued deliveries using atomic writes.
Supports both local file system and cloud storage via StorageProvider.

[INPUT]
- pathlib.Path (POS: 队列目录，本地模式)
- myrm_agent_harness.toolkits.storage.base::StorageProvider (POS: 存储提供器，云模式)
- json (POS: 序列化)

[OUTPUT]
- QueuedDelivery: 队列投递数据类
- save_delivery: 原子写入（支持StorageProvider）
- load_pending_deliveries: 加载待投递（支持StorageProvider）
- ack_delivery: 确认成功（支持StorageProvider）
- move_to_failed: 移动到失败目录（支持StorageProvider）

[POS]
Delivery queue storage layer. Atomic writes prevent data corruption; directory structure isolates pending and failed deliveries.

"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.storage.base import StorageProvider

logger = logging.getLogger(__name__)

QUEUE_DIRNAME = "delivery-queue"
FAILED_DIRNAME = "failed"


@dataclass(frozen=True, slots=True)
class QueuedDelivery:
    """Queued delivery entry.

    Attributes:
        id: Unique delivery ID
        channel: Channel name
        recipient: Recipient ID
        content: Message content dict
        enqueued_at: Enqueue timestamp (seconds since epoch)
        priority: Priority level (0=highest, 1=high, 2=normal, 3=low, default: 2)
        retry_count: Number of retry attempts
        last_attempt_at: Last attempt timestamp (optional)
        last_error: Last error message (optional)
        failed_at: Failed timestamp for dead letter queue (optional)
    """

    id: str
    channel: str
    recipient: str
    content: dict[str, Any]
    enqueued_at: float
    priority: int = 2
    retry_count: int = 0
    last_attempt_at: float | None = None
    last_error: str | None = None
    failed_at: float | None = None


def _resolve_queue_dir(base_dir: Path) -> Path:
    """Resolve queue directory path."""
    return base_dir / QUEUE_DIRNAME


def _resolve_failed_dir(base_dir: Path) -> Path:
    """Resolve failed directory path."""
    return _resolve_queue_dir(base_dir) / FAILED_DIRNAME


def _resolve_entry_path(delivery_id: str, base_dir: Path) -> Path:
    """Resolve entry file path."""
    return _resolve_queue_dir(base_dir) / f"{delivery_id}.json"


def _resolve_failed_path(delivery_id: str, base_dir: Path) -> Path:
    """Resolve failed entry file path."""
    return _resolve_failed_dir(base_dir) / f"{delivery_id}.json"


async def ensure_queue_dir(base_dir: Path) -> Path:
    """Ensure queue directory exists.

    Creates queue directory and failed subdirectory with secure permissions.

    Args:
        base_dir: Base state directory

    Returns:
        Queue directory path
    """
    queue_dir = _resolve_queue_dir(base_dir)
    failed_dir = _resolve_failed_dir(base_dir)

    queue_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    failed_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    return queue_dir


async def save_delivery(
    delivery: QueuedDelivery,
    base_dir: Path | None = None,
    storage_provider: StorageProvider | None = None,
) -> None:
    """Save delivery to storage using atomic write.

    Supports two modes:
    1. Local file mode: Uses Path with atomic tmp file + rename
    2. StorageProvider mode: Uses cloud storage abstraction

    Args:
        delivery: Delivery to save
        base_dir: Base state directory (local mode, optional)
        storage_provider: Storage provider (cloud mode, optional)

    Raises:
        ValueError: If neither base_dir nor storage_provider is provided
    """
    if storage_provider:
        await _save_delivery_storage(delivery, storage_provider)
    elif base_dir:
        await _save_delivery_file(delivery, base_dir)
    else:
        raise ValueError("Either base_dir or storage_provider must be provided")


async def _save_delivery_file(delivery: QueuedDelivery, base_dir: Path) -> None:
    """Save delivery to local file using atomic write."""
    from myrm_agent_harness.infra.atomic_write import atomic_write

    await ensure_queue_dir(base_dir)
    file_path = _resolve_entry_path(delivery.id, base_dir)
    atomic_write(file_path, json.dumps(asdict(delivery), indent=2, ensure_ascii=False))


async def _save_delivery_storage(delivery: QueuedDelivery, storage: StorageProvider) -> None:
    """Save delivery to StorageProvider with resilience."""
    from .storage_metrics import MonitoredStorageCallback, get_global_storage_metrics
    from .storage_resilience import resilient_storage_operation

    key = f"{QUEUE_DIRNAME}/{delivery.id}.json"
    content = json.dumps(asdict(delivery), indent=2, ensure_ascii=False)

    async def _write() -> None:
        await storage.write_text(key, content)

    callback = MonitoredStorageCallback(get_global_storage_metrics())
    await resilient_storage_operation("write", _write, max_retries=3, callback=callback)


async def load_pending_deliveries(
    base_dir: Path | None = None,
    storage_provider: StorageProvider | None = None,
) -> list[QueuedDelivery]:
    """Load all pending deliveries from storage.

    Args:
        base_dir: Base state directory (local mode, optional)
        storage_provider: Storage provider (cloud mode, optional)

    Returns:
        List of pending deliveries
    """
    if storage_provider:
        return await _load_pending_storage(storage_provider)
    elif base_dir:
        return await _load_pending_file(base_dir)
    else:
        return []


async def _load_pending_file(base_dir: Path) -> list[QueuedDelivery]:
    """Load pending deliveries from local files."""
    queue_dir = _resolve_queue_dir(base_dir)

    if not queue_dir.exists():
        return []

    deliveries = []

    for file_path in queue_dir.glob("*.json"):
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)

            delivery = QueuedDelivery(
                id=data["id"],
                channel=data["channel"],
                recipient=data["recipient"],
                content=data["content"],
                enqueued_at=data["enqueued_at"],
                retry_count=data.get("retry_count", 0),
                last_attempt_at=data.get("last_attempt_at"),
                last_error=data.get("last_error"),
            )

            deliveries.append(delivery)

        except Exception as e:
            logger.error(f"Failed to load delivery from {file_path}: {e}")

    return deliveries


async def _load_pending_storage(storage: StorageProvider) -> list[QueuedDelivery]:
    """Load pending deliveries from StorageProvider with resilience."""
    from .storage_metrics import MonitoredStorageCallback, get_global_storage_metrics
    from .storage_resilience import resilient_storage_operation

    async def _list_and_load() -> list[QueuedDelivery]:
        keys = await storage.list(QUEUE_DIRNAME, recursive=False)
        deliveries = []

        for key in keys:
            if not key.endswith(".json"):
                continue

            try:
                content = await storage.read_text(key)
                data = json.loads(content)

                delivery = QueuedDelivery(
                    id=data["id"],
                    channel=data["channel"],
                    recipient=data["recipient"],
                    content=data["content"],
                    enqueued_at=data["enqueued_at"],
                    retry_count=data.get("retry_count", 0),
                    last_attempt_at=data.get("last_attempt_at"),
                    last_error=data.get("last_error"),
                )

                deliveries.append(delivery)

            except Exception as e:
                logger.error(f"Failed to load delivery from {key}: {e}")

        return deliveries

    callback = MonitoredStorageCallback(get_global_storage_metrics())
    try:
        return await resilient_storage_operation("load_pending", _list_and_load, max_retries=2, callback=callback)
    except Exception as e:
        logger.error(f"Failed to load pending deliveries after retries: {e}")
        return []


async def ack_delivery(
    delivery_id: str,
    base_dir: Path | None = None,
    storage_provider: StorageProvider | None = None,
) -> None:
    """Acknowledge successful delivery by removing from queue.

    Args:
        delivery_id: Delivery ID
        base_dir: Base state directory (local mode, optional)
        storage_provider: Storage provider (cloud mode, optional)
    """
    if storage_provider:
        from .storage_metrics import MonitoredStorageCallback, get_global_storage_metrics
        from .storage_resilience import PermanentStorageError, resilient_storage_operation

        key = f"{QUEUE_DIRNAME}/{delivery_id}.json"

        async def _delete() -> None:
            await storage_provider.delete(key)

        callback = MonitoredStorageCallback(get_global_storage_metrics())
        try:
            await resilient_storage_operation("delete", _delete, max_retries=2, callback=callback)
            logger.debug(f"Acknowledged delivery: {delivery_id}")
        except FileNotFoundError:
            pass
        except PermanentStorageError:
            pass
        except Exception as e:
            logger.warning(f"Failed to remove delivery {delivery_id} after retries: {e}")
    elif base_dir:
        file_path = _resolve_entry_path(delivery_id, base_dir)
        try:
            if file_path.exists():
                file_path.unlink()
                logger.debug(f"Acknowledged delivery: {delivery_id}")
        except Exception as e:
            logger.warning(f"Failed to remove delivery file {delivery_id}: {e}")


async def move_to_failed(
    delivery: QueuedDelivery,
    base_dir: Path | None = None,
    storage_provider: StorageProvider | None = None,
) -> None:
    """Move delivery to failed directory.

    Args:
        delivery: Delivery to move
        base_dir: Base state directory (local mode, optional)
        storage_provider: Storage provider (cloud mode, optional)
    """
    import time
    from dataclasses import replace

    # Update delivery with failed timestamp if not already set
    if delivery.failed_at is None:
        delivery_with_failed_at = replace(delivery, failed_at=time.time())
    else:
        delivery_with_failed_at = delivery

    if storage_provider:
        from .storage_metrics import MonitoredStorageCallback, get_global_storage_metrics
        from .storage_resilience import resilient_storage_operation

        failed_key = f"{QUEUE_DIRNAME}/{FAILED_DIRNAME}/{delivery.id}.json"
        content = json.dumps(asdict(delivery_with_failed_at), indent=2, ensure_ascii=False)

        async def _move_to_failed() -> None:
            # Save to failed directory
            await storage_provider.write_text(failed_key, content)

            # Remove from queue
            queue_key = f"{QUEUE_DIRNAME}/{delivery.id}.json"
            with contextlib.suppress(FileNotFoundError):
                await storage_provider.delete(queue_key)

        callback = MonitoredStorageCallback(get_global_storage_metrics())
        try:
            await resilient_storage_operation("move_to_failed", _move_to_failed, max_retries=3, callback=callback)
            logger.info(f"Moved delivery to failed: {delivery.id}")
        except Exception as e:
            logger.error(f"Failed to move delivery {delivery.id} to failed after retries: {e}")

    elif base_dir:
        await ensure_queue_dir(base_dir)

        src_path = _resolve_entry_path(delivery.id, base_dir)
        dst_path = _resolve_failed_path(delivery.id, base_dir)

        try:
            # Save to failed directory
            with open(dst_path, "w", encoding="utf-8") as f:
                json.dump(asdict(delivery_with_failed_at), f, indent=2)

            # Set secure permissions
            os.chmod(dst_path, 0o600)

            # Remove from queue
            if src_path.exists():
                src_path.unlink()

            logger.info(f"Moved delivery to failed: {delivery.id}")

        except Exception as e:
            logger.error(f"Failed to move delivery {delivery.id} to failed: {e}")


async def move_to_pending(
    delivery: QueuedDelivery,
    base_dir: Path | None = None,
    storage_provider: StorageProvider | None = None,
) -> None:
    """Move delivery from failed back to pending.

    Args:
        delivery: Delivery to move
        base_dir: Base state directory (local mode, optional)
        storage_provider: Storage provider (cloud mode, optional)
    """
    if storage_provider:
        try:
            # Save to pending directory
            await save_delivery(delivery, storage_provider=storage_provider)

            # Remove from failed
            failed_key = f"{QUEUE_DIRNAME}/{FAILED_DIRNAME}/{delivery.id}.json"
            with contextlib.suppress(FileNotFoundError):
                await storage_provider.delete(failed_key)

            logger.info(f"Moved delivery from failed to pending: {delivery.id}")

        except Exception as e:
            logger.error(f"Failed to move delivery {delivery.id} to pending: {e}")

    elif base_dir:
        await ensure_queue_dir(base_dir)

        src_path = _resolve_failed_path(delivery.id, base_dir)

        try:
            # Save to pending directory
            await save_delivery(delivery, base_dir=base_dir)

            # Remove from failed
            if src_path.exists():
                src_path.unlink()

            logger.info(f"Moved delivery from failed to pending: {delivery.id}")

        except Exception as e:
            logger.error(f"Failed to move delivery {delivery.id} to pending: {e}")


async def load_failed_deliveries(
    base_dir: Path | None = None,
    storage_provider: StorageProvider | None = None,
) -> list[QueuedDelivery]:
    """Load all failed deliveries.

    Args:
        base_dir: Base state directory (local mode, optional)
        storage_provider: Storage provider (cloud mode, optional)

    Returns:
        List of failed deliveries
    """
    if storage_provider:
        return await _load_failed_storage(storage_provider)
    elif base_dir:
        return await _load_failed_file(base_dir)
    else:
        return []


async def _load_failed_file(base_dir: Path) -> list[QueuedDelivery]:
    """Load failed deliveries from local files."""
    await ensure_queue_dir(base_dir)
    failed_dir = _resolve_failed_dir(base_dir)

    if not failed_dir.exists():
        return []

    deliveries = []
    for file_path in failed_dir.glob("*.json"):
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
                delivery = QueuedDelivery(**data)
                deliveries.append(delivery)
        except Exception as e:
            logger.warning(f"Failed to load failed delivery {file_path.name}: {e}")

    return deliveries


async def _load_failed_storage(storage: StorageProvider) -> list[QueuedDelivery]:
    """Load failed deliveries from StorageProvider."""
    try:
        failed_prefix = f"{QUEUE_DIRNAME}/{FAILED_DIRNAME}"
        keys = await storage.list(failed_prefix, recursive=False)
        deliveries = []

        for key in keys:
            if not key.endswith(".json"):
                continue

            try:
                content = await storage.read_text(key)
                data = json.loads(content)
                delivery = QueuedDelivery(**data)
                deliveries.append(delivery)
            except Exception as e:
                logger.warning(f"Failed to load failed delivery {key}: {e}")

        return deliveries

    except Exception as e:
        logger.error(f"Failed to list failed deliveries from storage: {e}")
        return []


async def delete_failed_delivery(
    delivery_id: str,
    base_dir: Path | None = None,
    storage_provider: StorageProvider | None = None,
) -> bool:
    """Delete delivery from failed directory.

    Args:
        delivery_id: Delivery ID
        base_dir: Base state directory (local mode, optional)
        storage_provider: Storage provider (cloud mode, optional)

    Returns:
        True if deleted, False if not found
    """
    if storage_provider:
        failed_key = f"{QUEUE_DIRNAME}/{FAILED_DIRNAME}/{delivery_id}.json"
        try:
            await storage_provider.delete(failed_key)
            logger.debug(f"Deleted failed delivery: {delivery_id}")
            return True
        except FileNotFoundError:
            return False
        except Exception as e:
            logger.warning(f"Failed to delete failed delivery {delivery_id}: {e}")
            return False

    elif base_dir:
        failed_path = _resolve_failed_path(delivery_id, base_dir)
        try:
            if failed_path.exists():
                failed_path.unlink()
                logger.debug(f"Deleted failed delivery: {delivery_id}")
                return True
            return False
        except Exception as e:
            logger.warning(f"Failed to delete failed delivery {delivery_id}: {e}")
            return False

    return False


def generate_delivery_id(channel: str, recipient: str) -> str:
    """Generate unique delivery ID.

    Args:
        channel: Channel name
        recipient: Recipient ID

    Returns:
        Unique delivery ID
    """
    return f"{channel}_{recipient}_{uuid.uuid4().hex[:16]}"
