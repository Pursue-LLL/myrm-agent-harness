"""
[INPUT]: HTTP request headers, User-Agent strings, access latency metrics, and documentation page contents.
[OUTPUT]: Identified Agent types, AEO abandonment root causes, and conversion funnel analytics.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/agentic_traffic/models.py
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class AgentType(str, Enum):
    CURSOR = "CURSOR"
    CLAUDE_CODE = "CLAUDE_CODE"
    WINDSURF = "WINDSURF"
    AIDER = "AIDER"
    CLINE = "CLINE"
    OPENCLAW = "OPENCLAW"
    MYRM = "MYRM"
    GENERIC_AI_BOT = "GENERIC_AI_BOT"
    HUMAN_BROWSER = "HUMAN_BROWSER"
    UNKNOWN = "UNKNOWN"


class AbandonmentReason(str, Enum):
    TOKEN_OVERFLOW_20K = "TOKEN_OVERFLOW_20K"
    LLMS_TXT_MISSING = "LLMS_TXT_MISSING"
    FIRST_500_TOKENS_VAGUE = "FIRST_500_TOKENS_VAGUE"
    SPA_CLIENT_BLANK = "SPA_CLIENT_BLANK"
    API_SPEC_UNRESOLVABLE = "API_SPEC_UNRESOLVABLE"
    NONE = "NONE"


class FunnelStage(str, Enum):
    DISCOVERED = "DISCOVERED"
    CONTEXT_ABSORBED = "CONTEXT_ABSORBED"
    SANDBOX_PROBED = "SANDBOX_PROBED"
    ADOPTED = "ADOPTED"


@dataclass(frozen=True)
class AgentVisitRecord:
    visit_id: str
    agent_type: AgentType
    user_agent: str
    target_path: str
    duration_ms: float
    status_code: int
    is_agent: bool
    confidence_score: float
    funnel_stage: FunnelStage = FunnelStage.DISCOVERED
    abandonment_reasons: List[AbandonmentReason] = field(default_factory=list)
    timestamp: str = ""


@dataclass
class AeoPageDiagnostic:
    path: str
    estimated_tokens: int
    has_llms_txt_declared: bool
    has_code_in_first_500_tokens: bool
    is_spa_client_blank: bool
    suggested_actions: List[str]
    abandonment_reasons: List[AbandonmentReason]
    aeo_score: int  # 0 to 100


@dataclass
class AgentTrafficSummary:
    total_visits: int
    agent_visits_count: int
    human_visits_count: int
    agent_traffic_ratio_pct: float
    top_agents: Dict[str, int]
    funnel_conversion: Dict[str, int]
    abandonment_distribution: Dict[str, int]
    recent_visits: List[AgentVisitRecord] = field(default_factory=list)
    generated_at: str = ""
