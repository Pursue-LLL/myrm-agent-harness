"""Unified Multi-Dimension At-Symbol Context Resolver and Snapshot Ingestion Hub.

Parses rich @ notation references (@file, @session, @agent, @doc, @artifact),
extracts L0/L1 adaptive compressed snapshots to prevent context explosion,
and synthesizes structured XML context injection blocks with UI citation metadata.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import ClassVar

from myrm_agent_harness.runtime.context.multi_dimension_at_resolver_types import (
    AtContextIngestionResult,
    AtReferenceKind,
    ParsedAtReference,
    ResolvedAtResource,
    SnapshotDetailLevel,
)

__all__ = [
    "AtContextIngestionResult",
    "AtReferenceKind",
    "MultiDimensionAtSyntaxParser",
    "ParsedAtReference",
    "ResolvedAtResource",
    "SnapshotCompressor",
    "SnapshotDetailLevel",
    "UnifiedMultiDimensionAtResolver",
]


class MultiDimensionAtSyntaxParser:
    """Parses @ references spanning file, session, agent, doc, and artifact dimensions."""

    # Explicit schema match: @kind:target_id
    _EXPLICIT_REGEX: ClassVar[re.Pattern[str]] = re.compile(
        r"@(?P<kind>file|session|agent|doc|artifact):(?P<target>[^\s,，;；\(\)\[\]]+)",
        re.IGNORECASE,
    )

    # Shorthand path match: @/path/to/file or @relative/path.py
    _SHORTHAND_FILE_REGEX: ClassVar[re.Pattern[str]] = re.compile(
        r"@(?P<target>(?:[a-zA-Z0-9_\-\.]+/)+[a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+)",
    )

    @classmethod
    def parse_references(cls, prompt: str) -> tuple[str, tuple[ParsedAtReference, ...]]:
        """Extracts parsed reference spans and cleans prompt text."""
        references: list[ParsedAtReference] = []
        trailing_puncts = ".,:;!?'\"”’。，；！？"

        # 1. Parse explicit syntax
        for match in cls._EXPLICIT_REGEX.finditer(prompt):
            kind_str = match.group("kind").lower()
            target = match.group("target").strip()
            stripped_target = target.rstrip(trailing_puncts)
            if not stripped_target:
                continue
            trimmed_len = len(target) - len(stripped_target)
            raw = match.group(0)
            end_idx = match.end() - trimmed_len if trimmed_len > 0 else match.end()
            raw_match = raw[:-trimmed_len] if trimmed_len > 0 else raw

            references.append(
                ParsedAtReference(
                    raw_match=raw_match,
                    kind=AtReferenceKind(kind_str),
                    target_identifier=stripped_target,
                    start_index=match.start(),
                    end_index=end_idx,
                )
            )

        # 2. Parse shorthand file path references (avoid duplicate overlapping spans)
        for match in cls._SHORTHAND_FILE_REGEX.finditer(prompt):
            span = (match.start(), match.end())
            if not any(r.start_index <= span[0] and span[1] <= r.end_index for r in references):
                target = match.group("target").strip()
                stripped_target = target.rstrip(trailing_puncts)
                if not stripped_target:
                    continue
                trimmed_len = len(target) - len(stripped_target)
                raw = match.group(0)
                end_idx = match.end() - trimmed_len if trimmed_len > 0 else match.end()
                raw_match = raw[:-trimmed_len] if trimmed_len > 0 else raw

                references.append(
                    ParsedAtReference(
                        raw_match=raw_match,
                        kind=AtReferenceKind.FILE,
                        target_identifier=stripped_target,
                        start_index=match.start(),
                        end_index=end_idx,
                    )
                )

        references.sort(key=lambda r: r.start_index)
        cleaned_prompt = prompt.strip()
        return cleaned_prompt, tuple(references)


class SnapshotCompressor:
    """Compresses resource payloads into L0 skeleton or L1 structured summaries."""

    @classmethod
    def compress_resource(
        cls,
        *,
        title: str,
        full_content: str,
        detail_level: SnapshotDetailLevel,
        max_tokens: int = 300,
    ) -> tuple[str, int]:
        """Produces adaptive snippet avoiding context explosion."""
        if detail_level == SnapshotDetailLevel.FULL_PASS:
            tokens = max(len(full_content) // 4, 1)
            return full_content, tokens

        if detail_level == SnapshotDetailLevel.L0_SKELETON:
            first_line = full_content.strip().split("\n")[0]
            summary = f"[{title}] {first_line[:120]}..."
            tokens = max(len(summary) // 4, 1)
            return summary, tokens

        # L1_STRUCTURED: extract key structural summary within max_tokens budget
        lines = [line.strip() for line in full_content.strip().split("\n") if line.strip()]
        max_chars = max(max_tokens * 4, 16)
        bullet_points: list[str] = []
        char_count = 0

        for line in lines[:15]:
            formatted_line = f"- {line}"
            projected_len = char_count + len(formatted_line) + (1 if bullet_points else 0)
            if projected_len > max_chars:
                if not bullet_points:
                    bullet_points.append(formatted_line[:max_chars])
                else:
                    bullet_points.append("...")
                break
            bullet_points.append(formatted_line)
            char_count = projected_len

        snippet = "\n".join(bullet_points)
        tokens = max(len(snippet) // 4, 1)
        return snippet, min(tokens, max_tokens)


class UnifiedMultiDimensionAtResolver:
    """Orchestrates multi-dimensional @ resolution and prompt XML hydration."""

    @classmethod
    def resolve_and_ingest(
        cls,
        *,
        prompt: str,
        resource_loader: Callable[[AtReferenceKind, str], tuple[str, str]],
        default_level: SnapshotDetailLevel = SnapshotDetailLevel.L1_STRUCTURED,
    ) -> AtContextIngestionResult:
        """Parses @ tokens, loads resources, compresses snapshots, and builds context XML."""
        cleaned_prompt, parsed_refs = MultiDimensionAtSyntaxParser.parse_references(prompt)

        resolved_resources: list[ResolvedAtResource] = []
        total_tokens = 0
        xml_blocks: list[str] = ['<at_references_context version="1.0">']

        for ref in parsed_refs:
            try:
                title, content = resource_loader(ref.kind, ref.target_identifier)
            except Exception as exc:
                title, content = f"Unresolved {ref.kind}:{ref.target_identifier}", f"Error: {exc}"

            snippet, tokens = SnapshotCompressor.compress_resource(
                title=title,
                full_content=content,
                detail_level=default_level,
            )
            total_tokens += tokens

            badge_label = f"[{ref.kind.capitalize()}: {ref.target_identifier}]"
            resolved_resources.append(
                ResolvedAtResource(
                    kind=ref.kind,
                    target_identifier=ref.target_identifier,
                    title=title,
                    detail_level=default_level,
                    snippet=snippet,
                    token_estimate=tokens,
                    badge_label=badge_label,
                    uri_or_path=ref.target_identifier,
                )
            )

            xml_blocks.append(
                f'  <reference kind="{ref.kind}" target="{ref.target_identifier}" level="{default_level}" title="{title}">'
            )
            xml_blocks.append(f"    {snippet}")
            xml_blocks.append("  </reference>")

        xml_blocks.append("</at_references_context>")
        context_xml = "\n".join(xml_blocks)

        return AtContextIngestionResult(
            cleaned_prompt=cleaned_prompt,
            references=tuple(resolved_resources),
            injected_context_xml=context_xml,
            total_tokens_consumed=total_tokens,
        )
