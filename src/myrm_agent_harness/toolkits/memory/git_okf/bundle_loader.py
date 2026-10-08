"""Git-native loader for Google OKF v0.2 knowledge bundles.

[INPUT]
- toolkits.memory.git_okf.in_memory_bm25::InMemoryBM25Searcher (POS: High-performance in-memory BM25 lexical
  searcher for OKF concept bundles.)
- toolkits.memory.git_okf.models::ConceptStatus, ConceptSummaryItem, GovernanceLevel, OKFConcept,
  OKFDisclosureSummary, OKFGenerated, OKFSearchResult, OKFSource, OKFValidationReport, OKFVerified (POS: Types
  and models for git okf.)
- toolkits.memory.git_okf.validator::OKFConceptValidator (POS: Strict validator implementing Google OKF v0.2
  conformance checks,.)
- Third-party: yaml

[OUTPUT]
- OKFBundleLoader: Git-native loader for Google OKF v0.2 knowledge bundles.

[POS]
Git-native loader for Google OKF v0.2 knowledge bundles.
"""

import os
import posixpath
import re
from pathlib import Path

import yaml

from myrm_agent_harness.toolkits.memory.git_okf.in_memory_bm25 import InMemoryBM25Searcher
from myrm_agent_harness.toolkits.memory.git_okf.models import (
    ConceptStatus,
    ConceptSummaryItem,
    GovernanceLevel,
    OKFConcept,
    OKFDisclosureSummary,
    OKFGenerated,
    OKFSearchResult,
    OKFSource,
    OKFValidationReport,
    OKFVerified,
)
from myrm_agent_harness.toolkits.memory.git_okf.validator import OKFConceptValidator

_FRONTMATTER_REGEX = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def _split_frontmatter(raw_text: str) -> tuple[dict[str, object], str]:
    """Extract YAML frontmatter dictionary and markdown body content."""
    match = _FRONTMATTER_REGEX.match(raw_text.strip())
    if not match:
        return {}, raw_text.strip()
    fm_raw, body = match.groups()
    try:
        data = yaml.safe_load(fm_raw)
        if isinstance(data, dict):
            return {str(k): v for k, v in data.items()}, body.strip()
    except Exception:
        pass
    return {}, raw_text.strip()


class OKFBundleLoader:
    """Git-native loader for Google OKF v0.2 knowledge bundles.

    Parses markdown frontmatter, coordinates memory rot audits,
    and provides two-phase progressive disclosure to eliminate token inflation.
    """

    def __init__(self, root_dir: str | Path, declared_version: str = "0.2") -> None:
        self._root_dir = Path(root_dir).resolve()
        self._declared_version = declared_version
        self._concepts: dict[str, OKFConcept] = {}
        self._searcher = InMemoryBM25Searcher()
        self._validator = OKFConceptValidator(declared_version=declared_version)

    @property
    def root_dir(self) -> Path:
        return self._root_dir

    @property
    def concepts(self) -> dict[str, OKFConcept]:
        return self._concepts

    def load_bundle(self) -> int:
        """Scan bundle directory, parse concept files, and build lexical indices."""
        self._concepts.clear()
        if not self._root_dir.is_dir():
            return 0

        for root, dirs, files in os.walk(self._root_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", ".venv", "__pycache__")]
            for file_name in files:
                if not file_name.endswith(".md"):
                    continue
                file_path = Path(root) / file_name
                rel_path = posixpath.normpath(str(file_path.relative_to(self._root_dir)).replace("\\", "/"))

                # Exclude root index.md from standalone concept list (it's the bundle catalog)
                if rel_path == "index.md":
                    continue

                concept_id = rel_path[:-3] if rel_path.endswith(".md") else rel_path

                try:
                    raw_text = file_path.read_text(encoding="utf-8")
                except Exception:
                    continue

                fm, body = _split_frontmatter(raw_text)

                gov_raw = str(fm.get("governance", "context")).lower()
                gov = (
                    GovernanceLevel.CONSTRAINT
                    if gov_raw == "constraint"
                    else GovernanceLevel.HOLD
                    if gov_raw == "hold"
                    else GovernanceLevel.CONTEXT
                )

                status_raw = str(fm.get("status", "stable")).lower()
                status = (
                    ConceptStatus.DRAFT
                    if status_raw == "draft"
                    else ConceptStatus.DEPRECATED
                    if status_raw == "deprecated"
                    else ConceptStatus.STABLE
                )

                # Parse generated
                generated: OKFGenerated | None = None
                gen_dict = fm.get("generated")
                if isinstance(gen_dict, dict):
                    generated = OKFGenerated(
                        by=str(gen_dict.get("by", "")),
                        at=str(gen_dict.get("at", "")),
                    )

                # Parse verified
                verified_list: list[OKFVerified] = []
                ver_items = fm.get("verified")
                if isinstance(ver_items, list):
                    for v in ver_items:
                        if isinstance(v, dict):
                            verified_list.append(
                                OKFVerified(
                                    by=str(v.get("by", "")),
                                    at=str(v.get("at", "")),
                                )
                            )

                # Parse code_refs
                code_refs: list[str] = []
                refs_raw = fm.get("code_refs")
                if isinstance(refs_raw, list):
                    code_refs = [str(r) for r in refs_raw if r]

                # Parse tags
                tags: list[str] = []
                tags_raw = fm.get("tags")
                if isinstance(tags_raw, list):
                    tags = [str(t) for t in tags_raw if t]

                # Parse sources
                sources: list[OKFSource] = []
                sources_raw = fm.get("sources")
                if isinstance(sources_raw, list):
                    for s in sources_raw:
                        if isinstance(s, dict):
                            sources.append(
                                OKFSource(
                                    resource=str(s.get("resource", "")),
                                    id=str(s.get("id", "")),
                                    title=str(s.get("title", "")),
                                    author=str(s.get("author", "")),
                                    last_modified=str(s.get("last_modified", "")),
                                    usage_count=int(str(s.get("usage_count", 0))),
                                )
                            )

                concept = OKFConcept(
                    id=concept_id,
                    path=rel_path,
                    type=str(fm.get("type", "knowledge")),
                    title=str(fm.get("title", concept_id)),
                    description=str(fm.get("description", "")),
                    governance=gov,
                    status=status,
                    stale_after=str(fm.get("stale_after", "")),
                    code_refs=code_refs,
                    tags=tags,
                    generated=generated,
                    verified=verified_list,
                    sources=sources,
                    body=body,
                    raw_content=raw_text,
                )
                self._concepts[concept_id] = concept

        self._searcher.index(list(self._concepts.values()))
        return len(self._concepts)

    def search(
        self,
        query: str,
        limit: int = 10,
        filter_governance: str | None = None,
        filter_status: str | None = None,
    ) -> list[OKFSearchResult]:
        """Perform sub-millisecond lexical search over loaded concepts with staleness annotation."""
        results = self._searcher.search(
            query=query,
            limit=limit,
            filter_governance=filter_governance,
            filter_status=filter_status,
        )
        # Augment with staleness status
        for res in results:
            c = self._concepts.get(res.concept_id)
            if c:
                res.is_stale = self._validator.is_concept_stale(c)
        return results

    def validate(self) -> OKFValidationReport:
        """Run full OKF v0.2 audit on loaded bundle."""
        return self._validator.validate(
            concepts=list(self._concepts.values()),
            bundle_path=str(self._root_dir),
        )

    def get_disclosure_summary(self) -> OKFDisclosureSummary:
        """Generate first-phase progressive disclosure summary card (~300 tokens footprint).

        Reduces context token usage by >80% while preserving high-level architectural awareness.
        """
        stale_count = 0
        summaries: list[ConceptSummaryItem] = []

        for cid in sorted(self._concepts.keys()):
            c = self._concepts[cid]
            is_stale = self._validator.is_concept_stale(c)
            if is_stale:
                stale_count += 1
            summaries.append(
                ConceptSummaryItem(
                    id=c.id,
                    title=c.title,
                    description=c.description,
                    governance=c.effective_governance().value,
                    status=c.status.value,
                    is_stale=is_stale,
                    code_refs=list(c.code_refs),
                )
            )

        return OKFDisclosureSummary(
            bundle_path=str(self._root_dir),
            total_concepts=len(self._concepts),
            stale_count=stale_count,
            concepts=summaries,
        )

    def get_concept(self, concept_id: str) -> OKFConcept | None:
        """Retrieve full concept card on demand for phase two detailed inspection."""
        return self._concepts.get(concept_id)
