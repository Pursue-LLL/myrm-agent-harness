"""Content-addressed immutable store for large tool observations.

[INPUT]
- ObservationHandle, ObservationPackConfig, ObservationPage: Domain types from observation_pack_types.

[OUTPUT]
- ContentAddressedStore: Storage engine computing SHA-256 digests, indexing observation handles,
  and offering paged text slices.

[POS]
Local object storage engine powering lossless archival and on-demand retrieval for large outputs.
"""

from __future__ import annotations

import hashlib
import math
import os
import time
from typing import Dict, Optional, Sequence

from .observation_pack_types import ObservationHandle, ObservationPackConfig, ObservationPage


class ContentAddressedStore:
    """Immutable content-addressed store indexed by cryptographic SHA-256 observation handles."""

    def __init__(
        self,
        config: ObservationPackConfig | None = None,
        storage_dir: str | None = None,
    ) -> None:
        self._config = config or ObservationPackConfig()
        self._storage_dir = storage_dir
        self._memory_contents: Dict[str, str] = {}
        self._handles: Dict[str, ObservationHandle] = {}

        if self._storage_dir:
            os.makedirs(self._storage_dir, exist_ok=True)

    @property
    def config(self) -> ObservationPackConfig:
        return self._config

    def compute_sha256(self, content: str) -> str:
        """Compute hex-encoded SHA-256 digest of content string."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def format_obs_id(self, sha256_hex: str) -> str:
        """Construct canonical observation handle ID from SHA-256 digest."""
        return f"obs_{sha256_hex[:24]}"

    def store(self, content: str) -> ObservationHandle:
        """Store content immutably and return its observation handle descriptor."""
        sha256_hex = self.compute_sha256(content)
        obs_id = self.format_obs_id(sha256_hex)

        if obs_id in self._handles:
            return self._handles[obs_id]

        content_bytes = content.encode("utf-8")
        byte_size = len(content_bytes)
        lines = content.splitlines()
        line_count = len(lines)

        head_budget = self._config.head_bytes
        tail_budget = self._config.tail_bytes

        head_excerpt = content_bytes[:head_budget].decode("utf-8", errors="replace")
        if byte_size > head_budget + tail_budget:
            tail_excerpt = content_bytes[-tail_budget:].decode("utf-8", errors="replace")
        else:
            tail_excerpt = ""

        handle = ObservationHandle(
            obs_id=obs_id,
            sha256_hash=sha256_hex,
            byte_size=byte_size,
            line_count=line_count,
            head_excerpt=head_excerpt,
            tail_excerpt=tail_excerpt,
            created_at=time.time(),
        )

        self._memory_contents[obs_id] = content
        self._handles[obs_id] = handle

        if self._storage_dir:
            file_path = os.path.join(self._storage_dir, f"{obs_id}.txt")
            if not os.path.exists(file_path):
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(content)

        return handle

    def get_handle(self, obs_id: str) -> Optional[ObservationHandle]:
        """Retrieve handle descriptor for an observation ID."""
        return self._handles.get(obs_id)

    def get_content(self, obs_id: str) -> Optional[str]:
        """Retrieve full original content for an observation ID."""
        if obs_id in self._memory_contents:
            return self._memory_contents[obs_id]

        if self._storage_dir:
            file_path = os.path.join(self._storage_dir, f"{obs_id}.txt")
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                self._memory_contents[obs_id] = content
                return content

        return None

    def get_page(
        self,
        obs_id: str,
        page: int = 1,
        page_size: int | None = None,
    ) -> Optional[ObservationPage]:
        """Fetch a specific 1-indexed page slice from an archived observation."""
        content = self.get_content(obs_id)
        if content is None:
            return None

        effective_page_size = page_size or self._config.default_page_size
        if effective_page_size <= 0:
            effective_page_size = self._config.default_page_size

        all_lines = content.splitlines()
        total_lines = len(all_lines)

        if total_lines == 0:
            return ObservationPage(
                obs_id=obs_id,
                page=1,
                page_size=effective_page_size,
                total_pages=1,
                total_lines=0,
                lines=[],
                has_more=False,
            )

        total_pages = max(1, math.ceil(total_lines / effective_page_size))
        clamped_page = max(1, min(page, total_pages))

        start_idx = (clamped_page - 1) * effective_page_size
        end_idx = min(start_idx + effective_page_size, total_lines)
        page_lines: Sequence[str] = all_lines[start_idx:end_idx]

        return ObservationPage(
            obs_id=obs_id,
            page=clamped_page,
            page_size=effective_page_size,
            total_pages=total_pages,
            total_lines=total_lines,
            lines=page_lines,
            has_more=clamped_page < total_pages,
        )

    def total_stored_observations(self) -> int:
        """Return total count of unique stored observation handles."""
        return len(self._handles)
