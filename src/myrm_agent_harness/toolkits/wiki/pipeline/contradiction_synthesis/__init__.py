"""Compile-time contradiction synthesis (CCSP) package.

[INPUT]
- .backlink::apply_synthesis_backlinks (POS: apply backlinks after approval)
- .service::run_contradiction_synthesis_pass (POS: conflict synthesis pass orchestrator)
- .types::SynthesisPassResult (POS: pass result contract)
- .writer::build_evolution_concept_path, parse_synthesis_backlink_targets, synthesis_page_uses_cjk_body (POS: evolution page formatting)

[OUTPUT]
- SynthesisPassResult, apply_synthesis_backlinks, build_evolution_concept_path, parse_synthesis_backlink_targets, run_contradiction_synthesis_pass, synthesis_page_uses_cjk_body

[POS]
矛盾综合分析（CCSP）模块入口。在编译后跨概念检测事实冲突并生成演进比对页面。
"""

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
