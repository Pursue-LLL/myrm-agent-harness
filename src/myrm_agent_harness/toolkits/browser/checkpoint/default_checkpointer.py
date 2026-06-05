"""Default checkpoint implementation for development and testing.


[INPUT]
- langgraph.checkpoint.sqlite.aio::AsyncSqliteSaver (POS: LangGraph SQLite checkpointer)
- langgraph.checkpoint.serde.base::SerializerProtocol (POS: serializer protocol)
- aiosqlite (POS: async SQLite library)

[OUTPUT]
- create_default_checkpointer: create default SQLite checkpointer
- create_memory_checkpointer: create in-memory checkpointer (for testing)

[POS]
Default checkpointer implementation. Provides an out-of-the-box SQLite checkpointer for development and testing.
Production environments should use a PostgreSQL checkpointer injected by the business layer.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver

logger = logging.getLogger(__name__)


async def create_default_checkpointer(
    db_path: str | Path = ":memory:",
) -> BaseCheckpointSaver:
    """Create default SQLite checkpointer for development and testing.

    Uses LangGraph's AsyncSqliteSaver with default serializer.
    For production deployments, use business layer injected PostgreSQL checkpointer.

    Args:
        db_path: Database file path, defaults to ":memory:" for in-memory storage
                For persistence, use path like "./checkpoints.db" or "/tmp/checkpoints.db"

    Returns:
        BaseCheckpointSaver: Configured SQLite checkpointer

    Example:
        >>> # In-memory (default, for testing)
        >>> checkpointer = await create_default_checkpointer()

        >>> # File-based persistence (for development)
        >>> checkpointer = await create_default_checkpointer("./checkpoints.db")

        >>> # Use with IncrementalSessionCheckpointer
        >>> from myrm_agent_harness.toolkits.browser.checkpoint import IncrementalSessionCheckpointer
        >>> incremental_checkpointer = IncrementalSessionCheckpointer(
        ...     base_checkpointer=checkpointer,
        ...     session_vault=session_vault
        ... )

    Note:
        - This is a convenience function for development/testing
        - Production deployments should use business layer PostgreSQL checkpointer
        - In-memory checkpointer loses state on process restart
        - File-based checkpointer persists state but is single-machine only
    """
    try:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    except ImportError as e:
        raise ImportError(
            "LangGraph SQLite checkpoint dependencies not found. Install with: pip install langgraph-checkpoint-sqlite"
        ) from e

    try:
        import aiosqlite
    except ImportError as e:
        raise ImportError("aiosqlite not found. Install with: pip install aiosqlite") from e

    # Resolve path
    if db_path != ":memory:":
        db_path = Path(db_path).resolve()
        # Ensure parent directory exists
        if isinstance(db_path, Path) and db_path.parent != Path("."):
            db_path.parent.mkdir(parents=True, exist_ok=True)

    # Create connection
    conn = await aiosqlite.connect(str(db_path))
    from myrm_agent_harness.utils.db.sqlite import DEFAULT, harden_connection_async

    await harden_connection_async(conn, DEFAULT, db_path=Path(db_path) if db_path != ":memory:" else None)

    # Create checkpointer (uses default PickleSerde)
    checkpointer = AsyncSqliteSaver(conn)

    # Setup tables
    await checkpointer.setup()

    if db_path == ":memory:":
        logger.info("Created in-memory SQLite checkpointer (state will be lost on restart)")
    else:
        logger.info(f"Created file-based SQLite checkpointer: {db_path}")

    return checkpointer


async def create_memory_checkpointer() -> BaseCheckpointSaver:
    """Create in-memory checkpointer for testing.

    Convenience alias for create_default_checkpointer(":memory:").

    Returns:
        BaseCheckpointSaver: In-memory SQLite checkpointer

    Example:
        >>> checkpointer = await create_memory_checkpointer()
        >>> # Use in tests or development
    """
    return await create_default_checkpointer(":memory:")
