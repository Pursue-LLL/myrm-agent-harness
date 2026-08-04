"""File meta-tool mount policy SSOT.

[OUTPUT]
- FileAccessMode: enum for file_read / file_write mount surface
- file_access_mode_includes_read: whether file_read_tool is mounted
- file_access_mode_includes_write: whether write/edit/glob/grep mount

[POS]
Harness agent mount contract. Server ``tool_mount.resolve_agent_mount`` maps
product surfaces to FileAccessMode; ``get_meta_tools`` executes the mount.
"""

from __future__ import annotations

from enum import StrEnum


class FileAccessMode(StrEnum):
    """How file meta-tools mount on Turn1."""

    FULL = "full"
    SPILL_AND_UPLOADS = "spill_and_uploads"
    NONE = "none"


def file_access_mode_includes_read(mode: FileAccessMode) -> bool:
    return mode != FileAccessMode.NONE


def file_access_mode_includes_write(mode: FileAccessMode) -> bool:
    return mode == FileAccessMode.FULL
