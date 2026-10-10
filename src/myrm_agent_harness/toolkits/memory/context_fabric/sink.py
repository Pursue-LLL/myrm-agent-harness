"""Cross-source insight sink engine for sinking conclusions to project memory.

[INPUT]
- InsightCandidate items, ProjectEntityLinker, optional ProjectContextDongleManager.

[OUTPUT]
- InsightSinkEngine: resolves project attribution, generates provenance-stamped bullets,
  and sinks records to workspace memory dongles or persistent store.

[POS]
- Insight sink and feedback engine for Item 153 CrossSourceWorkContextFabricAndProjectEntityLinkerSuite.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from myrm_agent_harness.toolkits.memory.project_dongle import (
    DongleBlock,
    DongleBlockType,
    ProjectContextDongleManager,
)

from .linker import ProjectEntityLinker
from .models import InsightCandidate, InsightSinkRecord


class InsightSinkEngine:
    """Dispatches extracted insights into targeted project memory with strict provenance."""

    def __init__(
        self,
        linker: ProjectEntityLinker,
        dongle_manager: ProjectContextDongleManager | None = None,
        auto_link_threshold: float = 0.6,
    ) -> None:
        self.linker = linker
        self.dongle_manager = dongle_manager or ProjectContextDongleManager()
        self.auto_link_threshold = auto_link_threshold
        self._sink_history: dict[str, InsightSinkRecord] = {}

    def sink_insight(
        self,
        candidate: InsightCandidate,
        workspace_dir: str | Path | None = None,
        target_file_type: DongleBlockType = DongleBlockType.PROJECT_STATE,
    ) -> InsightSinkRecord | None:
        """Resolve project attribution and sink the insight into project memory.

        Returns None if project attribution cannot be established with sufficient confidence.
        """
        # 1. Check idempotency
        if candidate.insight_id in self._sink_history:
            return self._sink_history[candidate.insight_id]

        # 2. Determine target project
        project_id = candidate.target_project_id
        if not project_id:
            matches = self.linker.link_text(
                f"{candidate.title}\n{candidate.content}",
                min_confidence=self.auto_link_threshold,
            )
            if not matches:
                return None
            project_id = matches[0].project_id

        # Verify project exists in registry
        project_entry = self.linker.get_project(project_id)
        if not project_entry:
            return None

        # 3. Format provenance and bullet content
        source_refs = ",".join(candidate.source_event_ids) if candidate.source_event_ids else "generic"
        prov_tag = f"prov:{source_refs}"
        today_str = datetime.now(UTC).strftime("%Y-%m-%d")
        block_id = uuid.uuid4().hex[:6]

        tags = ("insight", candidate.impact_level, prov_tag)
        dongle_block = DongleBlock(
            block_id=block_id,
            block_type=target_file_type,
            content=f"[{project_entry.name}] {candidate.title}: {candidate.content}",
            created_date=today_str,
            tags=tags,
        )

        rendered_bullet = dongle_block.to_markdown()

        # 4. Optional physical sink to workspace dongle
        if workspace_dir:
            ws_path = Path(workspace_dir)
            self.dongle_manager.append_block(ws_path, dongle_block)

        # 5. Create audit record
        now_ms = int(time.time() * 1000)
        record = InsightSinkRecord(
            record_id=uuid.uuid4().hex[:8],
            insight_id=candidate.insight_id,
            project_id=project_id,
            sink_target=target_file_type.value,
            written_at_ms=now_ms,
            provenance_tag=prov_tag,
            rendered_bullet=rendered_bullet,
        )

        self._sink_history[candidate.insight_id] = record
        return record

    def list_sink_records(self) -> list[InsightSinkRecord]:
        """Return all historical sink audit records."""
        return list(self._sink_history.values())
