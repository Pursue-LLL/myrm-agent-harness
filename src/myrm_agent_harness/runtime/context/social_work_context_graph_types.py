"""Data contracts for Social Collaboration Graph and Cross-Application Work Context."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PersonRoleKind(StrEnum):
    """Organizational collaboration and decision role classifications."""

    LEADER = "leader"
    DECISION_MAKER = "decision_maker"
    REVIEWER = "reviewer"
    CONTRIBUTOR = "contributor"
    EXTERNAL_STAKEHOLDER = "external_stakeholder"


class WorkAssetKind(StrEnum):
    """Categorization of work artifacts spanning multiple applications."""

    DOCUMENT = "document"
    CODE_FILE = "code_file"
    CHAT_MESSAGE = "chat_message"
    ISSUE_OR_TICKET = "issue_or_ticket"


@dataclass(frozen=True)
class PersonEntity:
    """Team collaborator persona with aliases, role authority, and department."""

    person_id: str
    name: str
    aliases: tuple[str, ...]
    title: str
    role_kind: PersonRoleKind
    department: str


@dataclass(frozen=True)
class CrossAppWorkAsset:
    """Work artifact spanning local files, chat threads, PRs, and wiki docs."""

    asset_id: str
    title: str
    path_or_uri: str
    kind: WorkAssetKind
    created_by_person_id: str
    timestamp_epoch_s: float
    semantic_summary: str


@dataclass(frozen=True)
class FuzzyQueryIntent:
    """Parsed intention for fuzzy multi-source asset and decision retrieval."""

    mention_person: str | None
    time_hint: str | None
    keyword_hints: tuple[str, ...]


@dataclass(frozen=True)
class ResolvedContextAnchor:
    """Multi-dimensional contextual anchor linking person, temporal span, and assets."""

    matched_person: PersonEntity | None
    matched_assets: tuple[CrossAppWorkAsset, ...]
    confidence_score: float
    explanation: str


@dataclass(frozen=True)
class PrivacyAuditRecord:
    """Transparent audit log entry for privacy boundary and access enforcement."""

    access_id: str
    action: str
    queried_target: str
    is_authorized: bool
    timestamp_utc: str
