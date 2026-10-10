"""Dynamic Project Entity Linker for cross-source context fabric.

[INPUT]
- Text snippets, WorkEvent objects, and registered ProjectRegistryEntry objects.

[OUTPUT]
- ProjectEntityLinker: computes semantic and lexical attribution to active projects,
  returning sorted EntityMatchResult collections.

[POS]
- Project entity linker for Item 153 CrossSourceWorkContextFabricAndProjectEntityLinkerSuite.
"""

from __future__ import annotations

import re

from .models import EntityMatchResult, ProjectRegistryEntry, WorkEvent


class ProjectEntityLinker:
    """Links unstructured texts or work events to active workspace projects."""

    def __init__(self, initial_projects: list[ProjectRegistryEntry] | None = None) -> None:
        self._registry: dict[str, ProjectRegistryEntry] = {}
        if initial_projects:
            for p in initial_projects:
                self.register_project(p)

    def register_project(self, project: ProjectRegistryEntry) -> None:
        """Register or update an active project entry."""
        self._registry[project.project_id] = project

    def unregister_project(self, project_id: str) -> None:
        """Remove a project from active resolution registry."""
        self._registry.pop(project_id, None)

    def get_project(self, project_id: str) -> ProjectRegistryEntry | None:
        """Lookup a registered project by its identifier."""
        return self._registry.get(project_id)

    def list_projects(self) -> list[ProjectRegistryEntry]:
        """List all currently registered projects."""
        return list(self._registry.values())

    def link_event(
        self,
        event: WorkEvent,
        min_confidence: float = 0.4,
    ) -> list[EntityMatchResult]:
        """Link a WorkEvent to canonical projects based on title and content."""
        full_text = f"{event.title}\n{event.raw_content}"
        return self.link_text(full_text, min_confidence=min_confidence)

    def link_text(
        self,
        text: str,
        min_confidence: float = 0.4,
    ) -> list[EntityMatchResult]:
        """Evaluate text against registered projects and return sorted match candidates."""
        if not text.strip() or not self._registry:
            return []

        lower_text = text.lower()
        results: list[EntityMatchResult] = []

        for project in self._registry.values():
            if project.status == "archived":
                continue

            score = 0.0
            matched_terms: list[str] = []
            evidence_snippets: list[str] = []

            # 1. Exact name match
            if project.name.lower() in lower_text:
                score += 0.6
                matched_terms.append(project.name)
                evidence_snippets.append(self._find_snippet(text, project.name))

            # 2. Aliases match
            alias_score = 0.0
            for alias in project.aliases:
                if alias and alias.lower() in lower_text:
                    alias_score = min(0.6, alias_score + 0.45)
                    matched_terms.append(alias)
                    evidence_snippets.append(self._find_snippet(text, alias))
            score += alias_score

            # 3. Keywords density match
            keyword_score = 0.0
            for kw in project.keywords:
                if kw and kw.lower() in lower_text:
                    keyword_score = min(0.4, keyword_score + 0.15)
                    matched_terms.append(kw)
                    if len(evidence_snippets) < 2:
                        evidence_snippets.append(self._find_snippet(text, kw))
            score += keyword_score

            final_score = min(1.0, score)
            if final_score >= min_confidence:
                snippet = "; ".join(filter(None, evidence_snippets))[:120]
                results.append(
                    EntityMatchResult(
                        project_id=project.project_id,
                        project_name=project.name,
                        confidence_score=round(final_score, 2),
                        matched_terms=tuple(dict.fromkeys(matched_terms)),
                        evidence_snippet=snippet,
                        is_definitive=(final_score >= 0.7),
                    )
                )

        # Sort by confidence descending
        results.sort(key=lambda r: r.confidence_score, reverse=True)
        return results

    def _find_snippet(self, full_text: str, target: str, window: int = 35) -> str:
        """Extract a short context window around the first occurrence of target."""
        pos = full_text.lower().find(target.lower())
        if pos == -1:
            return ""
        start = max(0, pos - window)
        end = min(len(full_text), pos + len(target) + window)
        snippet = full_text[start:end].replace("\n", " ").strip()
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(full_text) else ""
        return f"{prefix}{snippet}{suffix}"
