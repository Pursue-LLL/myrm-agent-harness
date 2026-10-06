"""Cross-collaborator and cross-agent 'Big @' session reference & context borrowing bridge.

[INPUT]
- utils.text_utils::get_token_count, truncate_text_to_tokens (POS: Token estimation)

[OUTPUT]
- BigAtTargetKind: Target reference classification (session, collaborator, agent)
- BigAtReference: Parsed deep reference token and associated directive
- DistilledSessionContext: Distilled factual findings, rejections, conclusions, anchors
- ContextBorrowingConfig: Token budget and field limits for context hydration
- BigAtSyntaxParser: Robust syntax scanner and text normalizer
- ZeroExplanationContextExtractor: Distills technical essence from session turns
- ContextBorrowingBridge: Hydrates distilled contexts into tight model context blocks

[POS]
Harness runtime context layer. Bridges cross-discipline sessions via 'Big @' syntax,
eliminating manual translation friction without context window bloat.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from myrm_agent_harness.utils.text_utils import (
    get_token_count,
    truncate_text_to_tokens,
)

_DEFAULT_MAX_BORROWED_TOKENS: Final[int] = 1200
_DEFAULT_MAX_FINDINGS: Final[int] = 6
_DEFAULT_MAX_CONCLUSIONS: Final[int] = 6
_DEFAULT_MAX_ANCHORS: Final[int] = 8

# Matches @session:id, @collab:user/session, @agent:id/session, or @user/session
_BIG_AT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"@(?P<type>session|collab|collaborator|agent):(?P<target>[a-zA-Z0-9_\-\./]+)|"
    r"@(?P<shorthand>[a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-]+)",
    re.IGNORECASE,
)


class BigAtTargetKind(StrEnum):
    """Classification of referenced collaborator context target."""

    SESSION = "session"
    COLLABORATOR = "collaborator"
    AGENT = "agent"


@dataclass(slots=True, frozen=True)
class BigAtReference:
    """Parsed 'Big @' reference descriptor extracted from user prompt."""

    raw_token: str
    target_kind: BigAtTargetKind
    primary_identifier: str
    secondary_identifier: str | None = None


@dataclass(slots=True, frozen=True)
class DistilledSessionContext:
    """Distilled technical essence from a referenced collaborator session."""

    source_session_id: str
    title: str
    core_goal: str
    fact_findings: list[str] = field(default_factory=list)
    rejected_attempts: list[str] = field(default_factory=list)
    accepted_conclusions: list[str] = field(default_factory=list)
    code_anchors: list[str] = field(default_factory=list)
    key_artifact_ids: list[str] = field(default_factory=list)
    estimated_tokens: int = 0


@dataclass(slots=True, frozen=True)
class ContextBorrowingConfig:
    """Configuration governing borrowed context distillation and prompt injection."""

    max_borrowed_tokens: int = _DEFAULT_MAX_BORROWED_TOKENS
    max_findings: int = _DEFAULT_MAX_FINDINGS
    max_conclusions: int = _DEFAULT_MAX_CONCLUSIONS
    max_anchors: int = _DEFAULT_MAX_ANCHORS


class BigAtSyntaxParser:
    """Parser detecting and extracting 'Big @' session references from user inputs."""

    @classmethod
    def parse_references(cls, text: str) -> list[BigAtReference]:
        """Scan input text and return structured reference tokens."""
        if not text:
            return []

        references: list[BigAtReference] = []
        for match in _BIG_AT_PATTERN.finditer(text):
            raw_token = match.group(0)
            target_type = match.group("type")
            target_val = match.group("target")
            shorthand = match.group("shorthand")

            if shorthand:
                parts = shorthand.split("/", 1)
                references.append(
                    BigAtReference(
                        raw_token=raw_token,
                        target_kind=BigAtTargetKind.COLLABORATOR,
                        primary_identifier=parts[0],
                        secondary_identifier=parts[1],
                    )
                )
                continue

            if not target_type or not target_val:
                continue

            norm_type = target_type.lower()
            if norm_type in ("collab", "collaborator"):
                kind = BigAtTargetKind.COLLABORATOR
                parts = target_val.split("/", 1)
                primary = parts[0]
                secondary = parts[1] if len(parts) > 1 else None
            elif norm_type == "agent":
                kind = BigAtTargetKind.AGENT
                parts = target_val.split("/", 1)
                primary = parts[0]
                secondary = parts[1] if len(parts) > 1 else None
            else:
                kind = BigAtTargetKind.SESSION
                primary = target_val
                secondary = None

            references.append(
                BigAtReference(
                    raw_token=raw_token,
                    target_kind=kind,
                    primary_identifier=primary,
                    secondary_identifier=secondary,
                )
            )

        return references

    @classmethod
    def strip_references(cls, text: str) -> str:
        """Strip 'Big @' tokens to extract clean natural language directives."""
        if not text:
            return ""
        cleaned = _BIG_AT_PATTERN.sub("", text)
        return re.sub(r"\s+", " ", cleaned).strip()


class ZeroExplanationContextExtractor:
    """Distiller converting raw turns into high-density technical context."""

    @classmethod
    def distill(
        cls,
        source_session_id: str,
        title: str,
        core_goal: str,
        fact_findings: Sequence[str],
        rejected_attempts: Sequence[str],
        accepted_conclusions: Sequence[str],
        code_anchors: Sequence[str],
        key_artifact_ids: Sequence[str] = (),
        config: ContextBorrowingConfig | None = None,
    ) -> DistilledSessionContext:
        """Create bounded distilled session essence adhering to field limits."""
        cfg = config or ContextBorrowingConfig()

        bounded_findings = list(fact_findings[: cfg.max_findings])
        bounded_rejections = list(rejected_attempts)
        bounded_conclusions = list(accepted_conclusions[: cfg.max_conclusions])
        bounded_anchors = list(code_anchors[: cfg.max_anchors])
        artifacts = list(key_artifact_ids)

        # Estimate tokens
        text_repr = (
            f"{title} {core_goal} "
            + " ".join(bounded_findings)
            + " ".join(bounded_rejections)
            + " ".join(bounded_conclusions)
            + " ".join(bounded_anchors)
        )
        tokens_est = get_token_count(text_repr)

        return DistilledSessionContext(
            source_session_id=source_session_id,
            title=title,
            core_goal=core_goal,
            fact_findings=bounded_findings,
            rejected_attempts=bounded_rejections,
            accepted_conclusions=bounded_conclusions,
            code_anchors=bounded_anchors,
            key_artifact_ids=artifacts,
            estimated_tokens=tokens_est,
        )


class ContextBorrowingBridge:
    """Hydrates distilled collaborator contexts into model-ready context prompt blocks."""

    def __init__(self, config: ContextBorrowingConfig | None = None) -> None:
        self.config = config or ContextBorrowingConfig()

    def hydrate_context_block(
        self,
        borrowed_contexts: Sequence[DistilledSessionContext],
    ) -> str:
        """Render distilled contexts into a structured XML-like context block.

        Adheres strictly to configured max_borrowed_tokens.
        """
        if not borrowed_contexts:
            return ""

        sections: list[str] = []
        for ctx in borrowed_contexts:
            lines: list[str] = [
                f'  <session source_id="{ctx.source_session_id}" title="{ctx.title}">',
                f"    <core_goal>{ctx.core_goal}</core_goal>",
            ]

            if ctx.code_anchors:
                anchors_str = ", ".join(ctx.code_anchors)
                lines.append(f"    <code_anchors>{anchors_str}</code_anchors>")

            if ctx.fact_findings:
                lines.append("    <verified_findings>")
                for item in ctx.fact_findings:
                    lines.append(f"      - {item}")
                lines.append("    </verified_findings>")

            if ctx.rejected_attempts:
                lines.append("    <rejected_approaches>")
                for item in ctx.rejected_attempts:
                    lines.append(f"      - {item}")
                lines.append("    </rejected_approaches>")

            if ctx.accepted_conclusions:
                lines.append("    <accepted_decisions>")
                for item in ctx.accepted_conclusions:
                    lines.append(f"      - {item}")
                lines.append("    </accepted_decisions>")

            if ctx.key_artifact_ids:
                art_str = ", ".join(ctx.key_artifact_ids)
                lines.append(f"    <artifacts>{art_str}</artifacts>")

            lines.append("  </session>")
            sections.append("\n".join(lines))

        inner_body = "\n".join(sections)
        header = (
            "<borrowed_cross_session_context>\n"
            "<!-- The following distilled facts, rejected attempts, and verified conclusions -->\n"
            "<!-- were directly borrowed from peer collaborator sessions. Use them without re-asking. -->\n"
        )
        footer = "\n</borrowed_cross_session_context>"

        raw_block = f"{header}{inner_body}{footer}"

        # Guard token budget
        block_tokens = get_token_count(raw_block)
        if block_tokens > self.config.max_borrowed_tokens:
            return truncate_text_to_tokens(raw_block, self.config.max_borrowed_tokens)

        return raw_block
