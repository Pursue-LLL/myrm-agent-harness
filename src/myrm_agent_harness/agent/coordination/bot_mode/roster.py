"""Thread-safe registry for Named Bot Profiles ("Workstations") (Item 33).

Maintains AI colleague workstations with dual indexing by bot_id and @handle,
supporting @mention resolution, role lookup, and active status tracking.

[INPUT]
- __future__
- logging
- threading
- types

[OUTPUT]
- logger
- NamedBotRoster

[POS]
Thread-safe registry for Named Bot Profiles ("Workstations") (Item 33).
"""

from __future__ import annotations

import logging
import threading

from .types import BotProfile, BotStatus

logger = logging.getLogger(__name__)


class NamedBotRoster:
    """Thread-safe catalog of named AI colleague profiles with dual indexing."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._bots_by_id: dict[str, BotProfile] = {}
        self._bots_by_handle: dict[str, str] = {}  # normalized handle -> bot_id

    def register_bot(self, profile: BotProfile) -> None:
        """Register or update a bot profile in the roster."""
        with self._lock:
            # Check if handle is taken by another bot
            existing_id = self._bots_by_handle.get(profile.handle)
            if existing_id and existing_id != profile.bot_id:
                logger.warning(
                    "Rebinding handle '%s' from bot '%s' to '%s'",
                    profile.handle,
                    existing_id,
                    profile.bot_id,
                )

            # Clean old handle if bot_id was previously registered under a different handle
            old_bot = self._bots_by_id.get(profile.bot_id)
            if old_bot and old_bot.handle != profile.handle:
                self._bots_by_handle.pop(old_bot.handle, None)

            self._bots_by_id[profile.bot_id] = profile
            self._bots_by_handle[profile.handle] = profile.bot_id

            logger.info("Registered bot '%s' with handle '%s'", profile.bot_id, profile.handle)

    def unregister_bot(self, bot_id: str) -> bool:
        """Remove a bot profile from the roster."""
        with self._lock:
            bot = self._bots_by_id.pop(bot_id, None)
            if bot:
                self._bots_by_handle.pop(bot.handle, None)
                logger.info("Unregistered bot '%s'", bot_id)
                return True
            return False

    def get_bot_by_id(self, bot_id: str) -> BotProfile | None:
        """Lookup a bot profile by unique identifier."""
        with self._lock:
            return self._bots_by_id.get(bot_id)

    def get_bot_by_handle(self, handle: str) -> BotProfile | None:
        """Lookup a bot profile by handle (with or without leading '@')."""
        norm_handle = handle.strip().lower()
        if not norm_handle.startswith("@"):
            norm_handle = f"@{norm_handle}"

        with self._lock:
            bot_id = self._bots_by_handle.get(norm_handle)
            return self._bots_by_id.get(bot_id) if bot_id else None

    def resolve_mention(self, mention_str: str) -> BotProfile | None:
        """Resolve an @mention or raw identifier to a registered bot profile."""
        bot = self.get_bot_by_handle(mention_str)
        if bot:
            return bot
        return self.get_bot_by_id(mention_str)

    def update_status(
        self,
        bot_id: str,
        status: BotStatus,
        active_task_id: str | None = None,
    ) -> bool:
        """Update the active availability state of a bot."""
        with self._lock:
            current = self._bots_by_id.get(bot_id)
            if not current:
                return False

            updated = BotProfile(
                bot_id=current.bot_id,
                handle=current.handle,
                display_name=current.display_name,
                role_description=current.role_description,
                avatar_seed=current.avatar_seed,
                model_tier=current.model_tier,
                skills=current.skills,
                tools=current.tools,
                status=status,
                active_task_id=active_task_id,
                created_at=current.created_at,
            )
            self._bots_by_id[bot_id] = updated
            return True

    def list_bots(self, status_filter: BotStatus | None = None) -> tuple[BotProfile, ...]:
        """List all registered bots, optionally filtered by status."""
        with self._lock:
            bots = list(self._bots_by_id.values())
        if status_filter:
            bots = [b for b in bots if b.status == status_filter]
        return tuple(bots)

    def count(self) -> int:
        """Get the total count of registered bots."""
        with self._lock:
            return len(self._bots_by_id)

    def clear(self) -> None:
        """Reset the roster catalog."""
        with self._lock:
            self._bots_by_id.clear()
            self._bots_by_handle.clear()
