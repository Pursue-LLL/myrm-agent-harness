"""Directory sidecar builder for hierarchical wiki retrieval.

[INPUT]
langchain_core.language_models::BaseChatModel (POS: LLM summarisation engine)
langchain_core.messages::HumanMessage, SystemMessage (POS: prompt messages)
..core.structure::WikiStructure (POS: concept tree filesystem abstraction)
..core.config::WikiCompileConfig (POS: sidecar generation knobs)
..core.types::ConceptInfo (POS: touched concept hints from compiler)

[OUTPUT]
SidecarBuildResult: sidecar build statistics
build_directory_sidecars(): incremental bottom-up sidecar build entrypoint

[POS]
Builds L0/L1 directory sidecars (`.abstract.md`, `.overview.md`) using a bottom-up
incremental DAG. Parent sidecars depend on immediate file summaries and child
directory abstracts, so only changed subtrees are rebuilt.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from myrm_agent_harness.utils.logger_utils import get_agent_logger

from ..core.config import WikiCompileConfig
from ..core.structure import WikiStructure
from ..core.types import ConceptInfo

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer

logger = get_agent_logger(__name__)

_STATE_FILE = ".sidecar_state.json"
_MAX_FILE_SUMMARY_CHARS = 480
_MAX_CHILD_ABSTRACT_CHARS = 360
_MAX_ABSTRACT_CHARS = 1200
_MAX_OVERVIEW_CHARS = 4000
_MAX_INPUT_ROWS = 20
_ROOT_LABEL = "__root__"


@dataclass(frozen=True, slots=True)
class _FileSemantic:
    path: Path
    rel_dir: str
    truth_hash: str
    summary: str


@dataclass(frozen=True, slots=True)
class SidecarBuildResult:
    rebuilt_directories: int
    skipped_directories: int
    removed_directories: int


async def build_directory_sidecars(
    llm: BaseChatModel,
    structure: WikiStructure,
    compile_config: WikiCompileConfig,
    touched_concepts: list[ConceptInfo],
    indexer: WikiIndexer | None,
) -> SidecarBuildResult:
    """Build directory sidecars with bottom-up incremental DAG semantics."""
    builder = WikiDirectorySidecarBuilder(llm, structure, compile_config, indexer=indexer)
    return await builder.build_incremental(touched_concepts)


class WikiDirectorySidecarBuilder:
    """Incremental sidecar builder (L0/L1) with parent-chain invalidation."""

    def __init__(
        self,
        llm: BaseChatModel,
        structure: WikiStructure,
        compile_config: WikiCompileConfig,
        *,
        indexer: WikiIndexer | None = None,
    ) -> None:
        self._llm = llm
        self._structure = structure
        self._compile_config = compile_config
        self._indexer = indexer
        self._state_path = self._structure.wiki_dir / _STATE_FILE

    async def build_incremental(self, touched_concepts: list[ConceptInfo]) -> SidecarBuildResult:
        files = self._collect_file_semantics()
        if not files:
            removed = await self._clear_all_sidecars()
            self._write_state({})
            return SidecarBuildResult(
                rebuilt_directories=0,
                skipped_directories=0,
                removed_directories=removed,
            )

        directories = self._collect_directories(files)
        old_signatures = self._read_state()
        new_signatures = self._compute_signatures(directories, files)
        touched_dirs = self._resolve_touched_directories(touched_concepts)

        rebuilt = 0
        skipped = 0
        abstract_cache: dict[str, str] = {}

        for directory in sorted(directories, key=self._directory_depth, reverse=True):
            abstract_path, overview_path = self._structure.get_directory_sidecar_paths(directory)
            signature = new_signatures[directory]
            old_signature = old_signatures.get(directory)
            needs_rebuild = (
                directory in touched_dirs
                or old_signature != signature
                or not abstract_path.exists()
                or not overview_path.exists()
            )

            if needs_rebuild:
                file_summaries = self._immediate_file_summaries(directory, files)
                child_abstracts = self._child_abstracts(directory, directories, abstract_cache)
                abstract, overview = await self._generate_sidecar_pair(
                    directory=directory,
                    file_summaries=file_summaries,
                    child_abstracts=child_abstracts,
                )
                abstract_path.write_text(abstract, encoding="utf-8")
                overview_path.write_text(overview, encoding="utf-8")
                await self._upsert_sidecar_index(directory, abstract, overview)
                rebuilt += 1
                abstract_cache[directory] = abstract
            else:
                skipped += 1
                abstract_cache[directory] = abstract_path.read_text(encoding="utf-8")

        removed = await self._remove_stale_sidecars(
            stale_dirs=set(old_signatures) - set(new_signatures)
        )
        self._write_state(new_signatures)
        return SidecarBuildResult(
            rebuilt_directories=rebuilt,
            skipped_directories=skipped,
            removed_directories=removed,
        )

    def _collect_file_semantics(self) -> list[_FileSemantic]:
        semantics: list[_FileSemantic] = []
        for concept_path in self._structure.list_concepts():
            try:
                rel = concept_path.relative_to(self._structure.concepts_dir).with_suffix("")
            except ValueError:
                # Public mounted wiki is read-only and maintains its own sidecars.
                continue
            rel_dir = self._normalize_dir(str(rel.parent).replace("\\", "/"))
            content = concept_path.read_text(encoding="utf-8")
            truth = self._extract_truth(content)
            truth_hash = hashlib.sha256(truth.encode("utf-8")).hexdigest()
            summary = self._extract_compact_summary(truth, max_chars=_MAX_FILE_SUMMARY_CHARS)
            semantics.append(
                _FileSemantic(
                    path=concept_path,
                    rel_dir=rel_dir,
                    truth_hash=truth_hash,
                    summary=summary,
                )
            )
        return semantics

    def _collect_directories(self, files: list[_FileSemantic]) -> set[str]:
        directories = {""}
        for item in files:
            for parent in self._iter_parent_chain(item.rel_dir):
                directories.add(parent)
        return directories

    def _compute_signatures(self, directories: set[str], files: list[_FileSemantic]) -> dict[str, str]:
        by_dir: dict[str, list[_FileSemantic]] = {}
        for item in files:
            by_dir.setdefault(item.rel_dir, []).append(item)

        signatures: dict[str, str] = {}
        for directory in sorted(directories, key=self._directory_depth, reverse=True):
            parts: list[str] = []
            for f in sorted(by_dir.get(directory, []), key=lambda x: x.path.as_posix()):
                parts.append(f"f:{f.path.name}:{f.truth_hash}")
            for child in sorted(self._immediate_child_dirs(directory, directories)):
                parts.append(f"d:{child}:{signatures.get(child, '')}")
            digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
            signatures[directory] = digest
        return signatures

    def _resolve_touched_directories(self, touched_concepts: list[ConceptInfo]) -> set[str]:
        touched: set[str] = set()
        for concept in touched_concepts:
            safe = self._structure._sanitize_path(concept.name)
            rel_dir = self._normalize_dir(safe.rsplit("/", 1)[0] if "/" in safe else "")
            for parent in self._iter_parent_chain(rel_dir):
                touched.add(parent)
        return touched

    def _immediate_file_summaries(self, directory: str, files: list[_FileSemantic]) -> list[str]:
        rows = [
            f"{item.path.stem}: {item.summary}"
            for item in files
            if item.rel_dir == directory and item.summary
        ]
        return rows[:_MAX_INPUT_ROWS]

    def _child_abstracts(
        self,
        directory: str,
        directories: set[str],
        abstract_cache: dict[str, str],
    ) -> list[str]:
        rows: list[str] = []
        for child in self._immediate_child_dirs(directory, directories):
            abstract = abstract_cache.get(child)
            if not abstract:
                child_abstract_path, _ = self._structure.get_directory_sidecar_paths(
                    child,
                    create=False,
                )
                if child_abstract_path.exists():
                    abstract = child_abstract_path.read_text(encoding="utf-8")
            if abstract:
                short = self._extract_compact_summary(abstract, max_chars=_MAX_CHILD_ABSTRACT_CHARS)
                if short:
                    rows.append(f"{child}: {short}")
        return rows[:_MAX_INPUT_ROWS]

    async def _generate_sidecar_pair(
        self,
        *,
        directory: str,
        file_summaries: list[str],
        child_abstracts: list[str],
    ) -> tuple[str, str]:
        if not file_summaries and not child_abstracts:
            return (
                "No validated knowledge yet for this directory.",
                "No compiled knowledge is currently available for this directory.",
            )

        prompt = (
            f"Directory path: {directory or '/'}\n\n"
            "Immediate file summaries:\n"
            + ("\n".join(f"- {row}" for row in file_summaries) if file_summaries else "- (none)")
            + "\n\nChild directory abstracts:\n"
            + ("\n".join(f"- {row}" for row in child_abstracts) if child_abstracts else "- (none)")
            + "\n\nReturn STRICT JSON with exactly two keys:\n"
            + '{"abstract": "<L0 concise summary>", "overview": "<L1 detailed overview>"}\n'
            + "Rules:\n"
            + "- abstract: <= 1200 chars, high-density core facts only.\n"
            + "- overview: <= 4000 chars, structured and evidence-oriented.\n"
            + "- Do not include markdown code fences.\n"
        )
        system_msg = SystemMessage(
            content=(
                "You are generating hierarchical wiki sidecars for retrieval routing. "
                "Be factual, concise, and avoid speculation."
            )
        )
        try:
            response = await self._llm.ainvoke([system_msg, HumanMessage(content=prompt)])
            parsed = self._parse_sidecar_payload(str(response.content))
            if parsed is not None:
                abstract, overview = parsed
                return (
                    self._clip_text(abstract, _MAX_ABSTRACT_CHARS),
                    self._clip_text(overview, _MAX_OVERVIEW_CHARS),
                )
        except Exception as e:
            logger.warning("Directory sidecar LLM generation failed for %s: %s", directory or "/", e)

        fallback_lines = file_summaries + child_abstracts
        fallback = "\n".join(fallback_lines).strip() or "No validated knowledge yet."
        abstract = self._clip_text(fallback, _MAX_ABSTRACT_CHARS)
        overview = self._clip_text(fallback, _MAX_OVERVIEW_CHARS)
        return abstract, overview

    async def _upsert_sidecar_index(self, directory: str, abstract: str, overview: str) -> None:
        if self._indexer is None:
            return
        upsert = getattr(self._indexer, "upsert_sidecar", None)
        if not callable(upsert):
            return
        try:
            await upsert(directory, level=0, content=abstract)
            await upsert(directory, level=1, content=overview)
        except Exception as e:
            logger.warning("Sidecar index upsert failed for %s: %s", directory or "/", e)

    async def _clear_all_sidecars(self) -> int:
        removed = 0
        for sidecar in self._iter_sidecar_files():
            with contextlib.suppress(OSError):
                sidecar.unlink()
                removed += 1
        if self._indexer is not None:
            clear = getattr(self._indexer, "delete_all_sidecars", None)
            if callable(clear):
                with contextlib.suppress(Exception):
                    await clear()
        return removed

    async def _remove_stale_sidecars(self, stale_dirs: set[str]) -> int:
        removed = 0
        if not stale_dirs:
            return removed
        for directory in sorted(stale_dirs):
            abstract_path, overview_path = self._structure.get_directory_sidecar_paths(
                directory,
                create=False,
            )
            for sidecar in (abstract_path, overview_path):
                if sidecar.exists():
                    with contextlib.suppress(OSError):
                        sidecar.unlink()
                        removed += 1
            if self._indexer is not None:
                delete = getattr(self._indexer, "delete_sidecar", None)
                if callable(delete):
                    with contextlib.suppress(Exception):
                        await delete(directory, level=0)
                        await delete(directory, level=1)
        return removed

    def _read_state(self) -> dict[str, str]:
        if not self._state_path.exists():
            return {}
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
            raw_signatures = payload.get("signatures", {})
            if not isinstance(raw_signatures, dict):
                return {}
            signatures: dict[str, str] = {}
            for key, value in raw_signatures.items():
                if not isinstance(key, str) or not isinstance(value, str):
                    continue
                signatures[self._state_key_decode(key)] = value
            return signatures
        except Exception:
            return {}

    def _write_state(self, signatures: dict[str, str]) -> None:
        payload = {
            "updated_at": datetime.now(UTC).isoformat(),
            "signatures": {
                self._state_key_encode(directory): signature
                for directory, signature in signatures.items()
            },
        }
        self._state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _extract_truth(content: str) -> str:
        truth_match = re.search(r"(## Compiled Truth\n.*?)(?=\n## |$)", content, re.DOTALL)
        if truth_match:
            return truth_match.group(1).strip()
        return content.strip()

    @staticmethod
    def _extract_compact_summary(text: str, *, max_chars: int) -> str:
        stripped = re.sub(r"^---\n.*?\n---\n*", "", text, count=1, flags=re.DOTALL)
        lines: list[str] = []
        total = 0
        for line in stripped.splitlines():
            row = line.strip()
            if not row or row.startswith("#"):
                continue
            lines.append(row)
            total += len(row)
            if total >= max_chars:
                break
        merged = " ".join(lines).strip()
        return WikiDirectorySidecarBuilder._clip_text(merged, max_chars)

    @staticmethod
    def _clip_text(text: str, max_chars: int) -> str:
        clean = text.strip()
        if len(clean) <= max_chars:
            return clean
        clipped = clean[:max_chars].rsplit(" ", 1)[0].strip()
        return (clipped or clean[:max_chars]).strip() + "…"

    @staticmethod
    def _parse_sidecar_payload(raw: str) -> tuple[str, str] | None:
        text = raw.strip()
        if not text:
            return None
        candidates = [text]
        fenced = re.search(r"\{.*\}", text, re.DOTALL)
        if fenced:
            candidates.append(fenced.group(0))
        for candidate in candidates:
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            abstract = payload.get("abstract")
            overview = payload.get("overview")
            if isinstance(abstract, str) and isinstance(overview, str):
                return abstract.strip(), overview.strip()
        return None

    @staticmethod
    def _directory_depth(directory: str) -> int:
        if not directory:
            return 0
        return len([part for part in directory.split("/") if part])

    @staticmethod
    def _normalize_dir(directory: str) -> str:
        if directory in ("", ".", "/"):
            return ""
        return directory.strip("/").replace("\\", "/")

    @classmethod
    def _iter_parent_chain(cls, directory: str) -> list[str]:
        normalized = cls._normalize_dir(directory)
        chain = [normalized]
        while normalized:
            parent = normalized.rsplit("/", 1)[0] if "/" in normalized else ""
            chain.append(parent)
            normalized = parent
        if "" not in chain:
            chain.append("")
        return list(dict.fromkeys(chain))

    @classmethod
    def _immediate_child_dirs(cls, directory: str, directories: set[str]) -> list[str]:
        normalized = cls._normalize_dir(directory)
        children: list[str] = []
        for candidate in directories:
            if candidate == normalized:
                continue
            if normalized:
                if not candidate.startswith(f"{normalized}/"):
                    continue
                suffix = candidate[len(normalized) + 1 :]
            else:
                if "/" not in candidate:
                    if candidate:
                        children.append(candidate)
                    continue
                suffix = candidate
            if suffix and "/" not in suffix:
                children.append(candidate)
        return sorted(set(children))

    def _iter_sidecar_files(self) -> list[Path]:
        sidecar_names = {
            self._structure.DIRECTORY_ABSTRACT_FILENAME,
            self._structure.DIRECTORY_OVERVIEW_FILENAME,
        }
        files: list[Path] = []
        for md in self._structure.concepts_dir.rglob("*.md"):
            if md.name in sidecar_names:
                files.append(md)
        return files

    @staticmethod
    def _state_key_encode(directory: str) -> str:
        return _ROOT_LABEL if directory == "" else directory

    @staticmethod
    def _state_key_decode(directory: str) -> str:
        return "" if directory == _ROOT_LABEL else directory

