"""Compile-time contradiction synthesis (CCSP) package."""

from .backlink import apply_synthesis_backlinks
from .service import run_contradiction_synthesis_pass
from .types import SynthesisPassResult
from .writer import build_evolution_concept_path, parse_synthesis_backlink_targets, synthesis_page_uses_cjk_body

__all__ = [
    "SynthesisPassResult",
    "apply_synthesis_backlinks",
    "build_evolution_concept_path",
    "parse_synthesis_backlink_targets",
    "run_contradiction_synthesis_pass",
    "synthesis_page_uses_cjk_body",
]
