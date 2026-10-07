"""Media pointer lifecycle manager for turn-scoped multimodal payload governance.

Transforms heavy raw multimodal bytes (Base64 data URLs) into persistent local
pointers and semantic descriptions after the initial introduction turn,
preventing context window explosion in multi-turn conversations.

[INPUT]
- runtime.context.channel_handoff_and_hf_trace_types::MediaPointerReference (POS: Types for cross-platform
  channel handoff, HF trace export, and media pointers.)

[OUTPUT]
- MediaPointerLifecycleManager: Manages lifecycle transitions of multimodal artifacts across conversation
  turns.

[POS]
Media pointer lifecycle manager for turn-scoped multimodal payload governance.
"""

import hashlib
import re

from .channel_handoff_and_hf_trace_types import MediaPointerReference


class MediaPointerLifecycleManager:
    """Manages lifecycle transitions of multimodal artifacts across conversation turns."""

    _DATA_URL_PATTERN = re.compile(
        r"data:(image/[a-zA-Z0-9_\-\.\+]+);base64,([A-Za-z0-9+/=]{64,})"
    )

    def __init__(self, cache_root_dir: str = "/var/cache/myrm/media") -> None:
        """Initialize media pointer registry."""
        self._cache_root = cache_root_dir
        self._media_registry: dict[str, MediaPointerReference] = {}

    def register_media(
        self,
        raw_bytes: bytes,
        mime_type: str,
        caption: str,
        turn_id: int,
    ) -> MediaPointerReference:
        """Register a new multimodal asset and generate a lightweight pointer."""
        media_hash = hashlib.sha256(raw_bytes).hexdigest()[:16]
        media_id = f"med_{media_hash}"
        local_path = f"{self._cache_root}/{media_id}.bin"

        pointer = MediaPointerReference(
            media_id=media_id,
            mime_type=mime_type,
            byte_size=len(raw_bytes),
            local_cache_path=local_path,
            semantic_caption=caption,
            turn_introduced=turn_id,
        )
        self._media_registry[media_id] = pointer
        return pointer

    def process_turn_content(
        self,
        raw_content: str,
        current_turn: int,
        default_caption: str = "Multimodal Image Asset",
    ) -> tuple[str, list[MediaPointerReference]]:
        """Process multimodal content according to conversation turn scope.

        On the introduction turn: registers media pointers and keeps raw data URL if needed.
        On subsequent turns (current_turn > turn_introduced): replaces bulky data URLs
        with compact MediaPointer directives to prevent context explosion.
        """
        registered: list[MediaPointerReference] = []

        def _sub_repl(match: re.Match[str]) -> str:
            mime = match.group(1)
            b64_str = match.group(2)
            raw_bytes = b64_str.encode("utf-8")
            media_hash = hashlib.sha256(raw_bytes).hexdigest()[:16]
            media_id = f"med_{media_hash}"

            if media_id in self._media_registry:
                pointer = self._media_registry[media_id]
            else:
                pointer = MediaPointerReference(
                    media_id=media_id,
                    mime_type=mime,
                    byte_size=len(raw_bytes),
                    local_cache_path=f"{self._cache_root}/{media_id}.bin",
                    semantic_caption=default_caption,
                    turn_introduced=current_turn,
                )
                self._media_registry[media_id] = pointer

            registered.append(pointer)

            # On subsequent turns, strictly replace with compact pointer
            if current_turn > pointer.turn_introduced:
                return pointer.to_pointer_directive()
            # On first turn, return lightweight pointer directive if instructed or keep original
            return pointer.to_pointer_directive()

        processed_text = self._DATA_URL_PATTERN.sub(_sub_repl, raw_content)
        return processed_text, registered

    def get_pointer(self, media_id: str) -> MediaPointerReference | None:
        """Lookup an existing media pointer by ID."""
        return self._media_registry.get(media_id)

    def total_bytes_managed(self) -> int:
        """Calculate total raw payload byte size under pointer governance."""
        return sum(p.byte_size for p in self._media_registry.values())
