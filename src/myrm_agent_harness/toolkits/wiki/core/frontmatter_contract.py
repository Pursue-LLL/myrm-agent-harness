"""Wiki page frontmatter contract — required `type` field and enum validation.

[INPUT]
utils.markdown_frontmatter::parse_frontmatter (POS: YAML FM parse SSOT)

[OUTPUT]
WikiPageType, WikiPublishStatus, WikiProvenance, validate_wiki_frontmatter, infer_type_for_import,
repair_missing_types, apply_compile_gate, load_frontmatter_metadata, serialize_frontmatter_block,
ensure_frontmatter_type, ensure_published_frontmatter, ensure_draft_frontmatter,
repair_publication_on_disk, PublicationOnDiskRepairResult, FrontmatterValidationError

[POS]
Harness SSOT for wiki page type gate used by compile, import writeback, linter, pending approve,
and server repair API.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum, StrEnum
from pathlib import Path

import yaml

from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.utils.markdown_frontmatter import (
    parse_frontmatter,
)


class WikiPageType(StrEnum):
    SOURCE = "source"
    ENTITY = "entity"
    CONCEPT = "concept"
    COMPARISON = "comparison"
    OVERVIEW = "overview"
    QUESTION = "question"
    SESSION = "session"


WIKI_PAGE_TYPES: frozenset[str] = frozenset(member.value for member in WikiPageType)

PUBLISH_STATUS_KEY = "publish_status"


class WikiPublishStatus(StrEnum):
    PUBLISHED = "published"
    DRAFT = "draft"
    BLOCKED = "blocked"


WIKI_PUBLISH_STATUSES: frozenset[str] = frozenset(
    member.value for member in WikiPublishStatus
)


class WikiProvenance(StrEnum):
    COMPILED = "compiled"
    REPAIRED = "repaired"
    AGENT = "agent"
    CREATE_NOTE = "create_note"
    CHAT_SAVE = "chat-save"
    CHAT_COMPOUND = "chat-compound"
    CONTRADICTION_SYNTHESIS = "contradiction_synthesis"
    IMPORT = "import"
    WEB_FETCH = "web_fetch"


_FRONTMATTER_BLOCK_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def load_frontmatter_metadata(content: str) -> tuple[dict[str, object], str]:
    """Load frontmatter metadata, preserving nested YAML structures such as claims."""
    match = _FRONTMATTER_BLOCK_RE.match(content)
    if match is not None:
        parsed = yaml.safe_load(match.group(1))
        body = content[match.end() :]
        if isinstance(parsed, dict):
            return parsed, body
    metadata, body = parse_frontmatter(content)
    return dict(metadata), body


def _metadata_requires_yaml_dump(metadata: dict[str, object]) -> bool:
    for value in metadata.values():
        if isinstance(value, dict):
            return True
        if isinstance(value, list) and any(isinstance(item, dict) for item in value):
            return True
    return False


def _coerce_enum_values(obj: object) -> object:
    """Recursively convert Enum instances to their `.value` for YAML-safe serialization."""
    if isinstance(obj, dict):
        return {k: _coerce_enum_values(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_coerce_enum_values(item) for item in obj]
    if isinstance(obj, Enum):
        return obj.value
    return obj


def serialize_frontmatter_block(metadata: dict[str, object]) -> str:
    """Serialize metadata to a YAML frontmatter block."""
    safe_metadata: dict[str, object] = _coerce_enum_values(metadata)  # type: ignore[assignment]
    if _metadata_requires_yaml_dump(safe_metadata):
        dumped = yaml.safe_dump(
            safe_metadata, allow_unicode=True, sort_keys=False, default_flow_style=False
        ).strip()
        return f"---\n{dumped}\n---\n"
    return serialize_frontmatter(safe_metadata)


class FrontmatterValidationError(ValueError):
    """Raised when wiki content fails frontmatter type validation."""

    def __init__(self, errors: tuple[str, ...]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass(frozen=True, slots=True)
class FrontmatterValidationResult:
    ok: bool
    errors: tuple[str, ...] = ()
    page_type: str | None = None


@dataclass(frozen=True, slots=True)
class TypeRepairResult:
    files_scanned: int
    files_repaired: int
    files_skipped: int
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PublicationOnDiskRepairResult:
    files_scanned: int
    files_repaired: int
    files_skipped_published: int
    files_skipped_intentional_draft: int
    errors: tuple[str, ...] = ()


def _normalize_type_value(raw_type: object) -> str | None:
    if raw_type is None:
        return None
    type_str = str(raw_type).strip().lower()
    return type_str or None


def validate_wiki_frontmatter(content: str) -> FrontmatterValidationResult:
    """Validate that markdown content has a non-empty, allowed `type` in YAML frontmatter."""
    metadata, _body = parse_frontmatter(content)
    type_str = _normalize_type_value(metadata.get("type"))
    if type_str is None:
        return FrontmatterValidationResult(
            ok=False, errors=("Missing required frontmatter field: type",)
        )
    if type_str not in WIKI_PAGE_TYPES:
        allowed = ", ".join(sorted(WIKI_PAGE_TYPES))
        return FrontmatterValidationResult(
            ok=False,
            errors=(f"Invalid type '{type_str}'; must be one of: {allowed}",),
        )
    return FrontmatterValidationResult(ok=True, page_type=type_str)


def infer_type_for_import(
    relative_path: Path | str,
    metadata: dict[str, object],
    *,
    is_raw_import: bool = True,
) -> WikiPageType:
    """Infer wiki page type for import writeback when `type` is missing or invalid."""
    existing = _normalize_type_value(metadata.get("type"))
    if existing in WIKI_PAGE_TYPES:
        return WikiPageType(existing)

    path_str = str(relative_path).lower().replace("\\", "/")
    if is_raw_import or path_str.startswith("raw/") or "/raw/" in path_str:
        return WikiPageType.SOURCE
    if "comparisons/" in path_str or "/comparison" in path_str or "compare" in path_str:
        return WikiPageType.COMPARISON
    if "questions/" in path_str or "/question" in path_str:
        return WikiPageType.QUESTION
    if "entities/" in path_str or "/entity" in path_str:
        return WikiPageType.ENTITY
    if path_str.endswith("index.md") or "/overview" in path_str:
        return WikiPageType.OVERVIEW
    if "hot.md" in path_str or "log.md" in path_str or "/session" in path_str:
        return WikiPageType.SESSION
    return WikiPageType.CONCEPT


def serialize_frontmatter(metadata: dict[str, object]) -> str:
    """Serialize metadata dict to a YAML frontmatter block (minimal, Obsidian-compatible)."""
    lines = ["---"]
    ordered_keys = [
        "type",
        PUBLISH_STATUS_KEY,
        *[key for key in metadata if key not in {"type", PUBLISH_STATUS_KEY}],
    ]
    for key in ordered_keys:
        if key not in metadata:
            continue
        value = metadata[key]
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                item_str = str(item)
                if ":" in item_str or "#" in item_str:
                    lines.append(f'  - "{item_str}"')
                else:
                    lines.append(f"  - {item_str}")
        elif isinstance(value, str) and (":" in value or value.startswith("#")):
            lines.append(f'{key}: "{value}"')
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def ensure_frontmatter_type(
    content: str,
    page_type: WikiPageType | str,
    *,
    sources: list[str] | None = None,
    provenance: str | None = None,
) -> str:
    """Merge or inject frontmatter with a valid `type` while preserving body content."""
    metadata, body = load_frontmatter_metadata(content)
    resolved = (
        page_type.value
        if isinstance(page_type, WikiPageType)
        else str(page_type).strip().lower()
    )
    metadata["type"] = resolved
    if sources is not None and "sources" not in metadata:
        metadata["sources"] = sources
    if provenance is not None and "provenance" not in metadata:
        metadata["provenance"] = provenance
    return serialize_frontmatter_block(metadata) + body.lstrip("\n")


def ensure_published_frontmatter(content: str) -> str:
    """Stamp or refresh publish_status=published and published_at on concept content."""
    metadata, body = load_frontmatter_metadata(content)
    metadata[PUBLISH_STATUS_KEY] = WikiPublishStatus.PUBLISHED.value
    metadata["published_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
    return serialize_frontmatter_block(metadata) + body.lstrip("\n")


def ensure_draft_frontmatter(content: str) -> str:
    """Stamp publish_status=draft while preserving other frontmatter fields."""
    metadata, body = load_frontmatter_metadata(content)
    metadata[PUBLISH_STATUS_KEY] = WikiPublishStatus.DRAFT.value
    metadata.pop("published_at", None)
    return serialize_frontmatter_block(metadata) + body.lstrip("\n")


def repair_publication_on_disk(
    structure: WikiStructure,
) -> PublicationOnDiskRepairResult:
    """Grandfather missing publish_status to published; skip intentional draft/blocked pages."""
    scanned = 0
    repaired = 0
    skipped_published = 0
    skipped_intentional_draft = 0
    errors: list[str] = []

    intentional_statuses = {
        WikiPublishStatus.DRAFT.value,
        WikiPublishStatus.BLOCKED.value,
    }

    for concept_path in structure.list_concepts():
        scanned += 1
        try:
            content = concept_path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"{concept_path}: {exc}")
            continue

        metadata, _body = parse_frontmatter(content)
        status = str(metadata.get(PUBLISH_STATUS_KEY, "")).strip().lower()
        if status == WikiPublishStatus.PUBLISHED.value:
            skipped_published += 1
            continue
        if status in intentional_statuses:
            skipped_intentional_draft += 1
            continue

        try:
            concept_path.write_text(
                ensure_published_frontmatter(content), encoding="utf-8"
            )
            repaired += 1
        except OSError as exc:
            errors.append(f"{concept_path}: {exc}")

    return PublicationOnDiskRepairResult(
        files_scanned=scanned,
        files_repaired=repaired,
        files_skipped_published=skipped_published,
        files_skipped_intentional_draft=skipped_intentional_draft,
        errors=tuple(errors),
    )


def apply_compile_gate(content: str, concept_name: str, source_files: list[str]) -> str:
    """Ensure compiled LLM output passes the type gate; inject or repair `concept` type when invalid."""
    validation = validate_wiki_frontmatter(content)
    if validation.ok:
        return content
    return ensure_frontmatter_type(
        content,
        WikiPageType.CONCEPT,
        sources=source_files or [concept_name],
        provenance=WikiProvenance.COMPILED,
    )


def assert_valid_wiki_frontmatter(content: str) -> None:
    """Raise FrontmatterValidationError when content fails type validation."""
    result = validate_wiki_frontmatter(content)
    if not result.ok:
        raise FrontmatterValidationError(result.errors)


def repair_file_frontmatter(
    path: Path,
    *,
    is_raw_import: bool,
    relative_path: str | None = None,
) -> bool:
    """Repair a single markdown file in place. Returns True when content was rewritten."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return False

    validation = validate_wiki_frontmatter(content)
    if validation.ok:
        return False

    metadata, _body = load_frontmatter_metadata(content)
    rel = relative_path if relative_path is not None else path.name
    page_type = infer_type_for_import(rel, metadata, is_raw_import=is_raw_import)

    sources: list[str] | None = [rel] if is_raw_import else None
    repaired = ensure_frontmatter_type(
        content, page_type, sources=sources, provenance=WikiProvenance.REPAIRED
    )
    path.write_text(repaired, encoding="utf-8")
    return True


def repair_missing_types(structure: WikiStructure) -> TypeRepairResult:
    """Scan concept and raw markdown files; inject valid `type` where missing or invalid."""
    scanned = 0
    repaired = 0
    skipped = 0
    errors: list[str] = []

    for concept_path in structure.list_concepts():
        scanned += 1
        rel = str(
            concept_path.relative_to(structure.concepts_dir).with_suffix("")
        ).replace("\\", "/")
        try:
            if repair_file_frontmatter(
                concept_path, is_raw_import=False, relative_path=rel
            ):
                repaired += 1
            else:
                skipped += 1
        except OSError as exc:
            errors.append(f"{concept_path}: {exc}")

    for raw_path in structure.list_raw_files():
        scanned += 1
        rel = str(raw_path.relative_to(structure.raw_dir)).replace("\\", "/")
        try:
            if repair_file_frontmatter(raw_path, is_raw_import=True, relative_path=rel):
                repaired += 1
            else:
                skipped += 1
        except OSError as exc:
            errors.append(f"{raw_path}: {exc}")

    return TypeRepairResult(
        files_scanned=scanned,
        files_repaired=repaired,
        files_skipped=skipped,
        errors=tuple(errors),
    )
