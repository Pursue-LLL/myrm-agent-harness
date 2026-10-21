"""
[POS] src/myrm_agent_harness/core/security/assignment_sweep/types.py
[INPUT] enum, typing, pydantic
[OUTPUT] AssignmentKeyFamily, AssignmentFormat, AssignmentSweepVerdict,
         AssignmentSweepFinding, AssignmentSweepReport, DatabaseUrlAuditResult
Domain types for Quoted-Key and Separator-Prefix Secret Assignment Sweep Hardening.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class AssignmentKeyFamily(StrEnum):
    """Categorization of sensitive credential key family."""

    PASSWORD = "password"
    API_KEY = "api_key"
    SECRET = "secret"
    TOKEN = "token"
    CREDENTIAL = "credential"
    DATABASE_URL = "database_url"


class AssignmentFormat(StrEnum):
    """Syntactic notation used in credential assignment."""

    QUOTED_JSON = "quoted_json"
    ENV_ASSIGNMENT = "env_assignment"
    ENV_BRACKET = "env_bracket"
    COLON_ASSIGNMENT = "colon_assignment"
    EQUALS_ASSIGNMENT = "equals_assignment"
    DATABASE_DSN = "database_dsn"


class AssignmentSweepVerdict(StrEnum):
    """Overall outcome of scanning text or configuration."""

    CLEAN = "clean"
    SUSPECTED_LEAK = "suspected_leak"
    EXEMPTED_LOCAL_DEV = "exempted_local_dev"


class AssignmentSweepFinding(BaseModel):
    """Individual sensitive assignment detected in content."""

    key_name: str = Field(..., description="Matched credential key or identifier")
    key_family: AssignmentKeyFamily = Field(..., description="Classification of credential key")
    raw_matched_line: str = Field(..., description="Sanitized source line or context containing match")
    value_preview: str = Field(..., description="Masked or truncated preview of assigned value")
    format_kind: AssignmentFormat = Field(..., description="Syntactic pattern detected")
    is_exempt: bool = Field(default=False, description="Whether this finding is exempted (e.g. local dev DSN)")
    exemption_reason: str | None = Field(default=None, description="Explanation for exemption if applicable")


class DatabaseUrlAuditResult(BaseModel):
    """Detailed compliance and risk assessment for a database connection URL."""

    raw_url: str = Field(..., description="Masked or original database URL")
    scheme: str = Field(..., description="Database protocol scheme, e.g. postgres, mysql, mongodb")
    host: str = Field(..., description="Extracted target host or domain")
    user: str = Field(..., description="Extracted username credential")
    is_loopback: bool = Field(..., description="Whether host is loopback (localhost or 127.0.0.1)")
    is_default_credential: bool = Field(..., description="Whether credentials match standard development defaults")
    is_exempt: bool = Field(..., description="Whether URL is exempted from leak blocking")
    audit_reason: str = Field(..., description="Detailed rationale of classification and risk verdict")


class AssignmentSweepReport(BaseModel):
    """Comprehensive sweep audit report evaluating text content or config files."""

    total_lines_scanned: int = Field(default=0, ge=0, description="Number of text lines processed")
    findings: list[AssignmentSweepFinding] = Field(default_factory=list, description="List of detected findings")
    verdict: AssignmentSweepVerdict = Field(default=AssignmentSweepVerdict.CLEAN, description="Aggregated risk verdict")
    active_leaks_count: int = Field(default=0, ge=0, description="Count of non-exempt active leaks detected")
    exempted_count: int = Field(default=0, ge=0, description="Count of legitimately exempted local dev items")
