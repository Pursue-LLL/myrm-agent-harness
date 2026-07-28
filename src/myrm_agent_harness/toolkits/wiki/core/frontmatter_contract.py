"""Wiki page frontmatter contract — required `type` field and enum validation.

[INPUT]
agent.meta_tools.file_ops.utils.markdown_frontmatter::parse_frontmatter (POS: YAML FM parse SSOT)

[OUTPUT]
WikiPageType, validate_wiki_frontmatter, infer_type_for_import, repair_missing_types,
apply_compile_gate, ensure_frontmatter_type, FrontmatterValidationError

[POS]
Harness SSOT for wiki page type gate used by compile, import writeback, linter, pending approve,
and server repair API.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from myrm_agent_harness.agent.meta_tools.file_ops.utils.markdown_frontmatter import parse_frontmatter
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure


class WikiPageType(StrEnum):
    SOURCE = "source"
    ENTITY = "entity"
    CONCEPT = "concept"
    COMPARISON = "comparison"
    OVERVIEW = "overview"
    QUESTION = "question"
    SESSION = "session"


WIKI_PAGE_TYPES: frozenset[str] = frozenset(member.value for member in WikiPageType)


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
        return FrontmatterValidationResult(ok=False, errors=("Missing required frontmatter field: type",))
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
    for key, value in metadata.items():
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
    metadata, body = parse_frontmatter(content)
    resolved = page_type.value if isinstance(page_type, WikiPageType) else str(page_type).strip().lower()
    metadata["type"] = resolved
    if sources is not None and "sources" not in metadata:
        metadata["sources"] = sources
    if provenance is not None and "provenance" not in metadata:
        metadata["provenance"] = provenance
    return serialize_frontmatter(metadata) + body.lstrip("\n")


def apply_compile_gate(content: str, concept_name: str, source_files: list[str]) -> str:
    """Ensure compiled LLM output passes the type gate; auto-inject `concept` when missing."""
    validation = validate_wiki_frontmatter(content)
    if validation.ok:
        return content
    return ensure_frontmatter_type(
        content,
        WikiPageType.CONCEPT,
        sources=source_files or [concept_name],
        provenance="compiled",
    )


def assert_valid_wiki_frontmatter(content: str) -> None:
    """Raise FrontmatterValidationError when content fails type validation."""
    result = validate_wiki_frontmatter(content)
    if not result.ok:
        raise FrontmatterValidationError(result.errors)


def repair_file_frontmatter(path: Path, *, is_raw_import: bool) -> bool:
    """Repair a single markdown file in place. Returns True when content was rewritten."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return False

    validation = validate_wiki_frontmatter(content)
    if validation.ok:
        return False

    metadata, _body = parse_frontmatter(content)
    try:
        rel = path.name if is_raw_import else str(path)
        page_type = infer_type_for_import(rel, metadata, is_raw_import=is_raw_import)
    except Exception:
        page_type = WikiPageType.SOURCE if is_raw_import else WikiPageType.CONCEPT

    sources: list[str] | None = None
    if is_raw_import:
        sources = [path.name]
    repaired = ensure_frontmatter_type(content, page_type, sources=sources, provenance="repaired")
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
        try:
            if repair_file_frontmatter(concept_path, is_raw_import=False):
                repaired += 1
            else:
                skipped += 1
        except OSError as exc:
            errors.append(f"{concept_path}: {exc}")

    for raw_path in structure.list_raw_files():
        scanned += 1
        try:
            if repair_file_frontmatter(raw_path, is_raw_import=True):
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
