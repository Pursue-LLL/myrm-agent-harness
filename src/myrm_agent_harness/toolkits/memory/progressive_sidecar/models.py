"""[POS]: src/myrm_agent_harness/toolkits/memory/progressive_sidecar/models.py
[INPUT]: Text payloads, tier specifications, and Open Knowledge Format (OKF) metadata.
[OUTPUT]: Strongly typed contracts for L0/L1/L2 context tiers, OKF frontmatter, and sidecar bundles.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class ContextTier(StrEnum):
    """Progressive context disclosure granularity tiers."""

    L0_ABSTRACT = "l0_abstract"
    L1_OVERVIEW = "l1_overview"
    L2_DETAIL = "l2_detail"


class OKFFrontmatter(BaseModel):
    """Open Knowledge Format structured frontmatter metadata."""

    doc_id: str = Field(..., description="Canonical document or memory identifier")
    title: str = Field(default="", description="Document title or section label")
    digest_sha256: str = Field(..., description="SHA-256 fingerprint of L2 raw content")
    l0_tokens_est: int = Field(default=0, ge=0, description="Estimated token size of L0 abstract")
    l1_tokens_est: int = Field(default=0, ge=0, description="Estimated token size of L1 overview")
    l2_tokens_est: int = Field(default=0, ge=0, description="Estimated token size of L2 raw content")
    updated_at_epoch: float = Field(..., description="Update epoch timestamp in seconds")


class SidecarDescriptor(BaseModel):
    """Descriptor for a single companion sidecar file."""

    tier: ContextTier = Field(..., description="Target context granularity tier")
    suffix: str = Field(..., description="Canonical sidecar filename suffix")
    content: str = Field(..., description="Rendered text payload of the sidecar")
    token_est: int = Field(default=0, ge=0, description="Estimated token count")


class ProgressiveContextBundle(BaseModel):
    """Complete three-tier context bundle comprising L0, L1, and L2 layers."""

    doc_id: str = Field(..., description="Document identifier")
    frontmatter: OKFFrontmatter = Field(..., description="Structured OKF metadata header")
    l0_abstract: str = Field(..., description="L0 ultra-compact abstract (~100 tokens)")
    l1_overview: str = Field(..., description="L1 structural skeleton and key contracts (~2k tokens)")
    l2_detail: str = Field(..., description="L2 full verbatim body")
    token_savings_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="Estimated token savings percentage")


class ProgressiveReadRequest(BaseModel):
    """Request to read context at specified granularity tier."""

    uri: str = Field(..., description="Target document canonical URI")
    tier: ContextTier = Field(default=ContextTier.L0_ABSTRACT, description="Desired granularity tier")


class ProgressiveReadResult(BaseModel):
    """Deterministic read response for requested context tier."""

    uri: str = Field(..., description="Target document canonical URI")
    tier: ContextTier = Field(..., description="Delivered granularity tier")
    content: str = Field(..., description="Delivered content payload")
    token_est: int = Field(default=0, ge=0, description="Estimated token count")
    has_higher_detail: bool = Field(default=True, description="Whether higher detail tiers are available")
