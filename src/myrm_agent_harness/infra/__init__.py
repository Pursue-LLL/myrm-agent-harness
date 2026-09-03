"""Infrastructure layer.

Provides generic mechanisms for delivery, tracing, and incremental state tracking.
"""

from .sqlite_backup import BackupRecord, RestoreResult, SQLiteBackupManager
from .sqlite_salvage import (
    CorruptedRange,
    SalvageResult,
    SQLiteRowidSalvageEngine,
    TableSalvageStats,
)

__all__ = [
    "BackupRecord",
    "CorruptedRange",
    "RestoreResult",
    "SQLiteBackupManager",
    "SQLiteRowidSalvageEngine",
    "SalvageResult",
    "TableSalvageStats",
]

