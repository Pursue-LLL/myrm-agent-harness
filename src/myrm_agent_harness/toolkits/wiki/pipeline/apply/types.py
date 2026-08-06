"""Wiki apply request/result types.

[POS]
See module docstring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal


class WikiApplyOp(StrEnum):
    UPDATE_METADATA = "update_metadata"
    PATCH_COMPILED_TRUTH = "patch_compiled_truth"
    APPEND_TIMELINE = "append_timeline"
    CREATE_NOTE = "create_note"
    REPLACE_FULL_DOCUMENT = "replace_full_document"


WikiApplyCaller = Literal["agent", "settings", "chat"]


@dataclass(frozen=True, slots=True)
class WikiApplyRequest:
    op: WikiApplyOp
    concept_name: str
    compiled_truth: str = ""
    timeline_entry: str = ""
    content: str = ""
    body: str = ""
    tags: tuple[str, ...] | None = None
    aliases: tuple[str, ...] | None = None
    sources: tuple[str, ...] | None = None
    claims: tuple[dict[str, object], ...] = ()
    clear_confidence: bool = False
    page_type: str = "session"
    provenance: str = ""
    metadata: dict[str, object] = field(default_factory=dict)
    canonical_id: str | None = None
    if_match: str | None = None


@dataclass(frozen=True, slots=True)
class WikiApplyResult:
    success: bool
    op: WikiApplyOp
    concept_name: str
    message: str
    created: bool = False
    appended: bool = False
    content: str = ""
    content_hash: str = ""
