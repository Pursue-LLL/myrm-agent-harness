"""Type contracts and models for Clean Markdown Extractor and Context Sparsity Pruning Suite.

Defines DOM pruning categories, extracted clean content representations,
and spatiotemporal sparsity pruning result contracts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import time


class DOMPruneRule(StrEnum):
    """Categorical DOM element classes targeted for preemptive physical excision."""

    SCRIPTS_AND_STYLES = "scripts_and_styles"  # <script>, <style>, <noscript>
    SVG_VECTOR_GARBAGE = "svg_vector_garbage"  # <svg>, <path d="...">, inline icon bloat
    NAVIGATION_FOOTERS = "navigation_footers"  # <nav>, <footer>, <aside>, <header>
    AD_BANNERS = "ad_banners"  # Elements with class/id matching ad/banner/promo
    INLINE_BASE64 = "inline_base64"  # Data URIs with multi-kilobyte base64 payloads


class ExtractionDensityLevel(StrEnum):
    """Density level governing the output Markdown purity."""

    CONCISE_OUTLINE = "concise_outline"  # Skeleton titles and bullet anchors only
    NORMAL_MARKDOWN = "normal_markdown"  # Standard readable content with links
    HIGH_DENSITY_PURIFIED = "high_density_purified"  # Stripped of all fluff, dense facts only


@dataclass(frozen=True)
class ExtractedCleanContent:
    """Telemetry and purified textual payload extracted from raw unwashed HTML."""

    source_url_or_id: str
    title: str
    clean_markdown: str
    raw_char_count: int
    clean_char_count: int
    compression_ratio: float
    tokens_saved: int
    duration_ms: float
    extracted_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class SparsityPruneResult:
    """Telemetry report emitted after applying spatiotemporal sparsity pruning on long documents."""

    original_tokens: int
    pruned_tokens: int
    active_sections_kept: int
    folded_sections_count: int
    sparse_markdown: str
    tokens_saved: int
    savings_ratio: float


@dataclass(frozen=True)
class CleanMarkdownExtractorConfig:
    """Configuration governing DOM purification and context sparsity thresholds."""

    strip_svg: bool = True
    strip_nav_footer: bool = True
    strip_inline_images: bool = True
    strip_scripts_styles: bool = True
    max_sparsity_budget_tokens: int = 4000
    bytes_per_token_estimate: float = 4.0
