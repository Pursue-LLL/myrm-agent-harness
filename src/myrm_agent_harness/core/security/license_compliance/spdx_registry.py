"""SPDX License normalization registry and classifier.

[INPUT]
- Raw license identifiers or text strings from skills, MCP servers, or package manifests.

[OUTPUT]
- Normalized LicenseMetadata instances with accurate RiskTier and copyleft classifications.

[POS]
- Harness security core component providing Single-Source-of-Truth license risk mapping.
"""

from __future__ import annotations

import re
from typing import Final

from myrm_agent_harness.core.security.license_compliance.types import (
    LicenseMetadata,
    LicenseRiskTier,
)

_SPDX_KNOWN_DB: Final[dict[str, LicenseMetadata]] = {
    # Permissive licenses
    "MIT": LicenseMetadata(
        spdx_id="MIT",
        raw_name="MIT License",
        risk_tier=LicenseRiskTier.PERMISSIVE,
        is_copyleft=False,
        commercial_friendly=True,
        description="Short and simple permissive license with attribution requirement.",
    ),
    "APACHE-2.0": LicenseMetadata(
        spdx_id="Apache-2.0",
        raw_name="Apache License 2.0",
        risk_tier=LicenseRiskTier.PERMISSIVE,
        is_copyleft=False,
        commercial_friendly=True,
        description="Permissive license with patent grant and trademark protections.",
    ),
    "BSD-2-CLAUSE": LicenseMetadata(
        spdx_id="BSD-2-Clause",
        raw_name="BSD 2-Clause Simplified License",
        risk_tier=LicenseRiskTier.PERMISSIVE,
        is_copyleft=False,
        commercial_friendly=True,
        description="Permissive license focusing on copyright notices.",
    ),
    "BSD-3-CLAUSE": LicenseMetadata(
        spdx_id="BSD-3-Clause",
        raw_name="BSD 3-Clause Clear/New License",
        risk_tier=LicenseRiskTier.PERMISSIVE,
        is_copyleft=False,
        commercial_friendly=True,
        description="Permissive license with non-endorsement clause.",
    ),
    "ISC": LicenseMetadata(
        spdx_id="ISC",
        raw_name="ISC License",
        risk_tier=LicenseRiskTier.PERMISSIVE,
        is_copyleft=False,
        commercial_friendly=True,
        description="Functionally equivalent to simplified BSD license.",
    ),
    "CC0-1.0": LicenseMetadata(
        spdx_id="CC0-1.0",
        raw_name="Creative Commons Zero v1.0 Universal",
        risk_tier=LicenseRiskTier.PERMISSIVE,
        is_copyleft=False,
        commercial_friendly=True,
        description="Public domain dedication waiver.",
    ),
    # Weak Copyleft licenses
    "MPL-2.0": LicenseMetadata(
        spdx_id="MPL-2.0",
        raw_name="Mozilla Public License 2.0",
        risk_tier=LicenseRiskTier.WEAK_COPYLEFT,
        is_copyleft=True,
        commercial_friendly=True,
        description="File-level weak copyleft allowing commercial binary linking.",
    ),
    "LGPL-2.1": LicenseMetadata(
        spdx_id="LGPL-2.1-only",
        raw_name="GNU Lesser General Public License v2.1",
        risk_tier=LicenseRiskTier.WEAK_COPYLEFT,
        is_copyleft=True,
        commercial_friendly=True,
        description="Lesser copyleft requiring relinking rights for dynamic linking.",
    ),
    "LGPL-3.0": LicenseMetadata(
        spdx_id="LGPL-3.0-only",
        raw_name="GNU Lesser General Public License v3.0",
        risk_tier=LicenseRiskTier.WEAK_COPYLEFT,
        is_copyleft=True,
        commercial_friendly=True,
        description="Lesser copyleft with anti-tivoization and explicit patent rights.",
    ),
    "EPL-2.0": LicenseMetadata(
        spdx_id="EPL-2.0",
        raw_name="Eclipse Public License 2.0",
        risk_tier=LicenseRiskTier.WEAK_COPYLEFT,
        is_copyleft=True,
        commercial_friendly=True,
        description="Weak copyleft license common in Java ecosystems.",
    ),
    # Strong Copyleft licenses (Viral)
    "GPL-2.0": LicenseMetadata(
        spdx_id="GPL-2.0-only",
        raw_name="GNU General Public License v2.0",
        risk_tier=LicenseRiskTier.STRONG_COPYLEFT,
        is_copyleft=True,
        commercial_friendly=False,
        description="Strong copyleft requiring derived works to share source code upon distribution.",
    ),
    "GPL-3.0": LicenseMetadata(
        spdx_id="GPL-3.0-only",
        raw_name="GNU General Public License v3.0",
        risk_tier=LicenseRiskTier.STRONG_COPYLEFT,
        is_copyleft=True,
        commercial_friendly=False,
        description="Strong copyleft with anti-tivoization clauses.",
    ),
    "AGPL-3.0": LicenseMetadata(
        spdx_id="AGPL-3.0-only",
        raw_name="GNU Affero General Public License v3.0",
        risk_tier=LicenseRiskTier.STRONG_COPYLEFT,
        is_copyleft=True,
        commercial_friendly=False,
        description="Viral network copyleft requiring source disclosure over network interaction.",
    ),
    "SSPL-1.0": LicenseMetadata(
        spdx_id="SSPL-1.0",
        raw_name="Server Side Public License v1",
        risk_tier=LicenseRiskTier.STRONG_COPYLEFT,
        is_copyleft=True,
        commercial_friendly=False,
        description="Source-available viral license for commercial service providers.",
    ),
}

_ALIAS_PATTERNS: Final[list[tuple[re.Pattern[str], str]]] = [
    (re.compile(r"^mit$", re.IGNORECASE), "MIT"),
    (re.compile(r"^apache[- ]?(2(\.0)?)?$", re.IGNORECASE), "APACHE-2.0"),
    (re.compile(r"^bsd[- ]?2[- ]?clause$", re.IGNORECASE), "BSD-2-CLAUSE"),
    (re.compile(r"^bsd[- ]?3[- ]?clause$", re.IGNORECASE), "BSD-3-CLAUSE"),
    (re.compile(r"^isc$", re.IGNORECASE), "ISC"),
    (re.compile(r"^cc0([- ]?1(\.0)?)?$", re.IGNORECASE), "CC0-1.0"),
    (re.compile(r"^mpl[- ]?(2(\.0)?)?$", re.IGNORECASE), "MPL-2.0"),
    (re.compile(r"^lgpl[- ]?2(\.1)?", re.IGNORECASE), "LGPL-2.1"),
    (re.compile(r"^lgpl[- ]?3(\.0)?", re.IGNORECASE), "LGPL-3.0"),
    (re.compile(r"^epl[- ]?2(\.0)?", re.IGNORECASE), "EPL-2.0"),
    (re.compile(r"^agpl[- ]?3(\.0)?", re.IGNORECASE), "AGPL-3.0"),
    (re.compile(r"^gpl[- ]?2(\.0)?", re.IGNORECASE), "GPL-2.0"),
    (re.compile(r"^gpl[- ]?3(\.0)?", re.IGNORECASE), "GPL-3.0"),
    (re.compile(r"^sspl", re.IGNORECASE), "SSPL-1.0"),
]


class SpdxLicenseRegistry:
    """Registry for normalizing raw license identifiers and text into canonical SPDX metadata."""

    @classmethod
    def normalize(cls, raw_identifier: str | None) -> LicenseMetadata:
        """Resolve a raw license name, expression, or identifier into LicenseMetadata."""
        if not raw_identifier:
            return LicenseMetadata(
                spdx_id="UNKNOWN",
                raw_name="None/Empty",
                risk_tier=LicenseRiskTier.UNKNOWN,
                is_copyleft=False,
                commercial_friendly=False,
                description="No license identifier provided.",
            )

        trimmed = raw_identifier.strip()
        upper_key = trimmed.upper()

        # Direct database hit
        if upper_key in _SPDX_KNOWN_DB:
            return _SPDX_KNOWN_DB[upper_key]

        # Alias pattern match
        for pattern, canon_key in _ALIAS_PATTERNS:
            if pattern.search(trimmed):
                return _SPDX_KNOWN_DB[canon_key]

        # Proprietary detection
        if re.search(r"\b(commercial|proprietary|all rights reserved)\b", trimmed, re.IGNORECASE):
            return LicenseMetadata(
                spdx_id="PROPRIETARY",
                raw_name=trimmed,
                risk_tier=LicenseRiskTier.PROPRIETARY,
                is_copyleft=False,
                commercial_friendly=False,
                description="Proprietary commercial license requiring explicit terms agreement.",
            )

        return LicenseMetadata(
            spdx_id="UNKNOWN",
            raw_name=trimmed,
            risk_tier=LicenseRiskTier.UNKNOWN,
            is_copyleft=False,
            commercial_friendly=False,
            description=f"Unrecognized license identifier: {trimmed}",
        )
