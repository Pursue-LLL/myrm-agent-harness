"""Self Healing mechanism for element locators.

Provides a fast, spatial-locality-based fallback when strict locators fail.
Uses BBox coordinates and local JS evaluation for O(1) performance.
Implements Semantic Veto to prevent dangerous mis-clicks.
"""

import logging

from patchright.async_api import Frame, FrameLocator, Locator, Page

from .aria_types import CURSOR_ROLES, RefInfo

logger = logging.getLogger(__name__)

# Dangerous words that trigger semantic veto (preventing a 'submit' from healing to a 'delete')
FORBIDDEN_WORDS = frozenset(
    {
        "delete",
        "cancel",
        "remove",
        "drop",
        "clear",
        "discard",
        "abort",
        "close",
        "unsubscribe",
        "删除",
        "取消",
        "移除",
        "清空",
        "丢弃",
        "退出",
        "关闭",
        "解绑",
        "解散",
    }
)

_HEAL_JS = """
(elements, args) => {
    const { origX, origY, origWidth, origHeight, origName, forbiddenWords, origRole } = args;

    let bestIndex = -1;
    let bestScore = Infinity;

    for (let i = 0; i < elements.length; i++) {
        const el = elements[i];

        // Basic visibility check
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) continue;
        const style = window.getComputedStyle(el);
        if (style.visibility === 'hidden' || style.display === 'none') continue;

        // Convert viewport coordinates to absolute page coordinates
        const centerX = rect.x + window.scrollX + rect.width / 2;
        const centerY = rect.y + window.scrollY + rect.height / 2;

        // 1. Morphological (IoU-like Shape Similarity)
        // If element width/height drastically changed, it's likely a different element.
        const widthRatio = Math.max(rect.width, origWidth) / Math.max(Math.min(rect.width, origWidth), 1);
        const heightRatio = Math.max(rect.height, origHeight) / Math.max(Math.min(rect.height, origHeight), 1);
        const shapePenalty = (widthRatio - 1) * 50 + (heightRatio - 1) * 50;

        // 2. Topological (Depth relative to a named/id ancestor)
        // In this fast JS evaluation, we approximate topology by checking role attribute or inferred tag mapping
        let inferredRole = el.getAttribute('role');
        if (!inferredRole) {
            const tag = el.tagName.toLowerCase();
            if (tag === 'a') inferredRole = 'link';
            else if (tag === 'input' || tag === 'textarea') {
                const type = el.getAttribute('type') || 'text';
                if (type === 'button' || type === 'submit') inferredRole = 'button';
                else if (type === 'checkbox') inferredRole = 'checkbox';
                else if (type === 'radio') inferredRole = 'radio';
                else inferredRole = 'textbox';
            }
            else if (tag === 'select') inferredRole = 'combobox';
            else if (tag === 'button') inferredRole = 'button';
            else inferredRole = tag;
        }
        const isTagMatch = origRole && inferredRole.toLowerCase() === origRole.toLowerCase();

        // Euclidean distance (still useful for local search)
        const distance = Math.sqrt(Math.pow(centerX - origX, 2) + Math.pow(centerY - origY, 2));

        // Spatial locality constraint: Allow up to 800px vertical shift for heavy ads insertion
        if (distance > 800) continue;

        // Semantic Veto Check
        const ariaLabel = (el.getAttribute('aria-label') || "").toLowerCase();
        const title = (el.getAttribute('title') || "").toLowerCase();
        const alt = (el.getAttribute('alt') || "").toLowerCase();
        const textContent = (el.textContent || el.innerText || "").toLowerCase();
        const combinedText = [textContent, ariaLabel, title, alt].join(" ");

        const origNameLower = (origName || "").toLowerCase();

        let origIsDangerous = false;
        let candIsDangerous = false;

        for (const word of forbiddenWords) {
            if (origNameLower.includes(word)) origIsDangerous = true;
            if (combinedText.includes(word)) candIsDangerous = true;
        }

        if (candIsDangerous && !origIsDangerous) {
            continue; // Semantic Veto Triggered!
        }

        // Scoring: Lower is better. Base is distance + shape penalty
        let score = distance + shapePenalty;

        // Semantic Bonus
        if (origNameLower && combinedText && combinedText.includes(origNameLower)) {
            score -= 300; // Strong bonus for text match (overrides distance)
        }

        // Tag Match Bonus
        if (isTagMatch) {
            score -= 100;
        }

        if (score < bestScore) {
            bestScore = score;
            bestIndex = i;
        }
    }

    // Return distance strictly for logging purposes, not the abstract score
    let finalDistance = 0.0;
    if (bestIndex !== -1) {
        const bestEl = elements[bestIndex];
        const rect = bestEl.getBoundingClientRect();
        const cx = rect.x + window.scrollX + rect.width / 2;
        const cy = rect.y + window.scrollY + rect.height / 2;
        finalDistance = Math.sqrt(Math.pow(cx - origX, 2) + Math.pow(cy - origY, 2));
    }

    return [bestIndex, finalDistance];
}
"""


class SelfHealer:
    """Heals broken locators using spatial coordinates and semantic safeguards."""

    @staticmethod
    async def heal(frame: Page | FrameLocator | Frame, ref_info: RefInfo) -> tuple[Locator | None, str | None, float]:
        """Try to heal a broken locator.

        Args:
            frame: Patchright Page, FrameLocator, or Frame instance where the element should be
            ref_info: The original RefInfo that failed

        Returns:
            Tuple of (Healed Locator or None, Healed Element Text or None, Distance)
        """
        if not ref_info.bbox:
            return None, None, 0.0

        orig_x = ref_info.bbox.centerX
        orig_y = ref_info.bbox.centerY
        orig_width = ref_info.bbox.width
        orig_height = ref_info.bbox.height

        try:
            if ref_info.role in CURSOR_ROLES:
                # For clickable/focusable, query a broad range of interactive elements
                candidates_locator = frame.locator(
                    "a, button, input, select, textarea, [onclick], [tabindex], [role='button'], [role='link'], [role='menuitem']"
                )
            else:
                candidates_locator = frame.get_by_role(ref_info.role)

            result = await candidates_locator.evaluate_all(
                _HEAL_JS,
                {
                    "origX": orig_x,
                    "origY": orig_y,
                    "origWidth": orig_width,
                    "origHeight": orig_height,
                    "origName": ref_info.name,
                    "forbiddenWords": list(FORBIDDEN_WORDS),
                    "origRole": ref_info.role,
                },
            )

            best_index = result[0] if isinstance(result, list) else -1
            best_distance = float(result[1]) if isinstance(result, list) and len(result) > 1 else 0.0

            if best_index != -1:
                healed_loc = candidates_locator.nth(best_index)

                # Try to get the new name for the healed locator
                healed_name = None
                try:
                    healed_name = await healed_loc.text_content(timeout=1000)
                    if healed_name:
                        healed_name = healed_name.strip()
                except Exception:
                    pass

                logger.info(
                    f"SelfHealer: Successfully healed locator for {ref_info.role} '{ref_info.name}'. New text: '{healed_name}'"
                )
                return healed_loc, healed_name, best_distance

        except Exception as e:
            logger.debug(f"SelfHealer: healing attempt failed: {e}")

        return None, None, 0.0
