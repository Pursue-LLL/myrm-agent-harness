"""Vision Verifier component for Action-Verification Fusion.

[INPUT]
- langchain_core.language_models::BaseChatModel (POS: Vision LLM instance)
- patchright.async_api::Page (POS: Browser page)
- diff.fast_comparator::FastComparator (POS: dHash comparator)

[OUTPUT]
- VisionVerifier: Component that executes the 3-layer verification funnel.

[POS]
Implements the 3-layer funnel for verifying browser actions:
1. DOM Mutation Check (via page state or skipped if not available)
2. dHash Check (skips LLM if screen didn't change visually)
3. Vision LLM Check (scores 1-5 and provides reasoning)
"""

from __future__ import annotations

import base64
import contextlib
import logging
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage

from ..diff.fast_comparator import FastComparator

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from patchright.async_api import Page

logger = logging.getLogger(__name__)


class VisionVerifier:
    """3-Layer Vision Verifier for browser actions."""

    def __init__(self, llm: BaseChatModel | None = None) -> None:
        """Initialize VisionVerifier.

        Args:
            llm: Vision-capable LLM instance (e.g., gpt-4o-mini). If None, Layer 3 is disabled.
        """
        self._llm = llm
        self._comparator = FastComparator()

    async def verify_action(
        self,
        page: Page,
        baseline_screenshot: bytes,
        verify_goal: str,
    ) -> tuple[bool, str]:
        """Run the 3-layer verification funnel.

        Args:
            page: The current browser page.
            baseline_screenshot: Screenshot taken *before* the action.
            verify_goal: The user-defined goal to verify.

        Returns:
            (success, message): Tuple indicating if verification passed, and the reasoning/message.
        """
        # Layer 1: DOM Mutation Check (Optional, omitted here for simplicity as dHash covers visual changes)

        # Take new screenshot
        try:
            from ..utils.selectors import PASSWORD_FIELD_SELECTOR

            password_locator = page.locator(PASSWORD_FIELD_SELECTOR)
            new_screenshot = await page.screenshot(type="png", full_page=False, mask=[password_locator])
        except Exception as e:
            return False, f"Verification failed: Could not take new screenshot ({e})"

        # Layer 2: dHash Check
        try:
            # We need to write a quick wrapper or use FastComparator directly
            # FastComparator.compare expects base64 strings or bytes?
            # Let's check diff/fast_comparator.py
            b64_baseline = base64.b64encode(baseline_screenshot).decode("utf-8")
            b64_new = base64.b64encode(new_screenshot).decode("utf-8")

            result = self._comparator.compare(b64_baseline, b64_new)
            if result.similarity >= 0.99:
                return False, "Verification failed (Layer 2): The screen did not change visually after the action."
        except Exception as e:
            logger.warning("dHash comparison failed, falling back to Vision LLM: %s", e)

        # Layer 3: Vision LLM Check
        if self._llm is None:
            return True, "Action executed. (Vision verification skipped: No Vision LLM configured)."

        try:
            prompt = (
                f"You are a visual QA agent verifying a browser automation step.\n"
                f"Goal to verify: '{verify_goal}'\n\n"
                f"Look at the provided screenshot of the browser after the action was taken.\n"
                f"Did the action succeed in achieving the goal? Is the page in the expected state?\n"
                f"Score 1 to 5 (1=completely failed/blocked, 5=perfectly achieved).\n"
                f"Provide your response in exactly this format:\n"
                f"SCORE: <number>\n"
                f"REASON: <one sentence explanation>"
            )

            message = HumanMessage(
                content=[
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64_new}"},
                    },
                ]
            )

            response = await self._llm.ainvoke([message])
            content = str(response.content)

            # Parse SCORE and REASON
            score = 1  # Default to 1 (fail) if format is invalid
            reason = content
            for line in content.split("\n"):
                if line.startswith("SCORE:"):
                    with contextlib.suppress(ValueError):
                        score = int(line.replace("SCORE:", "").strip())
                elif line.startswith("REASON:"):
                    reason = line.replace("REASON:", "").strip()

            if score < 4:
                return False, f"Verification failed (Score {score}/5): {reason}"
            else:
                return True, f"Verification passed (Score {score}/5): {reason}"

        except Exception as e:
            return False, f"Verification failed (Layer 3 Error): Vision LLM call failed ({e})"
