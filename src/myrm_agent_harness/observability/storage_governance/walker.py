"""File tree measurement for storage attribution.

[INPUT]
- str (POS: root of the tree to measure; a regular file or a directory)
- frozenset[str] (POS: normalized paths owned by another category, left out of the measurement)

[OUTPUT]
- TreeSize: apparent bytes and regular-file count
- measure_tree(): the size of one tree

[POS]
Filesystem leaf of the storage inspector. It only adds up what is on disk; which category owns which path is
decided by `layout.py`.
"""

from __future__ import annotations

import os
import stat
from typing import NamedTuple


class TreeSize(NamedTuple):
    """Apparent size of the regular files below a root."""

    total_bytes: int
    file_count: int


_EMPTY = TreeSize(0, 0)


def measure_tree(root: str, skip: frozenset[str] = frozenset()) -> TreeSize:
    """Add up the regular files of `root`, which may itself be a single file.

    Symbolic links and junctions are neither followed nor counted, so a link can never pull another tree, or a
    loop, into the total. An entry whose `os.path.normcase`d path is in `skip` is left out together with
    everything below it: it belongs to another category. Whatever cannot be read (a directory without permission,
    a file removed during the walk) counts as empty.

    Sizes are apparent (`st_size`), not the blocks allocated on disk: every name of a hard-linked file counts in
    full and a sparse file counts its logical length.
    """
    try:
        root_stat = os.lstat(root)
    except OSError:
        return _EMPTY
    if stat.S_ISREG(root_stat.st_mode):
        return TreeSize(root_stat.st_size, 1)
    if not stat.S_ISDIR(root_stat.st_mode):
        return _EMPTY

    total_bytes = 0
    file_count = 0
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if skip and os.path.normcase(entry.path) in skip:
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if not entry.is_junction():
                                pending.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            total_bytes += entry.stat(follow_symlinks=False).st_size
                            file_count += 1
                    except OSError:
                        continue
        except OSError:
            continue
    return TreeSize(total_bytes, file_count)
