"""Ownership rules of the storage ledger.

[INPUT]
- Path | str (POS: root data directory)
- Mapping[StorageCategory, Iterable[Path | str]] (POS: the paths each category owns, wherever they live)

[OUTPUT]
- StorageLayout: resolved paths per category and the set of every owned path
- resolve_layout(): validate and resolve a declared layout

[POS]
Decides, without measuring anything, which category owns which part of the disk:
- a file belongs to the category with the deepest declared path at or above it, so a nested declaration carves its
  subtree out of the enclosing one;
- a declared path that is not a directory is a database file, and the `-wal`, `-shm` and `-journal` files SQLite
  keeps beside it belong to it too;
- what is left of the data directory is `OTHER`; declared paths may live outside the data directory (a relocated
  volume) and are then measured where they are.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .types import StorageCategory

logger = logging.getLogger(__name__)

# Files SQLite keeps beside a database; they live and die with it.
SQLITE_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")


@dataclass(frozen=True, slots=True)
class StorageLayout:
    """The resolved paths each category owns, in report order, and every owned path in `normcase` form."""

    data_dir: Path
    claims: Mapping[StorageCategory, tuple[Path, ...]]
    owned: frozenset[str]


def resolve_layout(data_dir: Path | str, declared: Mapping[StorageCategory, Iterable[Path | str]]) -> StorageLayout:
    """Resolve the declared paths (following links at the declared roots) and settle who owns what.

    A path declared for two categories goes to the first one in `StorageCategory` order and the clash is logged:
    a misconfigured location must not take the whole report down.
    """
    if StorageCategory.OTHER in declared:
        raise ValueError("StorageCategory.OTHER is the remainder of the data directory and cannot be declared")

    root = Path(data_dir).resolve()
    owners: dict[str, tuple[StorageCategory, Path]] = {}
    for category in StorageCategory:
        for raw in declared.get(category, ()):
            _claim(owners, category, Path(raw).resolve())
    for category, path in list(owners.values()):
        if not path.is_dir():
            for suffix in SQLITE_SIDECAR_SUFFIXES:
                sidecar = Path(f"{path}{suffix}")
                owners.setdefault(os.path.normcase(sidecar), (category, sidecar))

    root_key = os.path.normcase(root)
    claims: dict[StorageCategory, list[Path]] = {category: [] for category in StorageCategory if category in declared}
    for category, path in owners.values():
        claims[category].append(path)
    # A category that owns the whole data directory leaves nothing for `OTHER`.
    claims[StorageCategory.OTHER] = [] if root_key in owners else [root]
    return StorageLayout(
        data_dir=root,
        claims={category: tuple(paths) for category, paths in claims.items()},
        owned=frozenset(owners) | {root_key},
    )


def _claim(owners: dict[str, tuple[StorageCategory, Path]], category: StorageCategory, path: Path) -> None:
    owner = owners.setdefault(os.path.normcase(path), (category, path))
    if owner[0] is not category:
        logger.warning(
            "Storage path %s is declared for both %s and %s; it is attributed to %s",
            path,
            owner[0].value,
            category.value,
            owner[0].value,
        )
