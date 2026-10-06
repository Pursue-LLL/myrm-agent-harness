# [POS] toolkits/memory/wiki_memory/wiki_store.py
# [INPUT] pathlib.Path, re, types.WikiMemoryPage, types.WikiScopeLevel, types.WikiLinkRef
# [OUTPUT] MarkdownWikiMemoryStore

"""Markdown-as-SSOT storage manager handling scoped directories and Obsidian link parsing."""

from __future__ import annotations

import contextlib
import re
import time
from pathlib import Path

from .types import WikiLinkRef, WikiMemoryPage, WikiScopeLevel

# Regular expression matching Obsidian wiki links: [[PageName]], [[PageName#Section]], [[PageName|Alias]]
_OBSIDIAN_LINK_PATTERN = re.compile(r"\[\[([^\]|#]+)(?:#([^\]|]+))?(?:\|([^\]]+))?\]\]")


class MarkdownWikiMemoryStore:
    """Manages physical Markdown storage layout across global and profile-scoped tiers."""

    def __init__(self, root_dir: Path) -> None:
        self._root_dir = root_dir
        self._global_dir = root_dir / "global"
        self._agents_dir = root_dir / "agents"
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        """Create global and agents directories if not present."""
        self._global_dir.mkdir(parents=True, exist_ok=True)
        self._agents_dir.mkdir(parents=True, exist_ok=True)

    def resolve_page_path(
        self,
        page_id: str,
        scope: WikiScopeLevel,
        profile_id: str | None = None,
    ) -> Path:
        """Derive the deterministic filesystem path for a memory page."""
        safe_id = re.sub(r"[^\w\-_]", "_", page_id.lower().strip())
        filename = f"{safe_id}.md"

        if scope == WikiScopeLevel.GLOBAL:
            return self._global_dir / filename

        # Scoped to specific agent profile
        pid = profile_id or "default"
        safe_pid = re.sub(r"[^\w\-_]", "_", pid.lower().strip())
        agent_dir = self._agents_dir / safe_pid
        agent_dir.mkdir(parents=True, exist_ok=True)
        return agent_dir / filename

    def save_page(self, page: WikiMemoryPage) -> Path:
        """Serialize and persist memory page to its designated Markdown file."""
        target_path = self.resolve_page_path(
            page_id=page.page_id,
            scope=page.scope,
            profile_id=page.profile_id,
        )

        # 1. Render Markdown with YAML frontmatter
        now = time.time()
        rendered_md = self._render_markdown(
            title=page.title,
            content=page.content,
            scope=page.scope,
            profile_id=page.profile_id,
            tags=page.tags,
            updated_at=now,
            frontmatter=page.frontmatter,
        )

        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(rendered_md, encoding="utf-8")
        return target_path

    def get_page(
        self,
        page_id: str,
        scope: WikiScopeLevel,
        profile_id: str | None = None,
    ) -> WikiMemoryPage | None:
        """Read and deserialize memory page from Markdown file."""
        path = self.resolve_page_path(page_id=page_id, scope=scope, profile_id=profile_id)
        if not path.is_file():
            return None

        text = path.read_text(encoding="utf-8")
        return self._parse_markdown(page_id=page_id, text=text, default_scope=scope, default_profile=profile_id)

    def delete_page(
        self,
        page_id: str,
        scope: WikiScopeLevel,
        profile_id: str | None = None,
    ) -> bool:
        """Remove memory page Markdown file from disk."""
        path = self.resolve_page_path(page_id=page_id, scope=scope, profile_id=profile_id)
        if path.is_file():
            path.unlink()
            return True
        return False

    def list_pages(
        self,
        scope: WikiScopeLevel | None = None,
        profile_id: str | None = None,
    ) -> list[WikiMemoryPage]:
        """Scan and deserialize all Markdown memory pages matching scope."""
        pages: list[WikiMemoryPage] = []

        # 1. Scan global tier
        if (scope is None or scope == WikiScopeLevel.GLOBAL) and self._global_dir.exists():
            for p in self._global_dir.glob("*.md"):
                page = self._parse_markdown(
                    page_id=p.stem,
                    text=p.read_text(encoding="utf-8"),
                    default_scope=WikiScopeLevel.GLOBAL,
                    default_profile=None,
                )
                pages.append(page)

        # 2. Scan agent-scoped tier
        if (scope is None or scope == WikiScopeLevel.AGENT) and self._agents_dir.exists():
            dirs_to_scan = (
                [self._agents_dir / profile_id]
                if profile_id
                else list(self._agents_dir.iterdir())
            )
            for adir in dirs_to_scan:
                if adir.is_dir():
                    for p in adir.glob("*.md"):
                        page = self._parse_markdown(
                            page_id=p.stem,
                            text=p.read_text(encoding="utf-8"),
                            default_scope=WikiScopeLevel.AGENT,
                            default_profile=adir.name,
                        )
                        pages.append(page)

        return pages

    @classmethod
    def extract_links(cls, source_page_id: str, content: str) -> list[WikiLinkRef]:
        """Extract Obsidian-style [[Target#Section|Alias]] links from text."""
        links: list[WikiLinkRef] = []
        for match in _OBSIDIAN_LINK_PATTERN.finditer(content):
            target = match.group(1).strip()
            section = match.group(2).strip() if match.group(2) else None
            alias = match.group(3).strip() if match.group(3) else target
            links.append(
                WikiLinkRef(
                    source_page_id=source_page_id,
                    target_page_title=target,
                    link_text=alias,
                    section=section,
                )
            )
        return links

    @staticmethod
    def _render_markdown(
        title: str,
        content: str,
        scope: WikiScopeLevel,
        profile_id: str | None,
        tags: list[str],
        updated_at: float,
        frontmatter: dict[str, str | int | float | bool],
    ) -> str:
        """Compose valid Markdown string with YAML frontmatter header."""
        lines = [
            "---",
            f"title: {title}",
            f"scope: {scope.value}",
        ]
        if profile_id:
            lines.append(f"profile_id: {profile_id}")
        if tags:
            lines.append(f"tags: [{', '.join(tags)}]")
        lines.append(f"updated_at: {updated_at}")

        for k, v in frontmatter.items():
            if k not in ("title", "scope", "profile_id", "tags", "updated_at"):
                lines.append(f"{k}: {v}")

        lines.append("---")
        lines.append("")
        lines.append(f"# {title}")
        lines.append("")
        lines.append(content.strip())
        lines.append("")
        return "\n".join(lines)

    @classmethod
    def _parse_markdown(
        cls,
        page_id: str,
        text: str,
        default_scope: WikiScopeLevel,
        default_profile: str | None,
    ) -> WikiMemoryPage:
        """Parse YAML frontmatter and body from Markdown text."""
        title = page_id
        scope = default_scope
        profile_id = default_profile
        tags: list[str] = []
        updated_at = time.time()
        frontmatter: dict[str, str | int | float | bool] = {}
        content = text

        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                raw_fm = parts[1].strip()
                content = parts[2].strip()
                for line in raw_fm.splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        key = k.strip()
                        val = v.strip()
                        if key == "title":
                            title = val
                        elif key == "scope":
                            scope = WikiScopeLevel(val) if val in ("global", "agent") else default_scope
                        elif key == "profile_id":
                            profile_id = val
                        elif key == "tags":
                            clean_tags = val.strip("[]")
                            tags = [t.strip() for t in clean_tags.split(",") if t.strip()]
                        elif key == "updated_at":
                            with contextlib.suppress(ValueError):
                                updated_at = float(val)
                        else:
                            frontmatter[key] = val

        # Strip initial h1 if identical to title
        if content.startswith(f"# {title}"):
            content = content[len(f"# {title}") :].strip()

        links = cls.extract_links(page_id, content)

        return WikiMemoryPage(
            page_id=page_id,
            title=title,
            content=content,
            scope=scope,
            profile_id=profile_id,
            tags=tags,
            links=links,
            frontmatter=frontmatter,
            updated_at=updated_at,
        )
