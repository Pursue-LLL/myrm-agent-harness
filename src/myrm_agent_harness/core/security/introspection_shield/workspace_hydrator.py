"""
[POS] src/myrm_agent_harness/core/security/introspection_shield/workspace_hydrator.py
[INPUT] logging, pathlib, typing
[OUTPUT] DecoupledWorkspaceHydrator

Implements adaptive hydration and scaffolding for open standards workspace template files:
SOUL.md, USER.md, IDENTITY.md, BOOTSTRAP.md, HEARTBEAT.md.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .types import DecoupledTemplateStandard, HydratedTemplateRecord

logger = logging.getLogger(__name__)

TEMPLATE_MAPPINGS: dict[DecoupledTemplateStandard, tuple[str, ...]] = {
    DecoupledTemplateStandard.SOUL: ("SOUL.md", "soul.md", ".soul.md"),
    DecoupledTemplateStandard.USER: ("USER.md", "user.md", ".user.md"),
    DecoupledTemplateStandard.IDENTITY: ("IDENTITY.md", "identity.md", ".identity.md"),
    DecoupledTemplateStandard.BOOTSTRAP: ("BOOTSTRAP.md", "bootstrap.md", ".bootstrap.md"),
    DecoupledTemplateStandard.HEARTBEAT: ("HEARTBEAT.md", "heartbeat.md", ".heartbeat.md"),
}

DEFAULT_SCAFFOLD_TEMPLATES: dict[DecoupledTemplateStandard, str] = {
    DecoupledTemplateStandard.SOUL: (
        "# SOUL.md - Core Principles & Behavioral Directives\n\n"
        "- Absolute honesty and evidence-based problem solving.\n"
        "- Zero destructive commands without explicit confirmation.\n"
        "- Clean Architecture preservation and local-first data privacy.\n"
    ),
    DecoupledTemplateStandard.USER: (
        "# USER.md - User Persona & Working Preferences\n\n"
        "- Technical context: Full-stack software engineering & systems architecture.\n"
        "- Preferred communication style: Concise, technical, GitHub-flavored markdown.\n"
    ),
    DecoupledTemplateStandard.IDENTITY: (
        "# IDENTITY.md - Digital Coworker Persona\n\n"
        "- Role: Senior Systems Architect & Pair Programming Specialist.\n"
        "- Tone: Professional, thorough, proactive, and resilient.\n"
    ),
    DecoupledTemplateStandard.BOOTSTRAP: (
        "# BOOTSTRAP.md - Cold-Start Environment Healthcheck\n\n"
        "- Verify workspace boundaries and sandbox mount integrity.\n"
        "- Ensure local hardware keychain or ephemeral key store is initialized.\n"
    ),
    DecoupledTemplateStandard.HEARTBEAT: (
        "# HEARTBEAT.md - Periodic Self-Healing & Invariant Probes\n\n"
        "- Validate in-flight task leases and timeout monitors.\n"
        "- Check for memory leak thresholds and sandbox resource quotas.\n"
    ),
}

MAX_TEMPLATE_CHARS: int = 16000


class DecoupledWorkspaceHydrator:
    """Discovers, parses, and scaffolds decoupled workspace template specifications."""

    def __init__(self, max_chars_per_template: int = MAX_TEMPLATE_CHARS) -> None:
        self._max_chars: int = max_chars_per_template

    def hydrate_workspace(
        self,
        workspace_dir: Path,
    ) -> dict[DecoupledTemplateStandard, HydratedTemplateRecord]:
        """Scan workspace root for decoupled standard templates and hydrate them into memory."""
        results: dict[DecoupledTemplateStandard, HydratedTemplateRecord] = {}

        if not workspace_dir.exists() or not workspace_dir.is_dir():
            return results

        for standard, candidates in TEMPLATE_MAPPINGS.items():
            matched_file: Path | None = None
            for candidate in candidates:
                candidate_path = workspace_dir / candidate
                if candidate_path.is_file():
                    matched_file = candidate_path
                    break

            if matched_file is not None:
                try:
                    raw_text = matched_file.read_text(encoding="utf-8")
                    if len(raw_text) > self._max_chars:
                        logger.warning(
                            "Truncating oversized workspace template %s (%d chars)",
                            matched_file.name,
                            len(raw_text),
                        )
                        raw_text = raw_text[: self._max_chars]

                    results[standard] = HydratedTemplateRecord(
                        standard=standard,
                        filename=matched_file.name,
                        content=raw_text,
                        source_path=str(matched_file.resolve()),
                        is_active=True,
                        character_count=len(raw_text),
                    )
                except Exception as exc:
                    logger.error("Failed to read workspace template %s: %s", matched_file, exc)

        return results

    def scaffold_defaults(
        self,
        workspace_dir: Path,
        overwrite: bool = False,
    ) -> list[str]:
        """Generate default starter templates in the workspace directory."""
        workspace_dir.mkdir(parents=True, exist_ok=True)
        created_files: list[str] = []

        for standard, content in DEFAULT_SCAFFOLD_TEMPLATES.items():
            target_file = workspace_dir / f"{standard.value}.md"
            if not target_file.exists() or overwrite:
                target_file.write_text(content, encoding="utf-8")
                created_files.append(str(target_file.name))

        return created_files

    def build_prompt_context(
        self,
        hydrated: dict[DecoupledTemplateStandard, HydratedTemplateRecord],
    ) -> str:
        """Compose all active decoupled templates into a unified structured prompt block."""
        if not hydrated:
            return ""

        sections: list[str] = ["<workspace_standards>"]
        order = (
            DecoupledTemplateStandard.SOUL,
            DecoupledTemplateStandard.IDENTITY,
            DecoupledTemplateStandard.USER,
            DecoupledTemplateStandard.BOOTSTRAP,
            DecoupledTemplateStandard.HEARTBEAT,
        )

        for std in order:
            record = hydrated.get(std)
            if record and record.is_active:
                sections.append(
                    f"<standard type=\"{record.standard.value}\" file=\"{record.filename}\">\n"
                    f"{record.content.strip()}\n"
                    f"</standard>"
                )

        sections.append("</workspace_standards>")
        return "\n\n".join(sections)
