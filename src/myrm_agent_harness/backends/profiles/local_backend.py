"""Local Profile Backend Implementation.

Out-of-the-box persistent storage for agent profiles using the local
file system. Stores configurations as YAML files and system prompts as
Markdown files within agent-specific bundle directories. Maintains a
local SQLite index for fast listing.

[INPUT]
- .types::AgentProfile (POS: Agent Profile 数据类型定义)
- .exceptions::ProfileNotFoundError, ProfileAlreadyExistsError (POS: Profile 后端异常类型)
- .protocol::AgentProfileBackend (POS: Agent Profile 存储后端协议)
- myrm_agent_harness.toolkits.memory.config (POS: Agent 记忆策略配置)

[OUTPUT]
- LocalProfileBackend: YAML + SQLite local persistent profile store.

[POS]
本地文件 Profile 后端。使用 YAML 文件 + SQLite 索引实现持久化 Agent 配置管理，
支持 MYRM_DATA_DIR 环境变量自定义存储路径。
"""

from __future__ import annotations

import importlib
import json
import os
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from myrm_agent_harness.backends.profiles.exceptions import ProfileAlreadyExistsError, ProfileNotFoundError
from myrm_agent_harness.backends.profiles.types import AgentProfile
from myrm_agent_harness.toolkits.memory.config import AgentMemoryPolicy, MemoryScopeLevel, MemoryWritePolicy

from .protocols import AgentProfileBackend


def _yaml_safe_load_file(path: str) -> dict[str, object]:
    yaml_mod = importlib.import_module("yaml")
    with open(path, encoding="utf-8") as f:
        raw = yaml_mod.safe_load(f)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): val for k, val in raw.items()}


def _yaml_dump_file(data: dict[str, object], path: str) -> None:
    yaml_mod = importlib.import_module("yaml")
    with open(path, "w", encoding="utf-8") as f:
        yaml_mod.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


def _bundle_optional_str(data: dict[str, object], key: str) -> str | None:
    v = data.get(key)
    if v is None:
        return None
    if isinstance(v, str):
        return v
    return str(v)


def _bundle_optional_int(data: dict[str, object], key: str) -> int | None:
    v = data.get(key)
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    if isinstance(v, str):
        try:
            return int(v, 10)
        except ValueError:
            return None
    return None


def _bundle_str_list(data: dict[str, object], key: str) -> list[str] | None:
    v = data.get(key)
    if v is None:
        return None
    if isinstance(v, list):
        return [str(x) for x in v]
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, list):
            return [str(x) for x in parsed]
    return None


def _bundle_metadata(data: dict[str, object], key: str) -> dict[str, object]:
    v = data.get(key)
    if isinstance(v, dict):
        return {str(k): val for k, val in v.items()}
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return {str(k): val for k, val in parsed.items()}
    return {}


def _bundle_bool(data: dict[str, object], key: str, default: bool = False) -> bool:
    v = data.get(key, default)
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() in ("true", "1", "yes", "on")
    if isinstance(v, (int, float)):
        return bool(v)
    return default


def _bundle_iso_dt(data: dict[str, object], key: str) -> datetime | None:
    v = data.get(key)
    if isinstance(v, str):
        return datetime.fromisoformat(v)
    return None


def _serialize_memory_policy(policy: AgentMemoryPolicy | None) -> dict[str, object] | None:
    if policy is None:
        return None
    payload = asdict(policy)
    read_scopes = payload.get("read_scopes")
    if read_scopes is not None:
        payload["read_scopes"] = [scope.value for scope in read_scopes]
    payload["write_policy"] = policy.write_policy.value
    return payload


def _deserialize_memory_policy(raw: object) -> AgentMemoryPolicy | None:
    if not isinstance(raw, dict):
        return None

    read_scopes_raw = raw.get("read_scopes")
    read_scopes = None
    if isinstance(read_scopes_raw, (list, tuple)):
        read_scopes = tuple(
            scope if isinstance(scope, MemoryScopeLevel) else MemoryScopeLevel(str(scope))
            for scope in read_scopes_raw
            if isinstance(scope, (MemoryScopeLevel, str))
        )

    write_policy_raw = raw.get("write_policy")
    write_policy = (
        write_policy_raw
        if isinstance(write_policy_raw, MemoryWritePolicy)
        else MemoryWritePolicy(str(write_policy_raw))
        if isinstance(write_policy_raw, str)
        else MemoryWritePolicy.INHERIT
    )

    return AgentMemoryPolicy(
        agent_id=str(raw.get("agent_id")) if isinstance(raw.get("agent_id"), str) else None,
        channel_id=str(raw.get("channel_id")) if isinstance(raw.get("channel_id"), str) else None,
        conversation_id=str(raw.get("conversation_id")) if isinstance(raw.get("conversation_id"), str) else None,
        task_id=str(raw.get("task_id")) if isinstance(raw.get("task_id"), str) else None,
        read_scopes=read_scopes,
        write_policy=write_policy,
    )


class LocalProfileBackend(AgentProfileBackend):
    """Agent Bundle Manager (Framework default local storage).

    Storage Structure::

        ~/.myrm/agents/
            <agent_id>/
                config.yaml   # Configuration metadata
                prompt.md     # System prompt

    Index Storage: ``~/.myrm/agents_index.db``
    """

    def __init__(self, base_dir: str | None = None, db_path: str | None = None):
        """Initialize the Local Profile Backend.

        Args:
            base_dir: Root directory for agent bundles (defaults to ~/.myrm/agents).
            db_path: Path to the SQLite index file (defaults to ~/.myrm/agents_index.db).
        """
        myrm_dir = Path(os.getenv("MYRM_DATA_DIR", str(Path.home() / ".myrm")))

        if base_dir is None:
            base_dir = str(myrm_dir / "agents")
        if db_path is None:
            db_path = str(myrm_dir / "agents_index.db")

        self.base_dir = base_dir
        self.db_path = db_path

        os.makedirs(self.base_dir, exist_ok=True)
        self._init_db()
        self._sync_index()

    def _get_connection(self) -> sqlite3.Connection:
        from myrm_agent_harness.utils.db.sqlite import DEFAULT, harden_connection_sync

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        harden_connection_sync(conn, DEFAULT, db_path=Path(self.db_path))
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agents_index (
                    id TEXT PRIMARY KEY,
                    display_name TEXT,
                    description TEXT,
                    avatar TEXT,
                    model TEXT,
                    max_iterations INTEGER,
                    skills TEXT,
                    tools_allowed TEXT,
                    metadata TEXT,
                    built_in BOOLEAN NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

    def _sync_index(self) -> None:
        """Full sync from filesystem to SQLite index (executed on startup)."""
        profiles: list[AgentProfile] = []
        for entry in os.scandir(self.base_dir):
            if entry.is_dir():
                try:
                    profiles.append(self._read_bundle(entry.name))
                except Exception:
                    continue

        with self._get_connection() as conn:
            conn.execute("DELETE FROM agents_index")
            for profile in profiles:
                self._insert_index(conn, profile)
            conn.commit()

    def _insert_index(self, conn: sqlite3.Connection, profile: AgentProfile) -> None:
        conn.execute(
            """
            INSERT INTO agents_index (
                id, display_name, description, avatar, model,
                max_iterations, skills, tools_allowed, metadata, built_in,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile.id,
                profile.display_name,
                profile.description,
                profile.avatar,
                profile.model,
                profile.max_iterations,
                json.dumps(profile.skills) if profile.skills is not None else None,
                json.dumps(profile.tools_allowed) if profile.tools_allowed is not None else None,
                json.dumps(profile.metadata),
                1 if profile.built_in else 0,
                profile.created_at.isoformat() if profile.created_at else datetime.now().isoformat(),
                profile.updated_at.isoformat() if profile.updated_at else datetime.now().isoformat(),
            ),
        )

    def _update_index(self, conn: sqlite3.Connection, profile: AgentProfile) -> None:
        conn.execute(
            """
            UPDATE agents_index SET
                display_name = ?, description = ?, avatar = ?, model = ?,
                max_iterations = ?, skills = ?, tools_allowed = ?,
                metadata = ?, built_in = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                profile.display_name,
                profile.description,
                profile.avatar,
                profile.model,
                profile.max_iterations,
                json.dumps(profile.skills) if profile.skills is not None else None,
                json.dumps(profile.tools_allowed) if profile.tools_allowed is not None else None,
                json.dumps(profile.metadata),
                1 if profile.built_in else 0,
                profile.updated_at.isoformat() if profile.updated_at else datetime.now().isoformat(),
                profile.id,
            ),
        )

    def _delete_index(self, conn: sqlite3.Connection, profile_id: str) -> None:
        conn.execute("DELETE FROM agents_index WHERE id = ?", (profile_id,))

    def _get_bundle_dir(self, profile_id: str) -> str:
        return os.path.join(self.base_dir, profile_id)

    def _read_bundle(self, profile_id: str) -> AgentProfile:
        bundle_dir = self._get_bundle_dir(profile_id)
        config_path = os.path.join(bundle_dir, "config.yaml")
        prompt_path = os.path.join(bundle_dir, "prompt.md")

        if not os.path.exists(config_path):
            raise ProfileNotFoundError(profile_id)

        config_data = _yaml_safe_load_file(config_path)

        system_prompt = None
        if os.path.exists(prompt_path):
            with open(prompt_path, encoding="utf-8") as f:
                system_prompt = f.read()

        return AgentProfile(
            id=profile_id,
            display_name=_bundle_optional_str(config_data, "display_name"),
            description=_bundle_optional_str(config_data, "description"),
            avatar=_bundle_optional_str(config_data, "avatar"),
            model=_bundle_optional_str(config_data, "model"),
            max_iterations=_bundle_optional_int(config_data, "max_iterations"),
            skills=_bundle_str_list(config_data, "skills"),
            tools_allowed=_bundle_str_list(config_data, "tools_allowed"),
            system_prompt=system_prompt,
            memory_policy=_deserialize_memory_policy(config_data.get("memory_policy")),
            metadata=_bundle_metadata(config_data, "metadata"),
            built_in=_bundle_bool(config_data, "built_in", False),
            created_at=_bundle_iso_dt(config_data, "created_at"),
            updated_at=_bundle_iso_dt(config_data, "updated_at"),
        )

    def _write_bundle(self, profile: AgentProfile) -> None:
        bundle_dir = self._get_bundle_dir(profile.id)
        os.makedirs(bundle_dir, exist_ok=True)

        config_path = os.path.join(bundle_dir, "config.yaml")
        prompt_path = os.path.join(bundle_dir, "prompt.md")

        now = datetime.now().isoformat()

        config_data = {
            "display_name": profile.display_name,
            "description": profile.description,
            "avatar": profile.avatar,
            "model": profile.model,
            "max_iterations": profile.max_iterations,
            "skills": profile.skills,
            "tools_allowed": profile.tools_allowed,
            "memory_policy": _serialize_memory_policy(profile.memory_policy),
            "metadata": profile.metadata,
            "built_in": profile.built_in,
            "created_at": profile.created_at.isoformat() if profile.created_at else now,
            "updated_at": profile.updated_at.isoformat() if profile.updated_at else now,
        }

        filtered = {k: v for k, v in config_data.items() if v is not None}
        dump_payload: dict[str, object] = {str(k): val for k, val in filtered.items()}
        _yaml_dump_file(dump_payload, config_path)

        if profile.system_prompt is not None:
            with open(prompt_path, "w", encoding="utf-8") as f:
                f.write(profile.system_prompt)
        elif os.path.exists(prompt_path):
            os.remove(prompt_path)

    def list_profiles(self) -> list[AgentProfile]:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM agents_index ORDER BY created_at DESC")
            rows = cursor.fetchall()

            return [
                AgentProfile(
                    id=row["id"],
                    display_name=row["display_name"],
                    description=row["description"],
                    avatar=row["avatar"],
                    model=row["model"],
                    max_iterations=row["max_iterations"],
                    skills=json.loads(row["skills"]) if row["skills"] else None,
                    tools_allowed=json.loads(row["tools_allowed"]) if row["tools_allowed"] else None,
                    memory_policy=None,
                    metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                    built_in=bool(row["built_in"]),
                    created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
                    updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
                )
                for row in rows
            ]

    def get_profile(self, profile_id: str) -> AgentProfile | None:
        try:
            return self._read_bundle(profile_id)
        except ProfileNotFoundError:
            return None

    def create_profile(self, profile: AgentProfile) -> AgentProfile:
        bundle_dir = self._get_bundle_dir(profile.id)
        if os.path.exists(bundle_dir):
            raise ProfileAlreadyExistsError(profile.id)

        if not profile.created_at:
            profile.created_at = datetime.now()
        if not profile.updated_at:
            profile.updated_at = profile.created_at

        self._write_bundle(profile)

        with self._get_connection() as conn:
            self._insert_index(conn, profile)
            conn.commit()

        return profile

    def update_profile(self, profile: AgentProfile) -> AgentProfile:
        bundle_dir = self._get_bundle_dir(profile.id)
        if not os.path.exists(bundle_dir):
            raise ProfileNotFoundError(profile.id)

        profile.updated_at = datetime.now()
        self._write_bundle(profile)

        with self._get_connection() as conn:
            self._update_index(conn, profile)
            conn.commit()

        return profile

    def delete_profile(self, profile_id: str) -> bool:
        bundle_dir = self._get_bundle_dir(profile_id)
        if not os.path.exists(bundle_dir):
            return False

        import shutil

        try:
            shutil.rmtree(bundle_dir)
        except Exception:
            return False

        with self._get_connection() as conn:
            self._delete_index(conn, profile_id)
            conn.commit()

        return True
