"""[POS]: src/myrm_agent_harness/toolkits/memory/cvfs/store.py
[INPUT]: Normalized VFS nodes, content strings, and canonical query URIs.
[OUTPUT]: CVFSRegistryStore managing SQLite persistence for virtual file system hierarchy.
"""

import contextlib
import json
import sqlite3
import time
from pathlib import Path

from .models import VFSNodeInfo, VFSNodeType, VFSSubtreeStats


class CVFSRegistryStore:
    """SQLite-backed metadata and content registry for Context Virtual File System."""

    def __init__(self, db_path: Path | str = ":memory:") -> None:
        self.db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            if self.db_path != ":memory:":
                Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            if self.db_path != ":memory:":
                self._conn.execute("PRAGMA journal_mode = WAL;")
            self._conn.execute("PRAGMA busy_timeout = 5000;")
            self._init_schema(self._conn)
        return self._conn

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS myrm_cvfs_nodes (
                uri TEXT PRIMARY KEY,
                parent_uri TEXT NOT NULL,
                name TEXT NOT NULL,
                node_type TEXT NOT NULL,
                content TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at_epoch REAL NOT NULL,
                updated_at_epoch REAL NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_cvfs_parent
            ON myrm_cvfs_nodes(parent_uri);
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_cvfs_parent_name
            ON myrm_cvfs_nodes(parent_uri, name);
            """
        )
        conn.commit()

    def put_node(self, node: VFSNodeInfo, content: str = "") -> None:
        """Insert or update a virtual file system node and its text content."""
        conn = self._get_connection()
        meta_json = json.dumps(node.metadata)
        size_bytes = len(content.encode()) if node.node_type == VFSNodeType.FILE else 0
        now = time.time()

        conn.execute(
            """
            INSERT OR REPLACE INTO myrm_cvfs_nodes
            (uri, parent_uri, name, node_type, content, size_bytes, metadata_json, created_at_epoch, updated_at_epoch)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                node.uri,
                node.parent_uri,
                node.name,
                node.node_type.value,
                content,
                size_bytes,
                meta_json,
                node.created_at_epoch,
                now,
            ),
        )
        conn.commit()

    def get_node(self, uri: str) -> tuple[VFSNodeInfo, str] | None:
        """Fetch node metadata descriptor and raw text content by URI."""
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT uri, parent_uri, name, node_type, content, size_bytes,
                   metadata_json, created_at_epoch, updated_at_epoch
            FROM myrm_cvfs_nodes
            WHERE uri = ?;
            """,
            (uri,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        metadata = json.loads(str(row["metadata_json"]))
        node = VFSNodeInfo(
            uri=str(row["uri"]),
            parent_uri=str(row["parent_uri"]),
            name=str(row["name"]),
            node_type=VFSNodeType(row["node_type"]),
            size_bytes=int(row["size_bytes"]),
            metadata=metadata if isinstance(metadata, dict) else {},
            created_at_epoch=float(row["created_at_epoch"]),
            updated_at_epoch=float(row["updated_at_epoch"]),
        )
        return node, str(row["content"])

    def list_children(self, parent_uri: str) -> list[VFSNodeInfo]:
        """List direct child nodes under specified parent directory URI."""
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT uri, parent_uri, name, node_type, size_bytes,
                   metadata_json, created_at_epoch, updated_at_epoch
            FROM myrm_cvfs_nodes
            WHERE parent_uri = ?
            ORDER BY node_type ASC, name ASC;
            """,
            (parent_uri,),
        )
        rows = cursor.fetchall()
        result: list[VFSNodeInfo] = []
        for r in rows:
            meta = json.loads(str(r["metadata_json"]))
            result.append(
                VFSNodeInfo(
                    uri=str(r["uri"]),
                    parent_uri=str(r["parent_uri"]),
                    name=str(r["name"]),
                    node_type=VFSNodeType(r["node_type"]),
                    size_bytes=int(r["size_bytes"]),
                    metadata=meta if isinstance(meta, dict) else {},
                    created_at_epoch=float(r["created_at_epoch"]),
                    updated_at_epoch=float(r["updated_at_epoch"]),
                )
            )
        return result

    def delete_node(self, uri: str) -> bool:
        """Delete node and all its nested sub-nodes recursively."""
        conn = self._get_connection()
        # Delete exact node and any descendants whose URI starts with uri + "/"
        prefix_pattern = f"{uri}/%"
        cursor = conn.execute(
            "DELETE FROM myrm_cvfs_nodes WHERE uri = ? OR uri LIKE ?;",
            (uri, prefix_pattern),
        )
        conn.commit()
        return cursor.rowcount > 0

    def find_nodes(
        self,
        keyword: str,
        prefix_uri: str = "ctx://",
        node_type: VFSNodeType | None = None,
    ) -> list[VFSNodeInfo]:
        """Search nodes matching keyword in name or content within prefix URI, optionally filtered by node type."""
        conn = self._get_connection()
        like_keyword = f"%{keyword}%"
        prefix_pattern = f"{prefix_uri}%"

        query = """
            SELECT uri, parent_uri, name, node_type, size_bytes,
                   metadata_json, created_at_epoch, updated_at_epoch
            FROM myrm_cvfs_nodes
            WHERE (uri LIKE ? OR uri = ?)
              AND (uri LIKE ? OR name LIKE ? OR content LIKE ?)
        """
        params: list[str] = [prefix_pattern, prefix_uri, like_keyword, like_keyword, like_keyword]
        if node_type is not None:
            query += " AND node_type = ?"
            params.append(node_type.value)

        query += " ORDER BY uri ASC LIMIT 100;"
        cursor = conn.execute(query, tuple(params))
        rows = cursor.fetchall()
        result: list[VFSNodeInfo] = []
        for r in rows:
            meta = json.loads(str(r["metadata_json"]))
            result.append(
                VFSNodeInfo(
                    uri=str(r["uri"]),
                    parent_uri=str(r["parent_uri"]),
                    name=str(r["name"]),
                    node_type=VFSNodeType(r["node_type"]),
                    size_bytes=int(r["size_bytes"]),
                    metadata=meta if isinstance(meta, dict) else {},
                    created_at_epoch=float(r["created_at_epoch"]),
                    updated_at_epoch=float(r["updated_at_epoch"]),
                )
            )
        return result

    def get_subtree_stats(self, prefix_uri: str) -> VFSSubtreeStats:
        """Calculate aggregated node counts and storage byte size for a given URI prefix."""
        conn = self._get_connection()
        prefix_pattern = f"{prefix_uri}/%"
        cursor = conn.execute(
            """
            SELECT
                COUNT(*) as total_nodes,
                SUM(CASE WHEN node_type = 'file' THEN 1 ELSE 0 END) as file_count,
                SUM(CASE WHEN node_type = 'directory' THEN 1 ELSE 0 END) as dir_count,
                SUM(size_bytes) as total_bytes
            FROM myrm_cvfs_nodes
            WHERE uri = ? OR uri LIKE ?;
            """,
            (prefix_uri, prefix_pattern),
        )
        row = cursor.fetchone()
        if not row:
            return VFSSubtreeStats(root_uri=prefix_uri)

        total_nodes = int(row["total_nodes"] or 0)
        file_count = int(row["file_count"] or 0)
        dir_count = int(row["dir_count"] or 0)
        total_bytes = int(row["total_bytes"] or 0)

        return VFSSubtreeStats(
            root_uri=prefix_uri,
            total_nodes=total_nodes,
            file_count=file_count,
            directory_count=dir_count,
            total_bytes=total_bytes,
        )

    def close(self) -> None:
        """Close SQLite database connection if open."""
        if self._conn is not None:
            with contextlib.suppress(sqlite3.DatabaseError):
                self._conn.close()
            self._conn = None

