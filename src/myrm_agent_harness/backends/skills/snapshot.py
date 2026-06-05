"""SQLite-based Skill Snapshot Cache.

Provides O(1) loading of SkillMetadata from a local SQLite database,
avoiding expensive file system I/O and parsing of hundreds of SKILL.md files
during application cold start.

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- sqlite3 (POS: SQLite 数据库库)
- types::SkillMetadata, SkillTrust (POS: 技能元数据类型和信任枚举)
- _runtime::build_skill_metadata (POS: 组装元数据)
- _utils::parse_skill_frontmatter (POS: 提取元数据字典)

[OUTPUT]
- SQLiteSkillSnapshot: 管理技能快照的 SQLite 封装类
- load_snapshot_skills(): 一键从快照中恢复可用技能

[POS]
Skill backend snapshot cache. Serves as an intermediate layer to accelerate full skill discovery.

"""

import logging
import sqlite3
from pathlib import Path

from myrm_agent_harness.backends.skills._runtime import build_skill_metadata
from myrm_agent_harness.backends.skills._utils import (
    SkillMetadataError,
    parse_skill_frontmatter,
)
from myrm_agent_harness.backends.skills.types import SkillMetadata, SkillTrust

logger = logging.getLogger(__name__)


class SQLiteSkillSnapshot:
    """SQLite based cache for fast loading of SkillMetadata.

    Stores the raw SKILL.md content and its storage path.
    At startup, reads from a single SQLite DB file instead of walking the entire
    file system and stat'ing hundreds of directories.
    """

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path).resolve()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        """Open a hardened connection (WAL + busy_timeout + torn-write check)."""
        from myrm_agent_harness.utils.db.sqlite import CACHE, harden_connection_sync

        conn = sqlite3.connect(self.db_path, timeout=10.0)
        harden_connection_sync(conn, CACHE, db_path=self.db_path)
        return conn

    def _init_db(self) -> None:
        """Initialize the SQLite database schema."""
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS skill_snapshots (
                        skill_name TEXT PRIMARY KEY,
                        storage_path TEXT NOT NULL,
                        content TEXT NOT NULL,
                        trust INTEGER NOT NULL,
                        file_mtime REAL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                conn.commit()
        except (sqlite3.Error, OSError) as e:
            logger.warning(f"Failed to initialize snapshot DB at {self.db_path}: {e}")

    def read_all(self, workspace_root: Path | None = None) -> list[SkillMetadata]:
        """Read all skills from the snapshot.

        Reads content directly from SQLite, bypassing file system I/O.
        Validates content using parse_skill_frontmatter and build_skill_metadata.
        """
        skills: list[SkillMetadata] = []
        if not self.db_path.exists():
            return skills

        try:
            with self._connect() as conn:
                cursor = conn.execute("SELECT skill_name, storage_path, content, trust FROM skill_snapshots")
                rows = cursor.fetchall()
                cursor.close()

                for skill_name, storage_path, content, trust_val in rows:
                    try:
                        trust = SkillTrust(trust_val)
                        frontmatter = parse_skill_frontmatter(content, skill_name)

                        meta = build_skill_metadata(
                            skill_name=skill_name,
                            frontmatter=frontmatter,
                            storage_path=storage_path,
                            content=content,
                            trust=trust,
                            workspace_root=workspace_root,
                        )
                        skills.append(meta)
                    except (SkillMetadataError, ValueError) as e:
                        logger.debug(f"Snapshot skill '{skill_name}' invalid: {e}")
                    except Exception as e:
                        logger.warning(f"Failed to reconstruct snapshot skill '{skill_name}': {e}")

        except sqlite3.Error as e:
            logger.warning(f"Failed to read from snapshot DB at {self.db_path}: {e}")

        return skills

    def update_snapshot(self, skills: list[SkillMetadata]) -> None:
        """Update the snapshot database with new/updated skills."""
        if not skills:
            return

        try:
            with self._connect() as conn:
                for meta in skills:
                    # Only snapshot storage skills (file-based)
                    if not meta.is_storage_skill or not meta.storage_path:
                        continue

                    # Extract content
                    skill_md = Path(meta.storage_path) / "SKILL.md"
                    if not skill_md.exists():
                        continue

                    try:
                        content = skill_md.read_text(encoding="utf-8")
                        mtime = skill_md.stat().st_mtime
                        conn.execute(
                            """
                            INSERT INTO skill_snapshots (skill_name, storage_path, content, trust, file_mtime, updated_at)
                            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                            ON CONFLICT(skill_name) DO UPDATE SET
                                storage_path=excluded.storage_path,
                                content=excluded.content,
                                trust=excluded.trust,
                                file_mtime=excluded.file_mtime,
                                updated_at=CURRENT_TIMESTAMP
                            """,
                            (
                                meta.name,
                                meta.storage_path,
                                content,
                                meta.trust.value,
                                mtime,
                            ),
                        )
                    except (OSError, UnicodeDecodeError) as e:
                        logger.warning(f"Failed to read SKILL.md for snapshotting '{meta.name}': {e}")

                conn.commit()
                logger.info(f"Updated {len(skills)} skills in snapshot {self.db_path.name}")
        except sqlite3.Error as e:
            logger.warning(f"Failed to write to snapshot DB at {self.db_path}: {e}")

    def upsert_from_path(self, skill_md_path: Path | str, workspace_root: Path | None = None) -> bool:
        """Parse a single SKILL.md file and update the snapshot.

        Returns True if successfully upserted, False otherwise.
        """
        skill_md = Path(skill_md_path).resolve()
        if not skill_md.exists() or skill_md.name != "SKILL.md":
            return False

        skill_dir = skill_md.parent
        skill_name = skill_dir.name

        try:
            content = skill_md.read_text(encoding="utf-8")
            mtime = skill_md.stat().st_mtime

            # Validate before inserting
            frontmatter = parse_skill_frontmatter(content, skill_name)
            meta = build_skill_metadata(
                skill_name=skill_name,
                frontmatter=frontmatter,
                storage_path=str(skill_dir),
                content=content,
                trust=SkillTrust.INSTALLED,  # Default trust for local files
                workspace_root=workspace_root,
            )

            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO skill_snapshots (skill_name, storage_path, content, trust, file_mtime, updated_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(skill_name) DO UPDATE SET
                        storage_path=excluded.storage_path,
                        content=excluded.content,
                        trust=excluded.trust,
                        file_mtime=excluded.file_mtime,
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    (meta.name, meta.storage_path, content, meta.trust.value, mtime),
                )
                conn.commit()
            logger.info(f" Snapshot hot-reloaded skill: {skill_name}")
            return True
        except Exception as e:
            logger.warning(f"Failed to upsert skill snapshot for {skill_md}: {e}")
            return False

    def delete_from_path(self, skill_md_path: Path | str) -> bool:
        """Remove a skill from the snapshot based on its file path."""
        skill_md = Path(skill_md_path).resolve()
        skill_name = skill_md.parent.name

        try:
            with self._connect() as conn:
                cursor = conn.execute("DELETE FROM skill_snapshots WHERE skill_name = ?", (skill_name,))
                deleted = cursor.rowcount > 0
                conn.commit()
            if deleted:
                logger.info(f" Snapshot removed skill: {skill_name}")
            return deleted
        except sqlite3.Error as e:
            logger.warning(f"Failed to delete skill '{skill_name}' from snapshot DB: {e}")
            return False

    def sync_all(self, workspace_root: Path | str, max_depth: int = 3) -> None:
        """Fast incremental sync of the snapshot with the file system.

        Uses os.stat to check mtime instead of parsing all files.
        """
        root = Path(workspace_root).resolve()
        if not root.is_dir():
            return

        # 1. Get current DB state
        db_state = {}
        try:
            with self._connect() as conn:
                cursor = conn.execute("SELECT skill_name, storage_path, file_mtime FROM skill_snapshots")
                rows = cursor.fetchall()
                cursor.close()
                for name, path, mtime in rows:
                    db_state[name] = {"path": path, "mtime": mtime}
        except sqlite3.Error as e:
            logger.warning(f"Failed to read snapshot DB for sync: {e}")
            return

        # 2. Walk file system to find SKILL.md files
        disk_files = {}

        def _walk(directory: Path, depth: int) -> None:
            if depth > max_depth:
                return
            try:
                for item in directory.iterdir():
                    if item.name.startswith("."):
                        continue
                    if item.is_file() and item.name == "SKILL.md":
                        skill_name = item.parent.name
                        disk_files[skill_name] = item
                    elif item.is_dir():
                        _walk(item, depth + 1)
            except PermissionError:
                pass

        _walk(root, 0)

        # 3. Compare and update
        to_update = []
        to_delete = []

        for skill_name, skill_md in disk_files.items():
            try:
                mtime = skill_md.stat().st_mtime
                db_record = db_state.get(skill_name)

                # If not in DB, or mtime is newer, or path changed
                if (
                    not db_record
                    or db_record["mtime"] is None
                    or mtime > db_record["mtime"]
                    or db_record["path"] != str(skill_md.parent)
                ):
                    to_update.append(skill_md)
            except OSError:
                continue

        for skill_name in db_state:
            if skill_name not in disk_files:
                to_delete.append(skill_name)

        # 4. Apply changes
        updated_count = 0
        for skill_md in to_update:
            if self.upsert_from_path(skill_md, workspace_root=root):
                updated_count += 1

        deleted_count = 0
        if to_delete:
            try:
                with self._connect() as conn:
                    conn.executemany(
                        "DELETE FROM skill_snapshots WHERE skill_name = ?",
                        [(n,) for n in to_delete],
                    )
                    deleted_count = conn.total_changes
                    conn.commit()
            except sqlite3.Error as e:
                logger.warning(f"Failed to delete obsolete skills during sync: {e}")

        if updated_count > 0 or deleted_count > 0:
            logger.info(f" Snapshot sync complete: {updated_count} updated, {deleted_count} deleted.")

    def delete_skill(self, skill_name: str) -> None:
        """Remove a skill from the snapshot."""
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM skill_snapshots WHERE skill_name = ?", (skill_name,))
                conn.commit()
        except sqlite3.Error as e:
            logger.warning(f"Failed to delete skill '{skill_name}' from snapshot DB: {e}")

    def clear(self) -> None:
        """Clear all snapshot data."""
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM skill_snapshots")
                conn.commit()
        except sqlite3.Error as e:
            logger.warning(f"Failed to clear snapshot DB: {e}")


def rebuild_workspace_snapshot(workspace_root: str | Path, max_depth: int = 3) -> None:
    """Rebuild the skills snapshot for a given workspace directory."""
    root = Path(workspace_root).resolve()
    if not root.is_dir():
        return

    snapshot_path = root / ".skills_snapshot.sqlite"
    snapshot = SQLiteSkillSnapshot(snapshot_path)
    snapshot.sync_all(workspace_root=root, max_depth=max_depth)
    logger.info(f"Rebuilt workspace skills snapshot at {snapshot_path}")


async def rebuild_local_dir_snapshot(skills_dir: str | Path) -> None:
    """Rebuild the skills snapshot for a specific local directory."""
    target_dir = Path(skills_dir).resolve()
    if not target_dir.is_dir():
        return

    snapshot_path = target_dir / ".skills_snapshot.sqlite"
    snapshot = SQLiteSkillSnapshot(snapshot_path)
    snapshot.sync_all(workspace_root=target_dir, max_depth=1)
    logger.info(f"Rebuilt local skills snapshot at {snapshot_path}")
