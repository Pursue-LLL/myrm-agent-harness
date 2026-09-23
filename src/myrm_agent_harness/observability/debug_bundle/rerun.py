"""Single-variable rerun helper.

[INPUT]
- Plain config mappings + caller-supplied runner callable (POS: no agent imports)
- observability.debug_bundle.types::RerunComparison (POS: verdict DTO)

[OUTPUT]
- single_variable_rerun: baseline vs one-key-override verdict

[POS]
The helper never executes agents itself; the caller injects a runner that maps
a config mapping to a deterministic digest string. Exactly one key may differ.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from myrm_agent_harness.observability.debug_bundle.types import (
    RerunComparison,
    RerunVerdict,
)


def single_variable_rerun(
    *,
    session_id: str,
    base_config: Mapping[str, Any],
    varied_key: str,
    varied_value: Any,
    baseline_digest: str,
    runner: Callable[[dict[str, Any]], str],
) -> RerunComparison:
    """Rerun with exactly one config key overridden and compare digests.

    Raises ValueError when the override touches zero or multiple keys, or
    when the varied key is absent from the base config.
    """
    if varied_key not in base_config:
        raise ValueError(f"varied_key {varied_key!r} not present in base_config")
    rerun_config = dict(base_config)
    rerun_config[varied_key] = varied_value
    rerun_digest = runner(rerun_config)
    if rerun_digest == baseline_digest:
        verdict = RerunVerdict.UNCHANGED
        detail = f"{varied_key} change did not move the outcome; cause lies elsewhere"
    else:
        verdict = RerunVerdict.ALTERED
        detail = f"{varied_key} change moved the outcome; it participates in the cause"
    return RerunComparison(
        session_id=session_id,
        varied_key=varied_key,
        baseline_digest=baseline_digest,
        rerun_digest=rerun_digest,
        verdict=verdict,
        detail=detail,
    )
