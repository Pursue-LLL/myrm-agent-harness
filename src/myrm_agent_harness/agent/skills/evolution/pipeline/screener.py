"""Evolution screener - Two-phase filtering to prevent blind evolution.

[INPUT]
- agent.skills.evolution.core.types::EvolutionRequest (POS: Data types for skill evolution system.)

[OUTPUT]
- EvolutionScreener: Two-phase evolution screener.
- ScreeningResult: Result of evolution screening.

[POS]
Evolution screening pipeline. Implements multi-phase checks including static error interception, GUI-First force retry, and LLM confirmation.

## Architecture

Two-phase screening to block "snowball effect" of blind fixes:

**Phase 1: Rule-based (Cooldown)**
- Rejects repeated evolution attempts within cooldown period
- Checks both skill.updated_at and rejection history
- Zero LLM cost, instant response

**Phase 2: LLM Confirmation (Cheap Model)**
- Only for FIX evolution type
- Analyzes real error logs (HTTP status, exception stack)
- Asks cheap LLM: "Is this really a skill code defect?"
- Returns YES (proceed) or NO + reason (block)

**Prometheus Metrics (Observability)**
- evolution_screening_total: Counter by phase + result
- evolution_screening_confidence: Histogram of LLM confidence
- evolution_screening_duration_seconds: Histogram of screening duration by phase

## Design Principles

1. **Cost Optimization**: Use gpt-4o-mini/claude-haiku for Phase 2
2. **Fail-Safe**: LLM errors → Allow (don't block valid fixes)
3. **Transparency**: Record all rejections for audit
4. **Signal Extraction**: Focus on HTTP status + exception type vs full stack
5. **Observability**: Expose Prometheus metrics for monitoring and tuning
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage

from myrm_agent_harness.agent.skills.evolution.core.types import (
    EvolutionRequest,
    EvolutionType,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from myrm_agent_harness.agent.event_log import EventLogger

    from .store import SkillStore

from myrm_agent_harness.observability.metrics import (
    get_or_create_counter,
    get_or_create_histogram,
)

logger = logging.getLogger(__name__)


SCREENING_TOTAL = get_or_create_counter(
    "evolution_screening_total",
    "Total evolution screening requests",
    ("phase", "result"),  # phase: cooldown|llm_confirmation|none; result: allowed|blocked
)

SCREENING_CONFIDENCE = get_or_create_histogram(
    "evolution_screening_confidence",
    "LLM confidence distribution for screening decisions",
    buckets=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)

SCREENING_DURATION = get_or_create_histogram(
    "evolution_screening_duration_seconds",
    "Evolution screening duration in seconds",
    labelnames=("phase",),  # phase: cooldown|llm_confirmation|total
)

__all__ = ["EvolutionScreener", "ScreeningResult"]


@dataclass
class ScreeningResult:
    """Result of evolution screening."""

    allowed: bool
    reason: str
    phase: str  # "cooldown", "llm_confirmation", "none"
    confidence: float = 0.5  # LLM confidence in decision (0.0-1.0)


class EvolutionScreener:
    """Two-phase evolution screener.

    Phase 1: Rule-based screening (cooldown).
    Phase 2: LLM confirmation (cheap model).

    Benefits:
    - Block 70-80% blind fixes (estimated based on OpenSpace data)
    - Reduce evolution cost by 60-70% (1 cheap LLM call << 1 expensive evolution)
    - Prevent "snowball effect" (fix correct code → new errors → infinite loop)
    """

    # Strategy → allowed evolution types mapping.
    # "balanced" allows everything (default). "innovate" allows all + lowers
    # LLM confirmation threshold. "harden" only allows FIX + OPTIMIZE_DESCRIPTION.
    # "repair-only" restricts to FIX only.
    _STRATEGY_ALLOWED_TYPES: dict[str, frozenset[EvolutionType]] = {
        "balanced": frozenset(EvolutionType),
        "innovate": frozenset(EvolutionType),
        "harden": frozenset({EvolutionType.FIX, EvolutionType.OPTIMIZE_DESCRIPTION}),
        "repair-only": frozenset({EvolutionType.FIX}),
    }

    def __init__(
        self,
        store: SkillStore,
        cheap_llm: BaseChatModel | None = None,
        cooldown_seconds: int = 3600,
        event_logger: EventLogger | None = None,
        evolution_strategy: str = "balanced",
    ):
        """Initialize screener.

        Args:
            store: SkillStore for checking history
            cheap_llm: Cheap LLM for Phase 2 (e.g., gpt-4o-mini, claude-haiku-3)
            cooldown_seconds: Cooldown period in seconds (default 1 hour)
            event_logger: Optional EventLogger to record EVOLUTION_REJECTED events
            evolution_strategy: Controls which evolution types are allowed.
                balanced (default) — all types; innovate — all + lower confirmation
                threshold; harden — FIX + OPTIMIZE_DESCRIPTION only;
                repair-only — FIX only.
        """
        self._store = store
        self._cheap_llm = cheap_llm
        self._cooldown_seconds = cooldown_seconds
        self._event_logger = event_logger
        self._evolution_strategy = evolution_strategy

    @property
    def evolution_strategy(self) -> str:
        """Current evolution strategy."""
        return self._evolution_strategy

    @evolution_strategy.setter
    def evolution_strategy(self, value: str) -> None:
        """Update strategy at runtime (hot-update without restart)."""
        if value not in self._STRATEGY_ALLOWED_TYPES:
            logger.warning("Unknown evolution strategy '%s', falling back to 'balanced'", value)
            value = "balanced"
        self._evolution_strategy = value

    async def screen_request(self, request: EvolutionRequest) -> ScreeningResult:
        """Screen evolution request.

        Args:
            request: Evolution request

        Returns:
            ScreeningResult indicating if request is allowed
        """
        start_time = time.time()

        if not request.skill_id:
            result = ScreeningResult(
                allowed=True,
                reason="No skill ID provided",
                phase="none",
                confidence=1.0,
            )
            SCREENING_TOTAL.labels(phase="none", result="allowed").inc()
            SCREENING_DURATION.labels(phase="total").observe(time.time() - start_time)
            return result

        # Phase -1: Strategy-based type filtering (zero-cost, before any I/O)
        allowed_types = self._STRATEGY_ALLOWED_TYPES.get(
            self._evolution_strategy, frozenset(EvolutionType)
        )
        if request.evolution_type not in allowed_types:
            reason = (
                f"Evolution type '{request.evolution_type}' blocked by "
                f"strategy '{self._evolution_strategy}' "
                f"(allowed: {', '.join(sorted(t.value for t in allowed_types))})"
            )
            await self._log_rejection_event(request.skill_id, "strategy", reason)
            SCREENING_TOTAL.labels(phase="strategy", result="blocked").inc()
            SCREENING_DURATION.labels(phase="strategy").observe(time.time() - start_time)
            SCREENING_DURATION.labels(phase="total").observe(time.time() - start_time)
            SCREENING_CONFIDENCE.observe(1.0)
            return ScreeningResult(allowed=False, reason=reason, phase="strategy", confidence=1.0)

        # Phase 0: Evolution lock check (highest priority, zero-cost)
        if self._store.is_evolution_locked(request.skill_id):
            reason = "Skill is locked from auto-evolution (user-protected in DB)"
            await self._log_rejection_event(request.skill_id, "locked", reason)
            SCREENING_TOTAL.labels(phase="locked", result="blocked").inc()
            SCREENING_DURATION.labels(phase="locked").observe(time.time() - start_time)
            SCREENING_DURATION.labels(phase="total").observe(time.time() - start_time)
            SCREENING_CONFIDENCE.observe(1.0)
            return ScreeningResult(allowed=False, reason=reason, phase="locked", confidence=1.0)

        # Phase 0.5: Intent-Aware Cooldown Override
        # If user explicitly requests to continue fixing via GUI flag, bypass cooldown
        intent_override = request.force_retry
        if intent_override:
            logger.info(
                "Intent-aware cooldown override triggered by GUI force_retry flag for skill '%s'",
                request.skill_id,
            )

        skill = self._store.get_skill(request.skill_id)
        if skill:
            # Double check the physical file content frontmatter (in case DB is stale)
            try:
                from myrm_agent_harness.backends.skills._utils import (
                    parse_skill_frontmatter,
                )

                fm = parse_skill_frontmatter(skill.content, request.skill_id)
                if fm.evolution_locked:
                    reason = "Skill is locked from auto-evolution (user-protected in SKILL.md)"
                    await self._log_rejection_event(request.skill_id, "locked", reason)
                    SCREENING_TOTAL.labels(phase="locked", result="blocked").inc()
                    SCREENING_DURATION.labels(phase="locked").observe(time.time() - start_time)
                    SCREENING_DURATION.labels(phase="total").observe(time.time() - start_time)
                    SCREENING_CONFIDENCE.observe(1.0)
                    return ScreeningResult(allowed=False, reason=reason, phase="locked", confidence=1.0)
            except Exception as e:
                logger.debug(f"Failed to parse frontmatter during evolution screening: {e}")

            # Phase 1: Cooldown check
            if not intent_override:
                # Check if recently evolved
                now = datetime.now()
                # Ensure both are naive or aware
                updated_at = skill.updated_at
                if updated_at.tzinfo:
                    now = datetime.now(updated_at.tzinfo)

                time_since_evolution = (now - updated_at).total_seconds()
                if time_since_evolution < self._cooldown_seconds:
                    reason = f"Skill recently evolved ({time_since_evolution:.0f}s < {self._cooldown_seconds}s)"
                    await self._log_rejection_event(request.skill_id, "cooldown", reason)
                    # Metrics
                    SCREENING_TOTAL.labels(phase="cooldown", result="blocked").inc()
                    SCREENING_DURATION.labels(phase="cooldown").observe(time.time() - start_time)
                    SCREENING_DURATION.labels(phase="total").observe(time.time() - start_time)
                    SCREENING_CONFIDENCE.observe(1.0)
                    return ScreeningResult(allowed=False, reason=reason, phase="cooldown", confidence=1.0)

                # Check if recently rejected
                rejections = self._store.load_rejections(skill_id=request.skill_id, limit=1)
                if rejections:
                    last_rejection = rejections[0]
                    try:
                        rejected_at = datetime.fromisoformat(last_rejection["rejected_at"])
                        if rejected_at.tzinfo:
                            now_rej = datetime.now(rejected_at.tzinfo)
                        else:
                            now_rej = datetime.now()
                        time_since_rejection = (now_rej - rejected_at).total_seconds()
                        if time_since_rejection < self._cooldown_seconds:
                            reason = (
                                f"Skill recently rejected ({time_since_rejection:.0f}s < {self._cooldown_seconds}s)"
                            )
                            await self._log_rejection_event(request.skill_id, "cooldown", reason)
                            # Metrics
                            SCREENING_TOTAL.labels(phase="cooldown", result="blocked").inc()
                            SCREENING_DURATION.labels(phase="cooldown").observe(time.time() - start_time)
                            SCREENING_DURATION.labels(phase="total").observe(time.time() - start_time)
                            SCREENING_CONFIDENCE.observe(1.0)
                            return ScreeningResult(
                                allowed=False,
                                reason=reason,
                                phase="cooldown",
                                confidence=1.0,
                            )
                    except (ValueError, TypeError):
                        pass

        # Phase 1.5: Static Error Type Interception (Bypass LLM for basic syntax errors)
        if request.evolution_type == EvolutionType.FIX and skill:
            error_signals = self._extract_error_signals(request.reason)
            exception_types = error_signals.get("exception_types", "")

            # If it's a clear syntax or import error, bypass LLM confirmation
            static_bypass_errors = [
                "SyntaxError",
                "IndentationError",
                "NameError",
                "ModuleNotFoundError",
                "ImportError",
                "AttributeError",
                "TypeError",
            ]
            if any(err in exception_types for err in static_bypass_errors):
                reason = f"Static interception: Clear code defect detected ({exception_types})"
                logger.info(
                    "Static interception allowed evolution for skill '%s': %s",
                    skill.name,
                    reason,
                )
                SCREENING_TOTAL.labels(phase="static_interception", result="allowed").inc()
                SCREENING_DURATION.labels(phase="static_interception").observe(time.time() - start_time)
                SCREENING_DURATION.labels(phase="total").observe(time.time() - start_time)
                SCREENING_CONFIDENCE.observe(1.0)
                return ScreeningResult(
                    allowed=True,
                    reason=reason,
                    phase="static_interception",
                    confidence=1.0,
                )

        # Phase 2: LLM Confirmation (only for FIX evolution)
        if self._cheap_llm and request.evolution_type == EvolutionType.FIX and skill:
            # Extract error signals (HTTP status, exception type)
            error_signals = self._extract_error_signals(request.reason)

            # Build confirmation prompt
            prompt = self._build_confirmation_prompt(
                skill_content=skill.content,
                error_log=request.reason,
                error_signals=error_signals,
            )

            try:
                response = await self._cheap_llm.ainvoke([HumanMessage(content=prompt)])
                content = response.content.strip()

                # Parse LLM response (supports multiple formats)
                decision, reason, confidence = self._parse_llm_response(content)

                if decision:
                    # LLM confirmed: proceed with evolution
                    logger.info(
                        "LLM confirmed evolution for skill '%s' (confidence=%.2f): %s",
                        skill.name,
                        confidence,
                        reason[:100],
                    )
                    # Metrics
                    SCREENING_TOTAL.labels(phase="llm_confirmation", result="allowed").inc()
                    SCREENING_DURATION.labels(phase="llm_confirmation").observe(time.time() - start_time)
                    SCREENING_DURATION.labels(phase="total").observe(time.time() - start_time)
                    SCREENING_CONFIDENCE.observe(confidence)
                    return ScreeningResult(
                        allowed=True,
                        reason=reason,
                        phase="llm_confirmation",
                        confidence=confidence,
                    )
                else:
                    # "innovate" strategy: override low-confidence rejections
                    if self._evolution_strategy == "innovate" and confidence < 0.7:
                        logger.info(
                            "Innovate strategy override: allowing evolution for '%s' "
                            "(LLM rejected with low confidence=%.2f)",
                            skill.name,
                            confidence,
                        )
                        SCREENING_TOTAL.labels(phase="llm_confirmation", result="allowed").inc()
                        SCREENING_DURATION.labels(phase="llm_confirmation").observe(time.time() - start_time)
                        SCREENING_DURATION.labels(phase="total").observe(time.time() - start_time)
                        SCREENING_CONFIDENCE.observe(confidence)
                        return ScreeningResult(
                            allowed=True,
                            reason=f"Innovate override (conf={confidence:.2f}): {reason}",
                            phase="llm_confirmation",
                            confidence=confidence,
                        )

                    # LLM rejected: block evolution
                    logger.info(
                        "LLM rejected evolution for skill '%s' (confidence=%.2f): %s",
                        skill.name,
                        confidence,
                        reason[:100],
                    )
                    await self._log_rejection_event(skill.skill_id, "llm_confirmation", reason, confidence)

                    # Persist rejection as evolution constraint (learning feedback loop)
                    if confidence >= 0.7:
                        constraint = f"LLM screener rejected FIX (conf={confidence:.2f}): {reason[:200]}"
                        try:
                            await self._store.add_evolution_constraint(skill.skill_id, constraint)
                        except Exception as e:
                            logger.debug("Failed to persist evolution constraint: %s", e)

                    # Metrics
                    SCREENING_TOTAL.labels(phase="llm_confirmation", result="blocked").inc()
                    SCREENING_DURATION.labels(phase="llm_confirmation").observe(time.time() - start_time)
                    SCREENING_DURATION.labels(phase="total").observe(time.time() - start_time)
                    SCREENING_CONFIDENCE.observe(confidence)
                    return ScreeningResult(
                        allowed=False,
                        reason=reason,
                        phase="llm_confirmation",
                        confidence=confidence,
                    )

            except Exception as e:
                logger.error("LLM confirmation failed for skill '%s': %s", skill.name, e)
                # Fail-safe: allow evolution on LLM errors (don't block valid fixes)
                # Metrics
                SCREENING_TOTAL.labels(phase="llm_confirmation", result="allowed").inc()
                SCREENING_DURATION.labels(phase="llm_confirmation").observe(time.time() - start_time)
                SCREENING_DURATION.labels(phase="total").observe(time.time() - start_time)
                SCREENING_CONFIDENCE.observe(0.0)
                return ScreeningResult(
                    allowed=True,
                    reason=f"LLM confirmation unavailable: {e}",
                    phase="llm_confirmation",
                    confidence=0.0,
                )

        # No screening applied
        SCREENING_TOTAL.labels(phase="none", result="allowed").inc()
        SCREENING_DURATION.labels(phase="total").observe(time.time() - start_time)
        return ScreeningResult(
            allowed=True,
            reason="No screening applied (DERIVED/CAPTURED or no LLM)",
            phase="none",
            confidence=1.0,
        )

    async def _log_rejection_event(self, skill_id: str, phase: str, reason: str, confidence: float = 1.0) -> None:
        """Log rejection event to EventLogger if configured.

        Args:
            skill_id: Skill identifier
            phase: Rejection phase (cooldown, llm_confirmation)
            reason: Rejection reason
            confidence: LLM confidence
        """
        if self._event_logger:
            try:
                await self._event_logger.log(
                    "EVOLUTION_REJECTED",
                    {
                        "skill_id": skill_id,
                        "phase": phase,
                        "reason": reason,
                        "confidence": confidence,
                    },
                )
            except Exception as e:
                logger.warning("Failed to log EVOLUTION_REJECTED event: %s", e)

    def _extract_error_signals(self, error_log: str) -> dict[str, str]:
        """Extract key error signals from log.

        Extracts:
        - HTTP status codes (404, 500, etc.)
        - Exception types (ValueError, KeyError, etc.)
        - Error keywords (timeout, connection, permission, etc.)

        Args:
            error_log: Raw error log

        Returns:
            Dict with extracted signals
        """
        signals: dict[str, str] = {}

        # Extract HTTP status codes
        http_pattern = r"\b((?:HTTP\s*)?[1-5]\d{2})\b"
        http_matches = re.findall(http_pattern, error_log, re.IGNORECASE)
        if http_matches:
            signals["http_status"] = ", ".join(set(http_matches))

        # Extract exception types
        exception_pattern = r"\b(\w+(?:Error|Exception))\b"
        exception_matches = re.findall(exception_pattern, error_log)
        if exception_matches:
            signals["exception_types"] = ", ".join(set(exception_matches[:3]))  # Top 3

        # Extract error keywords
        error_keywords = [
            "timeout",
            "connection",
            "permission",
            "denied",
            "forbidden",
            "not found",
            "unauthorized",
            "rate limit",
            "quota",
            "unavailable",
        ]
        found_keywords = [kw for kw in error_keywords if kw.lower() in error_log.lower()]
        if found_keywords:
            signals["error_keywords"] = ", ".join(found_keywords[:3])

        return signals

    def _parse_llm_response(self, content: str) -> tuple[bool, str, float]:
        """Parse LLM confirmation response.

        Supports multiple formats:
        - "YES" / "NO" at start
        - "CONFIRMED" / "REJECTED"
        - Structured JSON with decision + reason + confidence

        Args:
            content: LLM response content

        Returns:
            Tuple of (decision: bool, reason: str, confidence: float)
        """
        stripped = content.strip()
        content_upper = stripped.upper()

        # Format 0: Structured JSON
        if stripped.startswith("{"):
            try:
                import json

                data = json.loads(stripped)
                approved = bool(data.get("approved", data.get("decision", False)))
                reason = str(data.get("reason", stripped))
                confidence = float(data.get("confidence", 0.8))
                return approved, reason, confidence
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

        # Format 1: Simple YES/NO
        if content_upper.startswith("YES"):
            return True, content.strip(), 0.8
        if content_upper.startswith("NO"):
            return False, content.strip(), 0.8

        # Format 2: CONFIRMED/REJECTED
        if "CONFIRMED" in content_upper:
            return True, content.strip(), 0.8
        if "REJECTED" in content_upper:
            return False, content.strip(), 0.8

        # Format 3: Try to parse confidence from text
        confidence = 0.5  # Default
        confidence_pattern = r"confidence[:\s]+([0-9.]+)"
        confidence_match = re.search(confidence_pattern, content, re.IGNORECASE)
        if confidence_match:
            try:
                confidence = float(confidence_match.group(1))
                if confidence > 1.0:  # Handle percentage format
                    confidence = confidence / 100.0
            except ValueError:
                pass

        # Fallback: analyze sentiment
        negative_keywords = [
            "not a defect",
            "not a bug",
            "not the skill",
            "external",
            "api",
            "service",
        ]
        if any(kw in content.lower() for kw in negative_keywords):
            return False, content.strip(), confidence

        # Default: allow if unclear
        return True, content.strip(), 0.5

    def _build_confirmation_prompt(self, skill_content: str, error_log: str, error_signals: dict[str, str]) -> str:
        """Build optimized prompt for LLM confirmation.

        Key optimizations:
        - Extract error signals upfront (HTTP status, exception type)
        - Truncate skill content to first 2000 chars (signatures only)
        - Clear decision criteria (skill defect vs external/usage error)

        Args:
            skill_content: Current skill content
            error_log: Error log or feedback
            error_signals: Extracted error signals

        Returns:
            Optimized prompt string
        """
        # Build signals summary
        signals_text = ""
        if error_signals:
            signals_parts = []
            if "http_status" in error_signals:
                signals_parts.append(f"HTTP Status: {error_signals['http_status']}")
            if "exception_types" in error_signals:
                signals_parts.append(f"Exceptions: {error_signals['exception_types']}")
            if "error_keywords" in error_signals:
                signals_parts.append(f"Keywords: {error_signals['error_keywords']}")
            if signals_parts:
                signals_text = "\n\nError Signals:\n" + "\n".join(f"- {p}" for p in signals_parts)

        return f"""Analyze if the skill code has a real defect that requires modification.

Error Log:
{error_log[:1000]}{signals_text}

Skill Code (first 2000 chars):
{skill_content[:2000]}

Decision Criteria:
- CONFIRM (YES) if: Skill logic is incorrect, outdated API usage, missing error handling, or syntax error
- REJECT (NO) if: External service error (404, 500, timeout), user input error, API rate limit, or network issue

Please answer YES or NO, then explain your reasoning in one sentence.

Answer:"""
