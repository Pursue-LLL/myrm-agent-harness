"""Structured input for request_directory HITL.

[POS]
See module docstring.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RequestDirectoryInput(BaseModel):
    reason: str = Field(description="Explain why access to this directory is needed for the user's task.")
    path: str = Field(
        default="",
        description="Suggested directory path (optional). User may pick a different folder.",
    )
    writable: bool = Field(
        default=False,
        description="Whether write access is required. Use false for read-only reference.",
    )
