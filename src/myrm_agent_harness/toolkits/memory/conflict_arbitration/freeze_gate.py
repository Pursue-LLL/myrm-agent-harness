# [POS] src/myrm_agent_harness/toolkits/memory/conflict_arbitration/freeze_gate.py
# [INPUT] .types (UserConfirmedFreezeLock, UserConfirmedFreezeViolationError)
# [OUTPUT] UserConfirmedFreezeGate

import logging
from threading import RLock

from .types import UserConfirmedFreezeLock, UserConfirmedFreezeViolationError

logger = logging.getLogger(__name__)


class UserConfirmedFreezeGate:
    """Gatekeeper enforcing immutable freeze locks on facts confirmed by human operators.

    Guarantees that automated agent reflection, memory consolidation, and LLM background
    summarizers can never silently alter, overwrite, or delete human-finalized decisions.
    """

    def __init__(self) -> None:
        self._lock: RLock = RLock()
        self._registry: dict[str, UserConfirmedFreezeLock] = {}

    def freeze(
        self,
        memory_id: str,
        content: str,
        confirmed_by: str,
        lock_version: int = 1,
    ) -> UserConfirmedFreezeLock:
        """Place an immutable freeze lock on a specific memory record.

        Args:
            memory_id: Unique identifier of the memory item.
            content: The finalized immutable content text.
            confirmed_by: Operator or user identifier who confirmed this fact.
            lock_version: Monotonically increasing version number for the lock.

        Returns:
            The newly created UserConfirmedFreezeLock with cryptographic hash.
        """
        with self._lock:
            existing = self._registry.get(memory_id)
            target_version = lock_version
            if existing is not None:
                target_version = max(lock_version, existing.lock_version + 1)

            freeze_lock = UserConfirmedFreezeLock(
                memory_id=memory_id,
                frozen_content=content,
                confirmed_by=confirmed_by,
                is_active=True,
                lock_version=target_version,
            )
            self._registry[memory_id] = freeze_lock
            logger.info(
                "Memory '%s' locked by '%s' with hash '%s' (v%d)",
                memory_id,
                confirmed_by,
                freeze_lock.immutable_hash,
                freeze_lock.lock_version,
            )
            return freeze_lock

    def is_frozen(self, memory_id: str) -> bool:
        """Check whether a memory item is under an active freeze lock."""
        with self._lock:
            lock_item = self._registry.get(memory_id)
            return lock_item is not None and lock_item.is_active

    def get_lock(self, memory_id: str) -> UserConfirmedFreezeLock | None:
        """Retrieve the freeze lock for a given memory item, if present."""
        with self._lock:
            return self._registry.get(memory_id)

    def list_frozen_memory_ids(self) -> list[str]:
        """List all memory IDs currently protected by an active freeze lock."""
        with self._lock:
            return [k for k, v in self._registry.items() if v.is_active]

    def check_mutation_allowed(
        self,
        memory_id: str,
        proposed_content: str,
        is_human_override: bool = False,
    ) -> None:
        """Validate whether a mutation (write, overwrite, deletion) is permitted on a memory item.

        Args:
            memory_id: Target memory identifier.
            proposed_content: New content attempted to be written.
            is_human_override: Explicit flag indicating this mutation originates from
                a verified human operator decision.

        Raises:
            UserConfirmedFreezeViolationError: If memory is frozen and mutation is automated.
        """
        with self._lock:
            lock_item = self._registry.get(memory_id)
            if lock_item is None or not lock_item.is_active:
                return

            # Verify lock integrity first
            if not lock_item.verify_integrity():
                logger.error("Tampered freeze lock detected for memory '%s'!", memory_id)
                raise UserConfirmedFreezeViolationError(
                    memory_id,
                    "Cryptographic integrity mismatch on freeze lock. Possible tampering.",
                )

            if not is_human_override:
                logger.warning(
                    "Blocked automated mutation on user-confirmed memory '%s'.",
                    memory_id,
                )
                raise UserConfirmedFreezeViolationError(
                    memory_id,
                    f"Locked by operator '{lock_item.confirmed_by}'. Automated overwrite is forbidden.",
                )

            logger.info(
                "Human override granted for frozen memory '%s'. Proposed length: %d",
                memory_id,
                len(proposed_content),
            )

    def unlock(self, memory_id: str, operator_id: str, reason: str) -> bool:
        """Explicitly deactivate a freeze lock by human operator action."""
        with self._lock:
            lock_item = self._registry.get(memory_id)
            if lock_item is None or not lock_item.is_active:
                return False

            deactivated = UserConfirmedFreezeLock(
                memory_id=lock_item.memory_id,
                frozen_content=lock_item.frozen_content,
                confirmed_by=operator_id,
                is_active=False,
                lock_version=lock_item.lock_version + 1,
            )
            self._registry[memory_id] = deactivated
            logger.info(
                "Memory '%s' unlocked by operator '%s'. Reason: %s",
                memory_id,
                operator_id,
                reason,
            )
            return True

    def verify_all_locks(self) -> dict[str, bool]:
        """Verify the integrity of all registered freeze locks."""
        with self._lock:
            return {
                mid: lock_item.verify_integrity()
                for mid, lock_item in self._registry.items()
            }
