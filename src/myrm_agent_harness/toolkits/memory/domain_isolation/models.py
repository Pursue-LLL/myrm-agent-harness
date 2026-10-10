"""Domain models for Connection and Account Domain Isolation.

[INPUT] Work/personal domain declarations, connector account bindings, and security grant requests.
[OUTPUT] ConnectorDomainBinding, DomainGrantConfig, EgressDecision, and DomainRecallFilter.
[POS] Harness framework toolkit memory layer for work-life domain isolation.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

DataDomain = Literal["work", "personal"]


class DomainGrantConfig(BaseModel):
    """Permissions and gate toggles scoped strictly to a specific domain."""

    domain: DataDomain
    allow_write: bool = True
    allow_recall: bool = True
    allow_proactive: bool = True
    allow_egress: bool = False  # By default, outbound channel egress requires explicit grant or confirmation


class ConnectorDomainBinding(BaseModel):
    """User-declared association between an external connector/account and a data domain."""

    connector_id: str
    channel: str = ""
    account_id: str | None = None
    domain: DataDomain = "work"
    created_at: str = ""
    updated_at: str = ""


class DomainRecallFilter(BaseModel):
    """Query parameter defining domain boundaries for memory recall."""

    active_domain: DataDomain = "work"
    allow_cross_domain: bool = False
    agent_id: str | None = None


class EgressDecision(BaseModel):
    """Verdict of domain-scoped egress redline evaluation."""

    allowed: bool
    requires_user_confirmation: bool
    reason: str
    source_domain: DataDomain
    target_channel: str
    is_cross_domain: bool = False
