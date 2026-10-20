"""Local filesystem-based peer registry for zero-broker agent mesh discovery.

[INPUT]
- __future__
- json
- os
- sys
- time
- pathlib

[OUTPUT]
- MeshRegistry

[POS]
Local filesystem-based peer registry for zero-broker agent mesh discovery.

"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from .types import PeerStatus, RegistryEntry


class MeshRegistry:
    """Manages decentralized agent discovery via per-project registry files.

    Location pattern:
        ~/.myrm/coms/projects/<project>/agents/<name>.json
    Sockets pattern:
        ~/.myrm/coms/sockets/<session_id>.sock (POSIX) or \\\\.\\pipe\\myrm-coms-<session_id> (Windows)
    """

    def __init__(
        self,
        base_dir: str | None = None,
        stale_threshold_seconds: float = 30.0,
        offline_threshold_seconds: float = 120.0,
    ) -> None:
        if base_dir:
            self.base_dir = Path(base_dir)
        else:
            env_dir = os.environ.get("MYRM_COMS_DIR")
            self.base_dir = Path(env_dir) if env_dir else Path.home() / ".myrm" / "coms"

        self.stale_threshold_seconds = stale_threshold_seconds
        self.offline_threshold_seconds = offline_threshold_seconds
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        """Create root and sockets folders if not existing."""
        (self.base_dir / "sockets").mkdir(parents=True, exist_ok=True)
        (self.base_dir / "projects").mkdir(parents=True, exist_ok=True)

    def _get_project_agents_dir(self, project: str) -> Path:
        """Return the directory containing agent registry files for a specific project."""
        clean_project = project.strip().replace("/", "_").replace("\\", "_")
        target = self.base_dir / "projects" / clean_project / "agents"
        target.mkdir(parents=True, exist_ok=True)
        return target

    def get_endpoint(self, session_id: str) -> str:
        """Return cross-platform local IPC endpoint path."""
        if sys.platform == "win32":
            return rf"\\.\pipe\myrm-coms-{session_id}"
        return str(self.base_dir / "sockets" / f"{session_id}.sock")

    def register_peer(self, project: str, entry: RegistryEntry) -> RegistryEntry:
        """Register or update an agent peer in the project directory."""
        agents_dir = self._get_project_agents_dir(project)
        file_path = agents_dir / f"{entry.name}.json"

        # Update heartbeat if not explicitly pre-configured
        if entry.heartbeat_at <= 0.0:
            entry.heartbeat_at = time.time()
        if not entry.status:
            entry.status = PeerStatus.ONLINE

        data = entry.to_dict()
        tmp_file = file_path.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp_file.replace(file_path)

        return entry

    def unregister_peer(self, project: str, name: str) -> bool:
        """Unregister an agent peer and clean up its metadata file and socket."""
        agents_dir = self._get_project_agents_dir(project)
        file_path = agents_dir / f"{name}.json"
        removed = False

        if file_path.exists():
            try:
                # Read endpoint to cleanup socket file
                with open(file_path, encoding="utf-8") as f:
                    data = json.load(f)
                    endpoint = str(data.get("endpoint", ""))
                    if endpoint and sys.platform != "win32" and os.path.exists(endpoint):
                        os.unlink(endpoint)
            except Exception:
                pass

            file_path.unlink(missing_ok=True)
            removed = True

        return removed

    def touch_heartbeat(
        self,
        project: str,
        name: str,
        context_used_pct: float = 0.0,
        queue_depth: int = 0,
    ) -> bool:
        """Update timestamp and load metrics for an active peer."""
        entry = self.get_peer(project, name)
        if not entry:
            return False

        entry.heartbeat_at = time.time()
        entry.context_used_pct = context_used_pct
        entry.queue_depth = queue_depth
        entry.status = PeerStatus.ONLINE

        self.register_peer(project, entry)
        return True

    def get_peer(self, project: str, name: str) -> RegistryEntry | None:
        """Fetch registration details of a single peer by name."""
        agents_dir = self._get_project_agents_dir(project)
        file_path = agents_dir / f"{name}.json"
        if not file_path.exists():
            return None

        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
            return RegistryEntry.from_dict(data)
        except Exception:
            return None

    def list_peers(self, project: str, auto_mark_stale: bool = True) -> list[RegistryEntry]:
        """List all peers in a project, optionally detecting stale/offline states."""
        agents_dir = self._get_project_agents_dir(project)
        now = time.time()
        peers: list[RegistryEntry] = []

        for p in sorted(agents_dir.glob("*.json")):
            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
                entry = RegistryEntry.from_dict(data)

                if auto_mark_stale:
                    elapsed = now - entry.heartbeat_at
                    if elapsed > self.offline_threshold_seconds:
                        entry.status = PeerStatus.OFFLINE
                    elif elapsed > self.stale_threshold_seconds:
                        entry.status = PeerStatus.STALE

                peers.append(entry)
            except Exception:
                continue

        return peers

    def cleanup_stale_peers(self, project: str, max_age_seconds: float = 300.0) -> int:
        """Remove metadata files of offline peers inactive for more than max_age_seconds."""
        agents_dir = self._get_project_agents_dir(project)
        now = time.time()
        cleaned_count = 0

        for p in agents_dir.glob("*.json"):
            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
                entry = RegistryEntry.from_dict(data)
                if (now - entry.heartbeat_at) > max_age_seconds:
                    self.unregister_peer(project, entry.name)
                    cleaned_count += 1
            except Exception:
                continue

        return cleaned_count
