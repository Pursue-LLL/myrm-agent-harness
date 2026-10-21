"""[INPUT]
- ScratchpadDraft: In-memory lightweight scratchpad model
- PromotionConfig: Options controlling promotion behavior

[OUTPUT]
- ProjectSeed: Structured project seed blueprint for persistence
- ScratchpadPromotionEngine: Core transformation engine converting scratchpad drafts to project seeds

[POS]
Harness framework layer scratchpad promotion engine.
Transforms transient scratchpad drafts into full-scale project seed blueprints.
Strictly decoupled from business persistence logic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class ScratchpadDraft:
    title: str
    content: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    temporary_tags: list[str] = field(default_factory=list)
    referenced_uris: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PromotionConfig:
    target_project_name: str | None = None
    init_readme: bool = True
    init_wiki_structure: bool = True
    default_branch: str = "main"


@dataclass(slots=True)
class SeedDocument:
    relative_path: str
    content: str


@dataclass(slots=True)
class ProjectSeed:
    project_name: str
    description: str
    seeded_documents: list[SeedDocument]
    initial_context_prompt: str
    provenance_metadata: dict[str, str] = field(default_factory=dict)


class ScratchpadPromotionEngine:
    """Transforms transient in-memory scratchpads into structured project seed blueprints."""

    @classmethod
    def compile_seed(
        cls,
        draft: ScratchpadDraft,
        config: PromotionConfig | None = None,
    ) -> ProjectSeed:
        cfg = config or PromotionConfig()

        project_name = cfg.target_project_name or cls._derive_project_name(draft.title, draft.content)
        description = cls._extract_summary(draft.content)

        docs: list[SeedDocument] = []

        # 1. Main scratchpad archival document
        docs.append(
            SeedDocument(
                relative_path="docs/scratchpad_origin.md",
                content=(
                    f"# Original Scratchpad: {draft.title}\n\n"
                    f"- Promoted At: {datetime.now(timezone.utc).isoformat()}\n"
                    f"- Tags: {', '.join(draft.temporary_tags) if draft.temporary_tags else 'None'}\n\n"
                    f"## Content\n\n{draft.content}\n"
                ),
            )
        )

        # 2. Project README if requested
        if cfg.init_readme:
            docs.append(
                SeedDocument(
                    relative_path="README.md",
                    content=(
                        f"# {project_name}\n\n"
                        f"{description}\n\n"
                        f"## Overview\n"
                        f"This project was promoted from a quick scratchpad session to support long-running development.\n\n"
                        f"## Artifacts\n"
                        f"- See `docs/scratchpad_origin.md` for historical brainstorming.\n"
                    ),
                )
            )

        # 3. Compile immutable initial context prompt
        context_prompt = (
            f"<!-- PROJECT_PROMOTED_FROM_SCRATCHPAD -->\n"
            f"<promoted_project name=\"{project_name}\">\n"
            f"  <origin_summary>{description}</origin_summary>\n"
            f"  <key_content>\n{draft.content[:1500]}\n  </key_content>\n"
            f"</promoted_project>"
        )

        provenance = {
            "source": "scratchpad",
            "promoted_at": datetime.now(timezone.utc).isoformat(),
            "original_title": draft.title,
        }

        return ProjectSeed(
            project_name=project_name,
            description=description,
            seeded_documents=docs,
            initial_context_prompt=context_prompt,
            provenance_metadata=provenance,
        )

    @classmethod
    def _derive_project_name(cls, raw_title: str, content: str) -> str:
        clean_title = re.sub(r"[^\w\s-]", "", raw_title).strip()
        if clean_title:
            return "-".join(clean_title.split()[:5]).lower()

        # Fallback from first line of content
        first_line = content.strip().split("\n")[0] if content.strip() else "scratchpad-project"
        clean_first = re.sub(r"[^\w\s-]", "", first_line).strip()
        words = clean_first.split()[:4]
        return "-".join(words).lower() if words else "scratchpad-project"

    @classmethod
    def _extract_summary(cls, content: str) -> str:
        lines = [line.strip() for line in content.strip().split("\n") if line.strip()]
        if not lines:
            return "Promoted project from scratchpad."
        summary = lines[0]
        if len(summary) > 120:
            return summary[:117] + "..."
        return summary
