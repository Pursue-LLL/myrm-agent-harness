"""[POS]: src/myrm_agent_harness/toolkits/memory/migration/detector.py
[INPUT]: Optional custom filesystem search roots and environment directories.
[OUTPUT]: DetectedCompetitorArtifact lists identifying available migration targets.
"""

import json
import time
from pathlib import Path

from myrm_agent_harness.toolkits.memory.migration.models import (
    CompetitorSourceKind,
    DetectedCompetitorArtifact,
)


class CompetitorAssetScanner:
    """Safe local filesystem scanner detecting external competitor memory archives."""

    def __init__(self, home_dir: Path | None = None) -> None:
        self._home = home_dir if home_dir is not None else Path.home()

    def scan(
        self, custom_candidates: list[str] | None = None
    ) -> list[DetectedCompetitorArtifact]:
        """Discover candidate competitor memory artifacts on local system."""
        artifacts: list[DetectedCompetitorArtifact] = []

        # 1. Hermes default paths
        hermes_dir = self._home / ".hermes" / "memories"
        if hermes_dir.is_dir():
            for fname in ("MEMORY.md", "USER.md"):
                fpath = hermes_dir / fname
                if fpath.is_file():
                    count = self._estimate_md_entries(fpath)
                    artifacts.append(
                        DetectedCompetitorArtifact(
                            source_kind=CompetitorSourceKind.HERMES,
                            artifact_path=str(fpath.resolve()),
                            estimated_entries=count,
                            detected_timestamp=time.time(),
                            summary=f"Hermes native {fname} context file ({count} 条预估记忆)",
                        )
                    )

        # 2. OpenClaw default paths
        openclaw_dir = self._home / ".openclaw"
        if openclaw_dir.is_dir():
            for fname in ("memory.json", "skills_memory.json"):
                fpath = openclaw_dir / fname
                if fpath.is_file():
                    count = self._estimate_json_entries(fpath)
                    artifacts.append(
                        DetectedCompetitorArtifact(
                            source_kind=CompetitorSourceKind.OPENCLAW,
                            artifact_path=str(fpath.resolve()),
                            estimated_entries=count,
                            detected_timestamp=time.time(),
                            summary=f"OpenClaw native {fname} database ({count} 条预估记忆)",
                        )
                    )

        # 3. Custom path overrides or workspace paths
        if custom_candidates:
            for p_str in custom_candidates:
                p = Path(p_str)
                if not p.exists():
                    continue
                if p.is_file():
                    self._inspect_file_candidate(p, artifacts)
                elif p.is_dir():
                    for sub in p.iterdir():
                        if sub.is_file():
                            self._inspect_file_candidate(sub, artifacts)

        return artifacts

    def _inspect_file_candidate(
        self, path: Path, out_list: list[DetectedCompetitorArtifact]
    ) -> None:
        name_lower = path.name.lower()
        if "hermes" in name_lower or name_lower in ("memory.md", "user.md"):
            count = self._estimate_md_entries(path)
            out_list.append(
                DetectedCompetitorArtifact(
                    source_kind=CompetitorSourceKind.HERMES,
                    artifact_path=str(path.resolve()),
                    estimated_entries=count,
                    detected_timestamp=time.time(),
                    summary=f"Custom Hermes memory file ({count} 条预估条目)",
                )
            )
        elif "openclaw" in name_lower:
            count = self._estimate_json_entries(path)
            out_list.append(
                DetectedCompetitorArtifact(
                    source_kind=CompetitorSourceKind.OPENCLAW,
                    artifact_path=str(path.resolve()),
                    estimated_entries=count,
                    detected_timestamp=time.time(),
                    summary=f"Custom OpenClaw memory export ({count} 条预估条目)",
                )
            )
        elif "chatgpt" in name_lower and path.suffix == ".json":
            count = self._estimate_json_entries(path)
            out_list.append(
                DetectedCompetitorArtifact(
                    source_kind=CompetitorSourceKind.CHATGPT_EXPORT,
                    artifact_path=str(path.resolve()),
                    estimated_entries=count,
                    detected_timestamp=time.time(),
                    summary=f"ChatGPT data export archive ({count} 条预估记录)",
                )
            )
        elif path.suffix == ".json":
            count = self._estimate_json_entries(path)
            if count > 0:
                out_list.append(
                    DetectedCompetitorArtifact(
                        source_kind=CompetitorSourceKind.GENERIC_JSON,
                        artifact_path=str(path.resolve()),
                        estimated_entries=count,
                        detected_timestamp=time.time(),
                        summary=f"Generic structured JSON memories ({count} 条记录)",
                    )
                )

    def _estimate_md_entries(self, path: Path) -> int:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            lines = [
                line.strip()
                for line in content.splitlines()
                if line.strip().startswith(("#", "-", "*"))
            ]
            return max(1, len(lines))
        except OSError:
            return 0

    def _estimate_json_entries(self, path: Path) -> int:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            data: dict[str, str | int | float | list[dict[str, str]]] | list[
                dict[str, str]
            ] = json.loads(content)
            if isinstance(data, list):
                return len(data)
            if isinstance(data, dict):
                memories_field = data.get("memories") or data.get("entries")
                if isinstance(memories_field, list):
                    return len(memories_field)
                return len(data)
            return 0
        except (OSError, json.JSONDecodeError):
            return 0
