"""unified adaptive router

zero-configuration, self-learning, self-healing intelligent routing system.
"""

from .adaptive_router import AdaptiveRouter
from .domain_metrics import DomainMetricsManager, get_global_domain_metrics_manager
from .models import DomainMetrics, FetcherDecision
from .site_experience import SiteExperience, SiteExperienceStore, get_global_site_experience_store

__all__ = [
    "AdaptiveRouter",
    "DomainMetrics",
    "DomainMetricsManager",
    "FetcherDecision",
    "SiteExperience",
    "SiteExperienceStore",
    "get_global_domain_metrics_manager",
    "get_global_site_experience_store",
]
