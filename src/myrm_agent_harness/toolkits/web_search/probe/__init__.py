"""Local and self-hosted search service discovery.

[INPUT]
- probe.constants (POS: Canonical SearXNG URLs and region presets)
- probe.local_probe (POS: HTTP probes for SearXNG endpoints)

[OUTPUT]
- Re-exports: probe helpers and SearXNG constants for onboarding/setup

[POS]
Subpackage entry for local/self-hosted search service discovery.
"""

from myrm_agent_harness.toolkits.web_search.probe.constants import (
    SEARXNG_DOCKER_SERVICE_URL,
    SEARXNG_HOST_URL,
    SEARXNG_PROBE_CANDIDATE_URLS,
    SEARXNG_REGION_PRESETS,
)
from myrm_agent_harness.toolkits.web_search.probe.local_probe import (
    LocalSearchProbeResult,
    probe_local_search_services,
    probe_searxng_endpoints,
)

__all__ = [
    "SEARXNG_DOCKER_SERVICE_URL",
    "SEARXNG_HOST_URL",
    "SEARXNG_PROBE_CANDIDATE_URLS",
    "SEARXNG_REGION_PRESETS",
    "LocalSearchProbeResult",
    "probe_local_search_services",
    "probe_searxng_endpoints",
]
