"""Local-first high-speed zero-latency pattern scanner for memory passages.

Detects instruction overrides, command injections, URL exfiltrations, and identity reassignments.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import re

from .types import PatternMatchDetail

# 1. Instruction override patterns (EN + CN)
_INSTRUCTION_OVERRIDE = re.compile(
    r"(?i)("
    r"ignore\s+(all\s+)?(the\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|rules?)"
    r"|disregard\s+(your\s+|all\s+|the\s+)?(previous|prior|instructions?|rules?|safety)"
    r"|forget\s+(everything|anything|all|what)\s+(you|that)\s+(were|was|have\s+been)\s+told"
    r"|(new|updated|revised)\s+instructions\s+(from|for)\s+(the\s+|your\s+)?(developer|system|admin\w*|operator|assistant|model|ai)\b"
    r"|system\s*:\s*you|system\s+override|developer\s+mode"
    r"|you\s+are\s+now\s+(in|a|an|the|dan|free|unrestricted|jailbroken)\b"
    r"|(reveal|print|output|repeat|show)\s+(me\s+)?your\s+(system\s+)?(prompt|instructions)"
    r"|(do\s+not|don'?t|never)\s+(tell|inform|alert|notify)\s+the\s+(user|operator|human|person)\s+(about|that\s+you)"
    r"|skip\s+(the\s+)?(privacy|safety)\s+(gate|check|rules?)"
    r"|忽略(之前|上述|以上|所有)?的?(指令|规则|提示词|限制|设定)"
    r"|无视(系统|安全)?(规则|提示词|指令|审查)"
    r"|忘记(之前|所有|刚才)?(你被赋予的|告诉你的)?(设定|指令|内容)"
    r"|系统提示词已更新|系统指令重置"
    r"|你现在进入(开发者模式|上帝模式|无限制模式|debug\s*mode)"
    r"|从现在开始你是一个?(无限制|自由|解除道德限制)的"
    r"|绝对不要(告诉|通知|提醒|汇报给)用户"
    r"|跳过(安全|隐私|权限)?(审查|门禁|检测)"
    r")"
)

# 2. Command injection risk patterns
_COMMAND_RISK = re.compile(
    r"(?i)("
    r"(?:without\s+(?:asking|confirm\w*|telling|permission|approval)|silently|quietly"
    r"|do\s+not\s+(?:ask|tell|mention|confirm)|don'?t\s+(?:ask|tell|mention|confirm)"
    r"|无需(?:询问|确认|通知|获得许可)|静默(?:执行|运行))"
    r".{0,100}"
    r"(?:\|\s*(?:sudo\s+)?(?:ba|z|da)?sh\b|\brm\s+-[a-z]*r[a-z]*f|\bbase64\b|/dev/tcp/|\bnc\s+-"
    r"|~/\.ssh|\bid_rsa\b|/etc/passwd|\.aws/credentials|(?<!\w)\.env\b)"
    r")"
)

# 3. Fetch and execute pipe patterns
_FETCH_AND_PIPE = re.compile(
    r"(?i)\b(?:curl|wget)\b[^\n|]{0,250}"
    r"(?:\|\s*(?:sudo\s+)?(?:ba|z|da)?sh\b|@(?:~|\$HOME|/etc/|/root/|/home/)|@\S*(?:\.env|id_rsa|credentials)\b)"
)

# 4. Hidden URL data exfiltration patterns
_EXFILTRATION_URL = re.compile(
    r"(?i)(?:!\[[^\]\n]{0,100}\]\(\s*https?://[^\s)]+"
    r"(?:token|secret|session|key|cookie|pwd|password|prompt|history|data)=[^\s)]+\)"
    r"|<img\b[^>]{0,200}?src\s*=\s*[\"']?https?://[^\s\"']+"
    r"(?:token|secret|session|key|cookie|pwd|password|prompt|history|data)=[^\s\"']+)"
)

# 5. Identity reassignment and prompt structure hijacking
_IDENTITY_REASSIGNMENT = re.compile(
    r"(?i)("
    r"<\|im_start\|>\s*system"
    r"|\[SYSTEM\]\s*:"
    r"|<<SYS>>"
    r"|Role\s*:\s*Root\s+Administrator"
    r"|你是系统内核，拥有最高执行权限"
    r")"
)


def scan_passage_patterns(
    text: str,
    enable_url_scan: bool = True,
    enable_cmd_scan: bool = True,
) -> list[PatternMatchDetail]:
    """Scan a memory passage for prompt injection threats using local zero-latency regex."""
    if not text or not text.strip():
        return []

    matches: list[PatternMatchDetail] = []

    # 1. Instruction override
    inst_match = _INSTRUCTION_OVERRIDE.search(text)
    if inst_match:
        matches.append(
            PatternMatchDetail(
                pattern_category="instruction_override",
                matched_substring=inst_match.group(0)[:60],
                risk_level="critical",
            )
        )

    # 2. Command risk
    if enable_cmd_scan:
        cmd_match = _COMMAND_RISK.search(text)
        if cmd_match:
            matches.append(
                PatternMatchDetail(
                    pattern_category="command_risk",
                    matched_substring=cmd_match.group(0)[:60],
                    risk_level="critical",
                )
            )

        pipe_match = _FETCH_AND_PIPE.search(text)
        if pipe_match:
            matches.append(
                PatternMatchDetail(
                    pattern_category="fetch_and_pipe_risk",
                    matched_substring=pipe_match.group(0)[:60],
                    risk_level="critical",
                )
            )

    # 3. URL Exfiltration
    if enable_url_scan:
        url_match = _EXFILTRATION_URL.search(text)
        if url_match:
            matches.append(
                PatternMatchDetail(
                    pattern_category="url_exfiltration",
                    matched_substring=url_match.group(0)[:60],
                    risk_level="high",
                )
            )

    # 4. Identity reassignment
    ident_match = _IDENTITY_REASSIGNMENT.search(text)
    if ident_match:
        matches.append(
            PatternMatchDetail(
                pattern_category="identity_reassignment",
                matched_substring=ident_match.group(0)[:60],
                risk_level="critical",
            )
        )

    return matches
