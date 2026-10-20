"""Persistent disk cache for MCP server tool schemas.

Architecture:
- Persists discovered MCP tool schemas and estimated token counts to disk keyed by config_hash
- Gives routing a recorded schema/token baseline per server config for diagnostics and offline inspection
- Atomic disk writes via tempfile + os.replace to prevent concurrency corruption
- Zero Any types, fully typed data structures, robust JSON serialization

[INPUT]
- langchain_core.tools::BaseTool (POS: LangChain BaseTool representation)
- collections.abc::Sequence (POS: Python standard sequence protocol)
- dataclasses::dataclass, asdict (POS: Python dataclasses serialization)

[OUTPUT]
- CachedServerSchema: dataclass representing serializable tool schema metadata
- CachedToolMeta: dataclass representing serializable metadata for a single cached tool
- clear_schema_cache(): wipe all or single server schema cache files
- get_schema_cache_dir(): resolver for the schema cache directory path
- load_cached_schema(): load and validate non-expired cached schema from disk
- save_cached_schema(): serialize and atomically write tool schemas to disk

[POS]
MCP schema persistent cache layer. Caches discovered schemas and estimated token counts
to disk with atomic writes and TTL expiration. Callers read it for diagnostics; the routing
path currently logs a cache hit but still skips an unreachable server.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from myrm_agent_harness.utils.token_estimation import (
    estimate_tool_schema_tokens,
    tool_input_schema,
)

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_DIR_NAME = ".cache/myrm/mcp_schemas"


def get_schema_cache_dir() -> Path:
    """Return the absolute path to the MCP schema cache directory."""
    custom_dir = os.environ.get("MYRM_MCP_CACHE_DIR")
    if custom_dir:
        path = Path(custom_dir)
    else:
        path = Path.home() / _DEFAULT_CACHE_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass(frozen=True, slots=True)
class CachedToolMeta:
    """Serializable metadata for a single cached MCP tool."""

    name: str
    description: str
    parameters: dict[str, object]
    schema_tokens: int


@dataclass(frozen=True, slots=True)
class CachedServerSchema:
    """Serializable cached schema payload for an entire MCP server."""

    server_name: str
    config_hash: str
    tools: tuple[CachedToolMeta, ...]
    total_schema_tokens: int
    cached_at: float

    def to_dict(self) -> dict[str, object]:
        return {
            "server_name": self.server_name,
            "config_hash": self.config_hash,
            "total_schema_tokens": self.total_schema_tokens,
            "cached_at": self.cached_at,
            "tools": [asdict(t) for t in self.tools],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> CachedServerSchema:
        tools_raw = cast("list[dict[str, object]]", data.get("tools", []))
        tools = tuple(
            CachedToolMeta(
                name=str(t["name"]),
                description=str(t.get("description", "")),
                parameters=cast("dict[str, object]", t.get("parameters", {})),
                schema_tokens=int(t.get("schema_tokens", 0)),
            )
            for t in tools_raw
        )
        return cls(
            server_name=str(data["server_name"]),
            config_hash=str(data["config_hash"]),
            tools=tools,
            total_schema_tokens=int(data.get("total_schema_tokens", 0)),
            cached_at=float(data.get("cached_at", 0.0)),
        )


def _cache_file_path(config_hash: str) -> Path:
    return get_schema_cache_dir() / f"{config_hash}.json"


def load_cached_schema(
    config_hash: str,
    max_age_seconds: float = 86400.0,
    force_refresh: bool = False,
) -> CachedServerSchema | None:
    """Load cached server schema from disk if available, valid, and not expired.

    Args:
        config_hash: SHA256 hash of the server configuration.
        max_age_seconds: Cache TTL in seconds (default: 86400.0 = 24 hours).
            If <= 0, expiration check is bypassed.
        force_refresh: If True, bypass cache completely and return None.
    """
    if force_refresh:
        return None
    path = _cache_file_path(config_hash)
    if not path.is_file():
        return None
    try:
        content = path.read_text(encoding="utf-8")
        data = cast("dict[str, object]", json.loads(content))
        if data.get("config_hash") != config_hash:
            return None
        schema = CachedServerSchema.from_dict(data)
        if max_age_seconds > 0 and (time.time() - schema.cached_at) > max_age_seconds:
            logger.debug(
                "Schema cache expired for %s (age=%.1fs > ttl=%.1fs)",
                config_hash[:16],
                time.time() - schema.cached_at,
                max_age_seconds,
            )
            return None
        return schema
    except Exception as exc:
        logger.debug("Failed to read schema cache for %s: %s", config_hash[:16], exc)
        return None


def save_cached_schema(
    config_hash: str,
    server_name: str,
    tools: Sequence[BaseTool],
) -> CachedServerSchema | None:
    """Serialize and atomically save tool schemas to disk."""
    try:
        cached_tools: list[CachedToolMeta] = []
        total_tokens = 0
        for tool in tools:
            tokens = estimate_tool_schema_tokens(tool)
            total_tokens += tokens
            cached_tools.append(
                CachedToolMeta(
                    name=tool.name,
                    description=tool.description or "",
                    parameters=tool_input_schema(tool),
                    schema_tokens=tokens,
                )
            )

        schema = CachedServerSchema(
            server_name=server_name,
            config_hash=config_hash,
            tools=tuple(cached_tools),
            total_schema_tokens=total_tokens,
            cached_at=time.time(),
        )

        cache_dir = get_schema_cache_dir()
        target_path = _cache_file_path(config_hash)

        # Atomic file write via tempfile in the same directory + os.replace
        with tempfile.NamedTemporaryFile("w", dir=cache_dir, delete=False, encoding="utf-8") as tf:
            json.dump(schema.to_dict(), tf, ensure_ascii=False, indent=2)
            temp_name = tf.name

        os.replace(temp_name, target_path)
        logger.info(
            "Persisted MCP schema cache for '%s' (%s, %d tools, ~%d tokens)",
            server_name,
            config_hash[:16],
            len(cached_tools),
            total_tokens,
        )
        return schema
    except Exception as exc:
        logger.warning(
            "Failed to save MCP schema cache for %s (%s): %s",
            server_name,
            config_hash[:16],
            exc,
        )
        return None


def clear_schema_cache() -> int:
    """Clear all cached MCP schemas from disk."""
    cache_dir = get_schema_cache_dir()
    count = 0
    for file in cache_dir.glob("*.json"):
        try:
            file.unlink()
            count += 1
        except OSError:
            pass
    return count


__all__ = [
    "CachedServerSchema",
    "CachedToolMeta",
    "clear_schema_cache",
    "get_schema_cache_dir",
    "load_cached_schema",
    "save_cached_schema",
]
