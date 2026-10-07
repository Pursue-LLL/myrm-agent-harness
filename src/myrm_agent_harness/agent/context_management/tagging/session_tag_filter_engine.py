# ============================================================================
# SessionTagFilterEngine (Item 156)
# Production-grade session tagging registry, multi-dimensional metadata filter,
# autonomous semantic tag recommender, and tag popularity analytics.
# ============================================================================

from __future__ import annotations

import logging
import re
import uuid

from .session_tag_types import (
    AutoTagSuggestion,
    SessionFilterQuery,
    SessionTag,
    TagCategory,
    TagColor,
    TagDistribution,
    TaggedSessionItem,
    TagMatchMode,
)

logger = logging.getLogger(__name__)

# Rule-based semantic classifiers for auto-tag recommendations
_SEMANTIC_RULES: list[tuple[re.Pattern[str], str, TagCategory, TagColor, str]] = [
    (
        re.compile(r"\b(bug|fix|error|exception|fail|crash|traceback|panic)\b", re.IGNORECASE),
        "BugFix",
        TagCategory.TASK_TYPE,
        TagColor.RED,
        "Detected error handling or bug fixing keywords",
    ),
    (
        re.compile(r"\b(refactor|cleanup|decouple|restructure|modular|split)\b", re.IGNORECASE),
        "Refactor",
        TagCategory.TASK_TYPE,
        TagColor.PURPLE,
        "Detected code restructuring and modularization intention",
    ),
    (
        re.compile(r"\b(test|pytest|unittest|coverage|mock|assert)\b", re.IGNORECASE),
        "Testing",
        TagCategory.TASK_TYPE,
        TagColor.GREEN,
        "Detected test suite execution or verification patterns",
    ),
    (
        re.compile(r"\b(architect|design|dag|system|protocol|contract)\b", re.IGNORECASE),
        "Architecture",
        TagCategory.TASK_TYPE,
        TagColor.BLUE,
        "Detected architectural design and contract specifications",
    ),
    (
        re.compile(r"\b(deploy|docker|k8s|kubernetes|pipeline|ci/cd|build)\b", re.IGNORECASE),
        "DevOps",
        TagCategory.PROJECT_TOPIC,
        TagColor.AMBER,
        "Detected infrastructure, deployment or CI/CD pipelines",
    ),
    (
        re.compile(r"\b(security|auth|jwt|token|encrypt|permission|rbac)\b", re.IGNORECASE),
        "Security",
        TagCategory.PROJECT_TOPIC,
        TagColor.RED,
        "Detected security, identity authentication or RBAC boundaries",
    ),
]


class SessionTagFilterEngine:
    """Manages tag catalog, session associations, queries, and auto-classification."""

    def __init__(self) -> None:
        self._tag_catalog: dict[str, SessionTag] = {}  # Normalized name -> SessionTag
        self._tag_id_index: dict[str, SessionTag] = {}  # tag_id -> SessionTag
        self._session_tags: dict[str, set[str]] = {}  # session_id -> set of normalized tag names

    def register_tag(
        self,
        name: str,
        color: TagColor = TagColor.BLUE,
        category: TagCategory = TagCategory.CUSTOM,
        description: str = "",
        custom_tag_id: str | None = None,
    ) -> SessionTag:
        """Registers a new tag or returns the existing tag with updated attributes."""
        clean_name = name.strip().lstrip("#")
        if not clean_name:
            raise ValueError("Tag name cannot be blank")

        norm_name = clean_name.lower()
        tag_id = custom_tag_id or f"tag-{uuid.uuid4().hex[:8]}"

        tag = SessionTag(
            tag_id=tag_id,
            name=clean_name,
            color=color,
            category=category,
            description=description,
        )

        self._tag_catalog[norm_name] = tag
        self._tag_id_index[tag_id] = tag
        return tag

    def get_tag(self, name_or_id: str) -> SessionTag | None:
        """Retrieves tag by normalized name or ID."""
        norm = name_or_id.strip().lstrip("#").lower()
        if norm in self._tag_catalog:
            return self._tag_catalog[norm]
        return self._tag_id_index.get(name_or_id)

    def list_registered_tags(self) -> list[SessionTag]:
        """Lists all registered tags sorted by name."""
        return sorted(self._tag_catalog.values(), key=lambda t: t.name.lower())

    def tag_session(self, session_id: str, tag_names: list[str]) -> list[SessionTag]:
        """Attaches one or more tags to a session, registering unlisted tags dynamically."""
        assigned: list[SessionTag] = []
        target_set = self._session_tags.setdefault(session_id, set())

        for raw_name in tag_names:
            clean = raw_name.strip().lstrip("#")
            if not clean:
                continue
            norm = clean.lower()
            tag = self._tag_catalog.get(norm)
            if not tag:
                tag = self.register_tag(name=clean, color=TagColor.BLUE, category=TagCategory.CUSTOM)

            target_set.add(norm)
            assigned.append(tag)

        return assigned

    def untag_session(self, session_id: str, tag_name: str) -> bool:
        """Removes a tag association from a session."""
        norm = tag_name.strip().lstrip("#").lower()
        target_set = self._session_tags.get(session_id)
        if target_set and norm in target_set:
            target_set.remove(norm)
            return True
        return False

    def get_session_tags(self, session_id: str) -> list[SessionTag]:
        """Retrieves all tags assigned to a session."""
        norm_names = self._session_tags.get(session_id, set())
        return [self._tag_catalog[n] for n in norm_names if n in self._tag_catalog]

    def filter_sessions(
        self,
        sessions: list[TaggedSessionItem],
        query: SessionFilterQuery,
    ) -> list[TaggedSessionItem]:
        """Filters a candidate session list against multi-dimensional query criteria."""
        filtered: list[TaggedSessionItem] = []
        target_tags = {t.strip().lstrip("#").lower() for t in query.tags if t.strip()}

        for session in sessions:
            # 1. Project filtering
            if query.project_id is not None and session.project_id != query.project_id:
                continue

            # 2. Pinned status filtering
            if query.is_pinned is not None and session.is_pinned != query.is_pinned:
                continue

            # 3. Keyword filtering across title
            if query.keyword:
                kw = query.keyword.strip().lower()
                if kw not in session.title.lower():
                    continue

            # 4. Date range filtering
            if query.created_after is not None and session.created_at < query.created_after:
                continue
            if query.created_before is not None and session.created_at > query.created_before:
                continue

            # 5. Multi-tag boolean matching
            if target_tags:
                session_tag_names = session.get_tag_names()
                if query.match_mode == TagMatchMode.ANY:
                    if not session_tag_names.intersection(target_tags):
                        continue
                elif query.match_mode == TagMatchMode.ALL:
                    if not target_tags.issubset(session_tag_names):
                        continue
                elif query.match_mode == TagMatchMode.EXACT:
                    if session_tag_names != target_tags:
                        continue

            filtered.append(session)

        return filtered

    def auto_suggest_tags_from_text(
        self,
        session_id: str,
        transcript_summary: str,
    ) -> list[AutoTagSuggestion]:
        """Derives autonomous semantic tag recommendations from transcript semantics."""
        suggestions: list[AutoTagSuggestion] = []
        seen_tags: set[str] = set()

        for pattern, tag_name, category, default_color, rationale in _SEMANTIC_RULES:
            matches = pattern.findall(transcript_summary)
            if matches and tag_name not in seen_tags:
                seen_tags.add(tag_name)
                # Compute confidence proportional to match density
                confidence = min(0.99, 0.65 + len(matches) * 0.08)

                # Ensure tag exists in catalog
                if tag_name.lower() not in self._tag_catalog:
                    self.register_tag(
                        name=tag_name,
                        color=default_color,
                        category=category,
                        description=rationale,
                    )

                suggestions.append(
                    AutoTagSuggestion(
                        tag_name=tag_name,
                        confidence=confidence,
                        category=category,
                        reasoning=f"{rationale} (matched '{matches[0]}')",
                    )
                )

        # Return top 3 suggestions sorted by confidence descending
        suggestions.sort(key=lambda s: s.confidence, reverse=True)
        return suggestions[:3]

    def get_tag_distribution(
        self,
        sessions: list[TaggedSessionItem],
    ) -> TagDistribution:
        """Computes aggregate distribution metrics of tag usage across sessions."""
        counts: dict[str, int] = {}
        tagged_sessions_count = 0

        for s in sessions:
            tag_names = s.get_tag_names()
            if tag_names:
                tagged_sessions_count += 1
                for t in tag_names:
                    counts[t] = counts.get(t, 0) + 1

        return TagDistribution(
            tag_counts=counts,
            total_tagged_sessions=tagged_sessions_count,
        )
