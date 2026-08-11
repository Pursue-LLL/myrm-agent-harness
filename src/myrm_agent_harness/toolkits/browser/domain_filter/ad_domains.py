"""Built-in ad/tracker domain blocklist for ResourceBlockConfig.block_ad_domains.

Source: Peter Lowe's ad and tracking server list https://pgl.yoyo.org/adservers/

[INPUT]
- importlib.resources (POS: bundled asset loader for ``assets/ad_domains.txt``)

[OUTPUT]
- load_ad_domains: cached loader returning frozenset[str]
- AD_DOMAINS: frozenset[str] — module-level cached domain set

[POS]
Data layer for browser domain_filter route blocking when block_ad_domains is enabled.
"""

from __future__ import annotations

import functools
from importlib import resources

_ASSET_NAME = "ad_domains.txt"


@functools.lru_cache(maxsize=1)
def load_ad_domains() -> frozenset[str]:
    """Load ad/tracker domains from the bundled text asset."""
    asset_path = resources.files("myrm_agent_harness.toolkits.browser.assets").joinpath(_ASSET_NAME)
    raw = asset_path.read_text(encoding="utf-8")
    domains = {line.strip() for line in raw.splitlines() if line.strip() and not line.startswith("#")}
    return frozenset(domains)


AD_DOMAINS: frozenset[str] = load_ad_domains()

__all__ = ["AD_DOMAINS", "load_ad_domains"]
