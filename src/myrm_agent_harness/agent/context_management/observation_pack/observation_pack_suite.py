"""Comprehensive facade suite for observation pack archival and paged recall.

[INPUT]
- ContentAddressedStore, ObservationDegradationPipeline, ObservationPackConfig, ObservationRecallTool,
  PackBatchResult, TransformDecision: Domain types and engines from observation_pack.

[OUTPUT]
- ObservationPackPagedRecallAndLongOutputHandleArchivalSuite: Central facade managing content-addressed
  archival, 2-turn full send windows, compact handle degradation, and on-demand paged recall.

[POS]
Top-level entrypoint for NVIDIA SoL-Pi inspired large observation lifecycle management.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .content_addressed_store import ContentAddressedStore
from .observation_degradation_pipeline import ObservationDegradationPipeline
from .observation_pack_types import (
    ObservationPackConfig,
    PackBatchResult,
    TransformDecision,
)
from .observation_recall_tool import ObservationRecallTool


class ObservationPackPagedRecallAndLongOutputHandleArchivalSuite:
    """Orchestrates observation archival, sliding-window degradation, and paged retrieval."""

    def __init__(
        self,
        config: ObservationPackConfig | None = None,
        storage_dir: str | None = None,
    ) -> None:
        self._config = config or ObservationPackConfig()
        self._store = ContentAddressedStore(config=self._config, storage_dir=storage_dir)
        self._pipeline = ObservationDegradationPipeline(store=self._store, config=self._config)
        self._recall_tool = ObservationRecallTool(store=self._store)

    @property
    def config(self) -> ObservationPackConfig:
        return self._config

    @property
    def store(self) -> ContentAddressedStore:
        return self._store

    @property
    def pipeline(self) -> ObservationDegradationPipeline:
        return self._pipeline

    @property
    def recall_tool(self) -> ObservationRecallTool:
        return self._recall_tool

    def get_meta_tool_spec(self) -> Mapping[str, object]:
        """Return the function specification for registration in the agent's tool catalog."""
        return self._recall_tool.get_tool_spec()

    def process_observation(
        self,
        text: str,
        session_id: str = "default",
    ) -> tuple[str, TransformDecision]:
        """Process a single observation string under degradation policies."""
        return self._pipeline.process_observation(text=text, session_id=session_id)

    def recall_observation(
        self,
        obs_id: str,
        page: int = 1,
        page_size: int = 100,
    ) -> str:
        """Recall an archived observation slice by its handle ID."""
        return self._recall_tool.execute(obs_id=obs_id, page=page, page_size=page_size)

    def get_raw_observation(self, obs_id: str) -> str | None:
        """Retrieve 100% full un-truncated content for an observation handle."""
        return self._store.get_content(obs_id)

    def transform_turn_messages(
        self,
        messages: Sequence[Mapping[str, str]],
        session_id: str = "default",
    ) -> PackBatchResult:
        """Transform a sequence of message dicts, compacting eligible tool observations."""
        transformed_messages: list[dict[str, str]] = []
        decisions: list[TransformDecision] = []
        bytes_saved = 0
        degraded_count = 0
        exempt_count = 0

        for msg in messages:
            msg_copy = dict(msg)
            content = msg_copy.get("content", "")
            role = msg_copy.get("role", "")

            # Tool and system observation payloads are eligible for degradation
            if role in ("tool", "function") or "[Observation" in content or len(content.encode("utf-8")) > self._config.threshold_bytes:
                new_content, decision = self._pipeline.process_observation(content, session_id=session_id)
                msg_copy["content"] = new_content
                decisions.append(decision)

                if decision.action == "DEGRADED_PLACEHOLDER":
                    degraded_count += 1
                    bytes_saved += max(0, decision.original_bytes - decision.transformed_bytes)
                elif decision.action == "EXEMPT_RECEIPT":
                    exempt_count += 1

            transformed_messages.append(msg_copy)

        tokens_saved_estimate = bytes_saved // 4

        return PackBatchResult(
            processed_count=len(messages),
            degraded_count=degraded_count,
            exempt_count=exempt_count,
            bytes_saved=bytes_saved,
            tokens_saved_estimate=tokens_saved_estimate,
            messages=transformed_messages,
            decisions=decisions,
        )

    def reset_session(self, session_id: str = "default") -> None:
        """Reset state for a session."""
        self._pipeline.reset_session(session_id)

    @classmethod
    def create(
        cls,
        threshold_bytes: int = 10 * 1024,
        full_sends: int = 2,
        storage_dir: str | None = None,
    ) -> ObservationPackPagedRecallAndLongOutputHandleArchivalSuite:
        """Create a configured suite instance."""
        config = ObservationPackConfig(threshold_bytes=threshold_bytes, full_sends=full_sends)
        return cls(config=config, storage_dir=storage_dir)
