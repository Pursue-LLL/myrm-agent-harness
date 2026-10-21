"""Command parser and prompt builder for session-scoped loops.

[INPUT]
- Raw string arguments from /loop command (e.g. "5m test my service --times 10")
- LLM completion text for completion marker detection

[OUTPUT]
- LoopConfig with parsed prompt, interval_seconds, times, and until clause
- Formatted wakeup prompt for injected turn

[POS]
Harness runtime layer. Pure function parsing with zero framework or server dependencies.
"""

from __future__ import annotations

import re

from .types import (
    DEFAULT_MIN_INTERVAL_SECONDS,
    LOOP_COMPLETE_MARKER,
    LoopConfig,
)

_INTERVAL_TOKEN_RE = re.compile(
    r"^(?=\d)(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$", re.IGNORECASE
)

_LOOP_COMPLETE_RE = re.compile(
    r"(?im)^\s*" + re.escape(LOOP_COMPLETE_MARKER) + r"\s*[.!]?\s*$"
)

_LOOP_COMMAND_PREFIX_RE = re.compile(
    r"^(?:/)?(?:loop|repeat|cron)\s+", re.IGNORECASE
)

_WAKEUP_PROMPT_TEMPLATE = (
    "[/loop wakeup #{tick}{cadence}]\n"
    "Recurring task: {prompt}\n\n"
    "This is an automatic wakeup from the /loop the user set. Perform the "
    "task now against the CURRENT state (re-check files, processes, or "
    "services fresh — do not assume anything from earlier iterations still "
    "holds). Report concisely what you found or did this iteration.\n"
    "If the task is now complete, no longer applicable, or the target "
    "objective has been reached, state so clearly and end your reply with "
    f"{LOOP_COMPLETE_MARKER} on its own line — that stops the loop."
)

_WAKEUP_PROMPT_WITH_UNTIL_TEMPLATE = (
    "[/loop wakeup #{tick}{cadence}]\n"
    "Recurring task: {prompt}\n\n"
    "Stop condition: {until}\n\n"
    "This is an automatic wakeup from the /loop the user set. Perform the "
    "task now against the CURRENT state (re-check files, processes, or "
    "services fresh — do not assume anything from earlier iterations still "
    "holds). Report concisely what you found or did this iteration, and "
    "show concrete evidence regarding the stop condition status.\n"
    "If the stop condition is met, or the task is no longer applicable, state "
    f"so clearly and end your reply with {LOOP_COMPLETE_MARKER} on its own line — "
    "that stops the loop."
)


def parse_interval_token(token: str) -> int | None:
    """Parse time string like 30s, 5m, 2h, 1h30m into total seconds.

    Returns None if token does not match pattern or totals 0.
    """
    if not token:
        return None
    match = _INTERVAL_TOKEN_RE.match(token.strip())
    if not match:
        return None
    hours, minutes, seconds = (int(group) if group else 0 for group in match.groups())
    total = hours * 3600 + minutes * 60 + seconds
    return total if total > 0 else None


def parse_loop_args(text: str) -> LoopConfig:
    """Parse command string for /loop [interval] <prompt> [--times N] [--until <condition>]."""
    raw = (text or "").strip()
    if not raw:
        return LoopConfig(prompt="", error="empty command")

    raw = _LOOP_COMMAND_PREFIX_RE.sub("", raw).strip()
    if not raw:
        return LoopConfig(
            prompt="",
            error="missing task prompt (usage: /loop [interval] <task> [--times N] [--until condition])",
        )

    times = 0
    until = ""

    # Extract --times N
    times_match = re.search(r"\s--times\s+(\S+)", raw)
    if times_match:
        try:
            times = int(times_match.group(1))
            if times < 1:
                return LoopConfig(
                    prompt="",
                    error=f"--times expects a positive integer, got {times_match.group(1)!r}",
                )
        except ValueError:
            return LoopConfig(
                prompt="",
                error=f"--times expects a positive integer, got {times_match.group(1)!r}",
            )
        raw = (raw[: times_match.start()] + raw[times_match.end() :]).strip()

    # Extract --until <condition>
    until_match = re.search(r"\s--until\s+(.+)$", raw, re.DOTALL)
    if until_match:
        until = until_match.group(1).strip()
        raw = raw[: until_match.start()].strip()

    # Support syntactic sugar: /loop every 5m <prompt>
    tokens = raw.split(None, 1)
    if tokens and tokens[0].lower() == "every" and len(tokens) > 1:
        raw = tokens[1]
        tokens = raw.split(None, 1)

    interval_sec: int | None = None
    if tokens:
        candidate_interval = parse_interval_token(tokens[0])
        if candidate_interval is not None:
            interval_sec = max(DEFAULT_MIN_INTERVAL_SECONDS, candidate_interval)
            raw = tokens[1].strip() if len(tokens) > 1 else ""

    if not raw:
        return LoopConfig(
            prompt="",
            error="missing task prompt (usage: /loop [interval] <task> [--times N] [--until condition])",
        )

    return LoopConfig(
        prompt=raw,
        interval_seconds=interval_sec,
        times=times,
        until=until,
        error=None,
    )


def format_interval(seconds: float) -> str:
    """Render seconds as concise human-readable interval (e.g. 90 -> 1m30s, 300 -> 5m)."""
    rounded = max(0, round(seconds))
    hours, remainder = divmod(rounded, 3600)
    minutes, secs = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs or not parts:
        parts.append(f"{secs}s")
    return "".join(parts)


def build_wakeup_prompt(
    tick: int,
    prompt: str,
    *,
    until: str = "",
    cadence_label: str = "",
) -> str:
    """Construct deterministic wakeup prompt for injected agent turn."""
    cadence = f", {cadence_label}" if cadence_label else ""
    if until:
        return _WAKEUP_PROMPT_WITH_UNTIL_TEMPLATE.format(
            tick=tick,
            cadence=cadence,
            prompt=prompt,
            until=until,
        )
    return _WAKEUP_PROMPT_TEMPLATE.format(
        tick=tick,
        cadence=cadence,
        prompt=prompt,
    )


def is_loop_complete_response(text: str) -> bool:
    """Determine whether model emitted LOOP_COMPLETE sentinel on its own line."""
    if not text:
        return False
    return _LOOP_COMPLETE_RE.search(text) is not None
