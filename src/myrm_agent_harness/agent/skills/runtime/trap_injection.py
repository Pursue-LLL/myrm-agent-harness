"""Known-pitfalls tail injection for loaded SKILL.md documents.

[INPUT]
- agent.skills.evolution.infra.integration::EvolutionIntegration (POS: Integration helpers for skill evolution system.) — 启用进化时经 set_trap_lookup 注册 trap 查找回调；本模块不 import evolution

[OUTPUT]
- TrapLookup: 按技能名返回已记录 trap 的回调类型
- set_trap_lookup(): 注册或清除 trap 查找回调
- inject_traps(): 查找并追加该技能的 Known Pitfalls 段落（best-effort，失败返回原文）
- inject_known_pitfalls(): 把 trap 列表渲染为尾部段落的纯函数

[POS]
Appends at the tail of the SKILL.md so the shared prompt prefix stays byte-stable for prompt-cache hits.
Only traps of severity medium or higher qualify, at most five per skill; a lookup failure never blocks skill loading.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence

logger = logging.getLogger(__name__)

TrapRecord = Mapping[str, object]
TrapLookup = Callable[[str], Sequence[TrapRecord]]

_DEFAULT_MAX_TRAPS = 5
_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
_UNKNOWN_RANK = len(_SEVERITY_RANK)
_MAX_QUALIFYING_RANK = _SEVERITY_RANK["medium"]
_SEVERITY_MARK = {"critical": "!!!", "high": "!!", "medium": "!"}

_trap_lookup: TrapLookup | None = None


def set_trap_lookup(lookup: TrapLookup | None) -> None:
    """Register the callback that returns the recorded traps of a skill (``None`` clears it)."""
    global _trap_lookup
    _trap_lookup = lookup


def inject_traps(skill_name: str, content: str) -> str:
    """Append the skill's recorded traps to ``content``; return ``content`` unchanged on any failure."""
    if _trap_lookup is None:
        return content
    try:
        traps = _trap_lookup(skill_name)
        if traps:
            return inject_known_pitfalls(content, traps)
    except Exception as e:
        logger.debug("Trap lookup failed for %s (non-fatal): %s", skill_name, e)
    return content


def inject_known_pitfalls(
    content: str,
    traps: Sequence[TrapRecord],
    max_traps: int = _DEFAULT_MAX_TRAPS,
) -> str:
    """Append a ``Known Pitfalls`` section built from the highest-severity, most frequent traps."""
    qualifying = [t for t in traps if _rank(t) <= _MAX_QUALIFYING_RANK]
    if not qualifying:
        return content

    qualifying.sort(key=lambda t: (_rank(t), -_occurrences(t)))

    lines = ["\n\n---\n## Known Pitfalls\n"]
    for trap in qualifying[:max_traps]:
        entry = f"- [{_SEVERITY_MARK[_severity(trap)]}] {trap.get('description', '')}"
        mitigation = trap.get("mitigation", "")
        if mitigation:
            entry += f" → {mitigation}"
        lines.append(entry)
    return content + "\n".join(lines) + "\n"


def _severity(trap: TrapRecord) -> str:
    return str(trap.get("severity", "low"))


def _rank(trap: TrapRecord) -> int:
    return _SEVERITY_RANK.get(_severity(trap), _UNKNOWN_RANK)


def _occurrences(trap: TrapRecord) -> int:
    count = trap.get("occurrence_count", 0)
    return count if isinstance(count, int) else 0
