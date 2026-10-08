"""
[POS] src/myrm_agent_harness/core/security/live_session_credential_shield/post_takeover_masker.py
[INPUT] re, time, uuid, typing
[OUTPUT] PostTakeoverMasker

Screen bounding box masking and DOM tree attribute redaction upon returning session control.
Blinds password fields and credential nodes so subsequent LLM observations cannot be probed via prompt injection.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import re
import time
import uuid

from .types import (
    BoundingBox,
    DOMRedactionRule,
    MaskingRedactionReport,
    ScreenMaskRegion,
)

logger = logging.getLogger(__name__)


class PostTakeoverMasker:
    """Applies bounding-box screen masking and sanitizes DOM trees before handing control back to Agent."""

    DEFAULT_DOM_RULES: tuple[DOMRedactionRule, ...] = (
        DOMRedactionRule(
            selector_pattern=r"<input[^>]*type=['\"]?password['\"]?[^>]*>",
            attribute_to_redact="value",
        ),
        DOMRedactionRule(
            selector_pattern=r"<input[^>]*name=['\"]?(?:cvv|cvc|otp|token|secret)['\"]?[^>]*>",
            attribute_to_redact="value",
        ),
    )

    VALUE_ATTR_REGEX: re.Pattern[str] = re.compile(
        r"""(value\s*=\s*['"])([^'"]*)(['"])""",
        re.IGNORECASE,
    )

    RAW_TOKEN_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"sk-(?:proj-)?[a-zA-Z0-9_\-]{20,}", re.IGNORECASE),
        re.compile(r"ghp_[a-zA-Z0-9]{20,}", re.IGNORECASE),
        re.compile(r"\b[A-Za-z0-9+/]{32,}={0,2}\b"),  # base64 secret tokens
    )

    def __init__(self) -> None:
        self._mask_regions_registry: dict[str, list[ScreenMaskRegion]] = {}

    def register_mask_region(
        self,
        session_id: str,
        box: BoundingBox,
        target_selector: str,
        mask_color: str = "#000000",
    ) -> ScreenMaskRegion:
        """Register a bounding box region that must be masked on screen captures."""
        region_id = f"mask-reg-{uuid.uuid4().hex[:12]}"
        region = ScreenMaskRegion(
            region_id=region_id,
            box=box,
            mask_color=mask_color,
            target_selector=target_selector,
        )
        if session_id not in self._mask_regions_registry:
            self._mask_regions_registry[session_id] = []
        self._mask_regions_registry[session_id].append(region)
        logger.info(
            "Registered screen mask region %s at (%d, %d, %d, %d) for session %s",
            region_id,
            box.x,
            box.y,
            box.width,
            box.height,
            session_id,
        )
        return region

    def list_mask_regions(self, session_id: str) -> list[ScreenMaskRegion]:
        """Fetch all registered screen mask regions for a session."""
        return list(self._mask_regions_registry.get(session_id, []))

    def redact_dom_tree(
        self,
        dom_html: str,
        custom_rules: tuple[DOMRedactionRule, ...] | None = None,
    ) -> tuple[str, int]:
        """Sanitize password inputs and secret tokens in DOM string before passing to LLM context."""
        rules = custom_rules or self.DEFAULT_DOM_RULES
        redacted_html = dom_html
        redactions_count = 0

        # 1. Redact matching element value attributes
        for rule in rules:
            rule_regex = re.compile(rule.selector_pattern, re.IGNORECASE)

            replacement = rule.replacement_value

            def _replace_element(
                match: re.Match[str],
                repl_val: str = replacement,
            ) -> str:
                nonlocal redactions_count
                elem_tag = match.group(0)
                if self.VALUE_ATTR_REGEX.search(elem_tag):
                    redactions_count += 1
                    return self.VALUE_ATTR_REGEX.sub(
                        rf"\g<1>{repl_val}\g<3>",
                        elem_tag,
                    )
                return elem_tag

            redacted_html = rule_regex.sub(_replace_element, redacted_html)

        # 2. Scrub raw technological secret patterns from general HTML text
        for token_pat in self.RAW_TOKEN_PATTERNS:
            matches = token_pat.findall(redacted_html)
            if matches:
                redactions_count += len(matches)
                redacted_html = token_pat.sub("<REDACTED_CREDENTIAL>", redacted_html)

        return redacted_html, redactions_count

    def execute_handover_scrub(
        self,
        session_id: str,
        dom_html: str,
    ) -> tuple[str, MaskingRedactionReport]:
        """Atomically scrub DOM and compile handover audit report when transferring control back to Agent."""
        sanitized_dom, nodes_redacted = self.redact_dom_tree(dom_html)
        regions = self.list_mask_regions(session_id)

        report = MaskingRedactionReport(
            session_id=session_id,
            masked_regions_count=len(regions),
            redacted_dom_nodes_count=nodes_redacted,
            observation_scrubbed=True,
            timestamp=time.time(),
        )
        logger.info(
            "Handover scrub completed for session %s: %d masked regions, %d redacted DOM nodes",
            session_id,
            len(regions),
            nodes_redacted,
        )
        return sanitized_dom, report
