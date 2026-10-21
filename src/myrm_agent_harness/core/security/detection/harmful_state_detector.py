"""Harmful psychological state detector for memory scanning.

Detects severe negative psychological states (paranoia, self-harm, severe depression)
to prevent the AI from permanently storing and reinforcing these states (AI Psychosis).
"""

import re

_HARMFUL_PATTERNS = [
    # Self-harm / Suicide
    re.compile(r"\b(kill myself|commit suicide|end my life|want to die|better off dead)\b", re.IGNORECASE),
    re.compile(r"\b(不想活了|想死|自杀|结束生命|活着没意思)\b"),
    # Severe Depression / Hopelessness
    re.compile(r"\b(completely hopeless|no point in living|severe depression|worthless|useless)\b", re.IGNORECASE),
    re.compile(r"\b(重度抑郁|完全绝望|活着没意义|自己是个废物|一无是处)\b"),
    # Paranoia / Delusions
    re.compile(
        r"\b(someone is following me|they are watching me|microchip in my|government is spying on me|gang stalking)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(有人跟踪我|他们在监视我|脑子里有芯片|总觉得有人要害我|被人监视)\b"),
    # Extreme Anxiety / Panic
    re.compile(r"\b(severe anxiety|panic attack|can't breathe|losing my mind)\b", re.IGNORECASE),
    re.compile(r"\b(重度焦虑|惊恐发作|快疯了|喘不过气)\b"),
]


def scan_for_harmful_states(text: str) -> list[str]:
    """Scan text for harmful psychological states.

    Returns a list of matched patterns.
    """
    matches = []
    for pattern in _HARMFUL_PATTERNS:
        if pattern.search(text):
            matches.append(pattern.pattern)
    return matches
