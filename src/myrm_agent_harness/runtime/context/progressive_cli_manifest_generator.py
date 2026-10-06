"""Progressive CLI Capability Manifest Generator conforming to llms.txt standard.

Produces compact, progressive hierarchical listings of hundreds of CLI tools
to allow LLMs to discover available sandbox commands with minimal token footprint.
"""

from __future__ import annotations

from myrm_agent_harness.runtime.context.progressive_cli_manifest_types import (
    CliCapabilityCategory,
    CliCapabilityEntry,
    ManifestFormatConfig,
)


class ProgressiveCliManifestGenerator:
    """Generates tiered and progressive capability manifests for CLI toolkits."""

    def __init__(self) -> None:
        self._entries: dict[str, CliCapabilityEntry] = {}

    def register_entry(self, entry: CliCapabilityEntry) -> None:
        """Register a CLI capability entry."""
        self._entries[entry.name] = entry

    def register_entries(self, entries: list[CliCapabilityEntry]) -> None:
        """Register multiple CLI capability entries."""
        for e in entries:
            self.register_entry(e)

    def get_entry(self, name: str) -> CliCapabilityEntry | None:
        """Fetch a specific capability entry by tool name."""
        return self._entries.get(name)

    def generate_llms_txt(
        self,
        config: ManifestFormatConfig | None = None,
    ) -> str:
        """Render a compact llms.txt format capability catalog."""
        cfg = config or ManifestFormatConfig()
        by_category: dict[CliCapabilityCategory, list[CliCapabilityEntry]] = {}

        for entry in self._entries.values():
            if cfg.include_categories and entry.category not in cfg.include_categories:
                continue
            by_category.setdefault(entry.category, []).append(entry)

        lines: list[str] = [
            "# CLI Capability Manifest (llms.txt standard)",
            "> Lightweight capability index. Use `--dry-run <tool>` or inquiry protocol for full specs.",
            "",
        ]

        for cat in sorted(by_category.keys(), key=lambda c: c.value):
            items = by_category[cat]
            lines.append(f"## {cat.value}")
            sorted_items = sorted(items, key=lambda x: x.name)[: cfg.max_entries_per_category]
            for it in sorted_items:
                tags_str = f" [{','.join(sorted(it.tags))}]" if cfg.render_tags and it.tags else ""
                lines.append(f"- **{it.name}**: {it.short_summary}{tags_str}")
            lines.append("")

        return "\n".join(lines).strip()

    def generate_xml_manifest(
        self,
        config: ManifestFormatConfig | None = None,
    ) -> str:
        """Render a structured XML manifest block for injection into system prompt."""
        cfg = config or ManifestFormatConfig()
        lines: list[str] = ["<cli_capability_manifest>"]

        by_category: dict[CliCapabilityCategory, list[CliCapabilityEntry]] = {}
        for entry in self._entries.values():
            if cfg.include_categories and entry.category not in cfg.include_categories:
                continue
            by_category.setdefault(entry.category, []).append(entry)

        for cat in sorted(by_category.keys(), key=lambda c: c.value):
            lines.append(f'  <category name="{cat.value}">')
            items = sorted(by_category[cat], key=lambda x: x.name)[: cfg.max_entries_per_category]
            for it in items:
                net_attr = ' net="true"' if it.requires_network else ""
                side_attr = ' side_effects="true"' if it.has_side_effects else ""
                lines.append(
                    f'    <tool name="{it.name}"{net_attr}{side_attr}>{it.short_summary}</tool>'
                )
            lines.append("  </category>")

        lines.append("</cli_capability_manifest>")
        return "\n".join(lines)
