"""
[INPUT]: HTTP User-Agent strings, request headers mapping, and interaction latency metrics.
[OUTPUT]: Identified AgentType, classification confidence score, and boolean agent flag.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/agentic_traffic/traffic_classifier.py
"""

import re
from typing import Dict, Optional, Tuple

from .models import AgentType

_AGENT_UA_PATTERNS = [
    (re.compile(r"cursor", re.IGNORECASE), AgentType.CURSOR),
    (re.compile(r"claude-code|claudecode|anthropic-code", re.IGNORECASE), AgentType.CLAUDE_CODE),
    (re.compile(r"windsurf|codeium", re.IGNORECASE), AgentType.WINDSURF),
    (re.compile(r"aider", re.IGNORECASE), AgentType.AIDER),
    (re.compile(r"cline|roo-cline", re.IGNORECASE), AgentType.CLINE),
    (re.compile(r"openclaw", re.IGNORECASE), AgentType.OPENCLAW),
    (re.compile(r"myrm", re.IGNORECASE), AgentType.MYRM),
    (
        re.compile(r"gptbot|claudebot|perplexitybot|bytespider|anthropic-ai|cohere-ai", re.IGNORECASE),
        AgentType.GENERIC_AI_BOT,
    ),
]

_HUMAN_BROWSER_PATTERNS = [
    re.compile(r"mozilla/5\.0.*(macintosh|windows|iphone|android).*applewebkit.*(chrome|safari|firefox)", re.IGNORECASE),
]


class AgentTrafficClassifier:
    """
    Classifies incoming HTTP traffic to detect whether an AI coding agent or generic LLM crawler
    is inspecting documentation and APIs, distinguishing it from conventional human browsing.
    """

    def classify_request(
        self,
        user_agent: str,
        headers: Optional[Dict[str, str]] = None,
        duration_ms: float = 0.0,
    ) -> Tuple[AgentType, bool, float]:
        """
        Returns:
            Tuple of (AgentType, is_agent: bool, confidence_score: float)
        """
        clean_ua = (user_agent or "").strip()
        h = {k.lower(): v for k, v in (headers or {}).items()}

        # 1. 显式 Agent 请求头检查 (e.g. X-Agent-Client, A2A, llm-client)
        if "x-agent-client" in h:
            val = h["x-agent-client"].lower()
            if "cursor" in val:
                return AgentType.CURSOR, True, 0.99
            if "claude" in val:
                return AgentType.CLAUDE_CODE, True, 0.99
            if "windsurf" in val:
                return AgentType.WINDSURF, True, 0.99
            if "myrm" in val:
                return AgentType.MYRM, True, 0.99
            return AgentType.GENERIC_AI_BOT, True, 0.95

        # 2. 正则匹配已知 Agent UA
        for pattern, agent_type in _AGENT_UA_PATTERNS:
            if pattern.search(clean_ua):
                return agent_type, True, 0.95

        # 3. 典型 Agent 极速拉取行为特征 (< 800ms 且仅请求 markdown/json 或携带特定 Accept)
        accept_header = h.get("accept", "").lower()
        if "text/markdown" in accept_header or "text/x-markdown" in accept_header:
            return AgentType.GENERIC_AI_BOT, True, 0.85

        # 4. 判断是否为普通人类浏览器
        for h_pat in _HUMAN_BROWSER_PATTERNS:
            if h_pat.search(clean_ua):
                # 如果是常见浏览器但伴随极速拉取且缺少静态资源加载，标记为低可信人类
                if 0 < duration_ms < 500.0 and "sec-ch-ua" not in h:
                    return AgentType.GENERIC_AI_BOT, True, 0.60
                return AgentType.HUMAN_BROWSER, False, 0.90

        if not clean_ua:
            return AgentType.GENERIC_AI_BOT, True, 0.50

        return AgentType.UNKNOWN, False, 0.40
