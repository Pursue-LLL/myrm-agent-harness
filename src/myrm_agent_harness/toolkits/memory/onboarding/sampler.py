"""Multi-source conversation sliding window sampler and sanitizer.

[INPUT]
- typing: List, Dict, Optional, Tuple
- re: Inline media payload cleanup
- .models: OnboardingSampleOptions, SampledTurnMessage, OnboardingConversationWindow
- .redactor: LocalSecretRedactor
- .registry: OnboardingSourceRegistry

[OUTPUT]
- MultiSourceOnboardingSampler: Extracts sanitized keyframe message windows from agent logs.

[POS]
Harness framework core sampling engine that compresses large external conversation histories
into lightweight, credential-scrubbed context windows for fast insight distillation.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .models import OnboardingConversationWindow, OnboardingSampleOptions, SampledTurnMessage
from .redactor import LocalSecretRedactor

if TYPE_CHECKING:
    from .registry import OnboardingSourceRegistry

_INLINE_MEDIA_PATTERN = re.compile(r"data:image\/[a-zA-Z]+;base64,[A-Za-z0-9+/=]{100,}")


class MultiSourceOnboardingSampler:
    """Extracts first-2 and last-12 turn keyframes from agent sessions with local secret scrubbing."""

    def __init__(
        self,
        registry: OnboardingSourceRegistry,
        options: OnboardingSampleOptions | None = None,
    ) -> None:
        self._registry = registry
        self._options = options or OnboardingSampleOptions()
        self._redactor = LocalSecretRedactor(
            enable_entropy=self._options.enable_entropy_inspection,
        )

    def _clean_text(self, text: str, role: str) -> str:
        """Strip inline media and truncate per-role message character budgets."""
        cleaned = text
        if self._options.strip_media_payloads:
            cleaned = _INLINE_MEDIA_PATTERN.sub("[INLINE_MEDIA_PAYLOAD_REDACTED]", cleaned)

        # Apply per-role max characters
        if role == "user":
            cleaned = cleaned[: self._options.max_user_chars]
        elif role == "assistant":
            cleaned = cleaned[: self._options.max_assistant_chars]
        elif role == "tool":
            cleaned = cleaned[: self._options.max_tool_chars]

        return cleaned

    def sample_messages(
        self,
        messages: list[SampledTurnMessage],
    ) -> tuple[list[SampledTurnMessage], bool, int]:
        """Apply first-2 and last-12 turns sliding window selection and secret redaction."""
        if not messages:
            return [], False, 0

        first_n = self._options.first_conversation_turns
        last_n = self._options.last_conversation_turns

        # If total turns are small, keep all
        if len(messages) <= (first_n + last_n):
            selected_indices = list(range(len(messages)))
        else:
            first_indices = list(range(min(first_n, len(messages))))
            last_indices = list(range(max(0, len(messages) - last_n), len(messages)))
            selected_indices = sorted(list(set(first_indices + last_indices)))

        sampled: list[SampledTurnMessage] = []
        total_chars = 0
        truncated = False
        total_redactions = 0

        for idx in selected_indices:
            msg = messages[idx]
            cleaned_text = self._clean_text(msg.text, msg.role)
            scrubbed_text, redactions = self._redactor.scrub(cleaned_text)
            total_redactions += redactions

            if total_chars + len(scrubbed_text) > self._options.max_window_chars:
                remaining_budget = max(0, self._options.max_window_chars - total_chars)
                if remaining_budget > 50:
                    scrubbed_text = scrubbed_text[:remaining_budget] + "... [TRUNCATED]"
                    sampled.append(
                        SampledTurnMessage(
                            source_id=msg.source_id,
                            conversation_id=msg.conversation_id,
                            message_id=msg.message_id,
                            role=msg.role,
                            text=scrubbed_text,
                            created_at=msg.created_at,
                            workspace_path=msg.workspace_path,
                        )
                    )
                truncated = True
                break

            total_chars += len(scrubbed_text)
            sampled.append(
                SampledTurnMessage(
                    source_id=msg.source_id,
                    conversation_id=msg.conversation_id,
                    message_id=msg.message_id,
                    role=msg.role,
                    text=scrubbed_text,
                    created_at=msg.created_at,
                    workspace_path=msg.workspace_path,
                )
            )

        return sampled, truncated, total_redactions

    def sample_source(
        self,
        source_id: str,
    ) -> list[OnboardingConversationWindow]:
        """Sample all active recent conversation files for a specific agent source."""
        adapter = self._registry.get(source_id)
        if not adapter or not adapter.detect_active():
            return []

        recent_files = adapter.scan_recent_sessions(limit=self._options.max_session_files)
        windows: list[OnboardingConversationWindow] = []

        for file_path in recent_files:
            try:
                raw_messages = adapter.extract_turn_messages(file_path)
                sampled_messages, truncated, _ = self.sample_messages(raw_messages)
                total_chars = sum(len(m.text) for m in sampled_messages)

                windows.append(
                    OnboardingConversationWindow(
                        source_id=source_id,
                        conversation_id=file_path.stem,
                        display_name=adapter.display_name,
                        file_path=str(file_path),
                        messages=sampled_messages,
                        total_chars=total_chars,
                        truncated=truncated,
                    )
                )
            except Exception as e:
                windows.append(
                    OnboardingConversationWindow(
                        source_id=source_id,
                        conversation_id=file_path.stem,
                        display_name=adapter.display_name,
                        file_path=str(file_path),
                        error=str(e),
                    )
                )

        return windows

    def sample_all_active_sources(self) -> list[OnboardingConversationWindow]:
        """Detect all active host sources and sample keyframes across all of them."""
        all_windows: list[OnboardingConversationWindow] = []
        active_sources = self._registry.detect_active_sources()
        for source_id in active_sources:
            all_windows.extend(self.sample_source(source_id))
        return all_windows
