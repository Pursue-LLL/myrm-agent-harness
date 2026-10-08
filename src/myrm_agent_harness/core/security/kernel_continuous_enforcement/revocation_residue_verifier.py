"""Revocation residue verifier for post-termination sandbox and run audits.

[INPUT]
- .types::RevocationResidueReport
- stdlib collections.abc, datetime, logging

[OUTPUT]
- RevocationResidueVerifier: audits lingering processes, sockets, tmp files, and cached tokens

[POS]
Verification engine based on John Rood's post-revocation testing methodology:
"the fence is the demo; revocation is the product. kill a run, then prove
nothing it kept still works: memory files, cached tokens, and stray processes."
Strictly avoids Any types; enforced under 400 lines limit.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime

from myrm_agent_harness.core.security.kernel_continuous_enforcement.types import (
    RevocationResidueReport,
)

logger = logging.getLogger(__name__)


class RevocationResidueVerifier:
    """Verifies whether execution remnants survive after run or sandbox revocation."""

    def audit_run_residue(
        self,
        run_id: str,
        active_pids: Sequence[int] = (),
        open_sockets: Sequence[str] = (),
        temp_files: Sequence[str] = (),
        cached_tokens: Sequence[str] = (),
    ) -> RevocationResidueReport:
        """Audit post-revocation environment for lingering execution artifacts.

        Args:
            run_id: Unique identifier of the terminated run or sandbox session.
            active_pids: Sequence of process IDs found still running under the cgroup/sandbox.
            open_sockets: Sequence of lingering socket addresses or file descriptors.
            temp_files: Sequence of remaining temporary memory or disk files.
            cached_tokens: Sequence of unevicted credential tokens or session keys.

        Returns:
            RevocationResidueReport detailing cleanliness and surviving artifacts.
        """
        timestamp = datetime.now(UTC).isoformat()
        lingering_pids = tuple(active_pids)
        lingering_sockets = tuple(open_sockets)
        lingering_tmp = tuple(temp_files)
        lingering_tokens = tuple(cached_tokens)

        is_clean = (
            len(lingering_pids) == 0
            and len(lingering_sockets) == 0
            and len(lingering_tmp) == 0
            and len(lingering_tokens) == 0
        )

        if not is_clean:
            logger.warning(
                "REVOCATION RESIDUE DETECTED for run '%s': PIDs=%d, Sockets=%d, TmpFiles=%d, Tokens=%d",
                run_id,
                len(lingering_pids),
                len(lingering_sockets),
                len(lingering_tmp),
                len(lingering_tokens),
            )
        else:
            logger.info("Revocation audit PASSED for run '%s': 0 surviving artifacts", run_id)

        return RevocationResidueReport(
            run_id=run_id,
            timestamp_iso=timestamp,
            lingering_pids=lingering_pids,
            lingering_sockets=lingering_sockets,
            lingering_tmp_files=lingering_tmp,
            lingering_cached_tokens=lingering_tokens,
            is_fully_clean=is_clean,
        )
