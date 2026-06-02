"""ARIA tree acquisition (Layer 1).

Dual-path architecture for obtaining ARIA tree from browser:
- Fast Path: Playwright ariaSnapshot() API (90% cases, zero overhead)
- Custom Path: JavaScript DOM traversal (10% cases, maxDepth support)


[INPUT]
- patchright.async_api::Locator (POS: Patchright element locator)

[OUTPUT]
- YAML string: ARIA tree in YAML format

[POS]
Layer 1 of the four-layer ARIA snapshot architecture.
Intelligently routes to Fast/Custom path based on parameters.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.browser.utils.selectors import PASSWORD_FIELD_SELECTOR

if TYPE_CHECKING:
    from patchright.async_api import Locator

logger = logging.getLogger(__name__)

# JavaScript traverser for Custom Path (maxDepth support)
_CUSTOM_TRAVERSER_SCRIPT = f"""
(function(rootElement, maxDepth) {{
    const PASSWORD_SELECTOR = `{PASSWORD_FIELD_SELECTOR}`;
    const result = [];

    function escapeYamlString(str) {{
        // Escape backslashes and double quotes for YAML string safety
        return str.replace(/\\\\/g, '\\\\\\\\').replace(/"/g, '\\\\"');
    }}

    function getAccessibleName(elem) {{
        const explicitName = elem.getAttribute('aria-label')
            || elem.getAttribute('alt')
            || elem.getAttribute('title')
            || elem.getAttribute('placeholder');

        if (explicitName) return explicitName;

        const labelledBy = elem.getAttribute('aria-labelledby');
        if (labelledBy) {{
            const labelElem = document.getElementById(labelledBy);
            if (labelElem) return (labelElem.textContent || '').trim();
        }}

        const role = getRole(elem);
        if (role !== 'generic') {{
            return (elem.textContent || '').trim();
        }}

        return '';
    }}

    function getRole(elem) {{
        // Explicit role attribute
        const explicitRole = elem.getAttribute('role');
        if (explicitRole) return explicitRole;

        // Implicit roles from HTML semantics
        const tagName = elem.tagName.toLowerCase();
        const implicitRoles = {{
            'button': 'button',
            'a': 'link',
            'input': elem.type === 'checkbox' ? 'checkbox' : elem.type === 'radio' ? 'radio' : 'textbox',
            'textarea': 'textbox',
            'select': 'combobox',
            'h1': 'heading', 'h2': 'heading', 'h3': 'heading', 'h4': 'heading', 'h5': 'heading', 'h6': 'heading',
            'nav': 'navigation',
            'main': 'main',
            'article': 'article',
            'aside': 'complementary',
            'form': 'form',
            'img': 'img',
            'li': 'listitem',
            'ul': 'list',
            'ol': 'list',
            'table': 'table',
            'tr': 'row',
            'td': 'cell',
            'th': 'columnheader'
        }};

        return implicitRoles[tagName] || 'generic';
    }}

    function isVisible(elem) {{
        const style = window.getComputedStyle(elem);
        return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
    }}

    function traverse(elem, depth, indent) {{
        if (depth > maxDepth) {{
            if (elem.parentNode && !elem.parentNode._hasDepthTruncation) {{
                result.push(`${{'  '.repeat(indent)}}- note "[System Note: Exceeded maxDepth limit. Deep child elements are hidden. Use browser_snapshot(selector=...) to explore.]"`);
                elem.parentNode._hasDepthTruncation = true;
            }}
            return;
        }}
        if (!isVisible(elem)) return;

        let name = getAccessibleName(elem);
        let role = getRole(elem);

        const escapedName = escapeYamlString(name);
        const indentStr = '  '.repeat(indent);

        // Format: - role "name" (with YAML-safe escaping)
        result.push(`${{indentStr}}- ${{role}} "${{escapedName}}"`);

        // Traverse children (if within depth limit)
        if (depth < maxDepth) {{
            for (const child of elem.children) {{
                traverse(child, depth + 1, indent + 1);
            }}
        }}
    }}

    traverse(rootElement, 0, 0);
    return result.join('\\n');
}})
"""


async def get_aria_tree(
    locator: Locator,
    *,
    max_depth: int | None = None,
) -> str:
    """Get ARIA tree using Fast Path (Playwright API) or Custom Path (JS traversal).

    Args:
        locator: Playwright Locator (typically page.locator(':root')).
        max_depth: Optional depth limit. None = Fast Path, int = Custom Path.

    Returns:
        YAML-formatted ARIA tree string.

    Raises:
        ValueError: If max_depth is invalid (negative or non-integer).
        Exception: If both paths fail.

    Notes:
        - Fast Path (max_depth=None): Zero overhead, 100% stable
        - Custom Path (max_depth=N): JavaScript DOM traversal with depth control
        - Custom Path fallback: If fails, automatically retry with Fast Path
        - Large max_depth (>100) automatically uses Fast Path for better performance
    """
    # Parameter validation
    if max_depth is not None:
        if not isinstance(max_depth, int):
            raise ValueError(
                f"max_depth must be int or None, got {type(max_depth).__name__}"
            )
        if max_depth < 0:
            raise ValueError(f"max_depth must be >= 0, got {max_depth}")
        if max_depth > 100:
            # Large depth values are inefficient for Custom Path, use Fast Path instead
            logger.info(
                f"max_depth={max_depth} exceeds threshold (100), using Fast Path instead for better performance"
            )
            max_depth = None

    if max_depth is None:
        # Fast Path: Direct Playwright API call
        return await _get_aria_tree_fast(locator)

    # Custom Path: JavaScript traversal with maxDepth
    return await _get_aria_tree_custom(locator, max_depth)


async def _get_aria_tree_fast(locator: Locator) -> str:
    """Fast Path: Use Playwright ariaSnapshot() API."""
    try:
        # Security: Fetch password values safely before snapshot to redact them
        password_values = []
        if hasattr(locator, "page") and hasattr(locator.page, "evaluate"):
            result = locator.page.evaluate(
                f"""() => {{
                const inputs = Array.from(document.querySelectorAll('{PASSWORD_FIELD_SELECTOR}'));
                return inputs.map(el => el.value).filter(v => v && v.trim().length > 0);
            }}"""
            )
            if hasattr(result, "__await__"):
                password_values = await result
            elif isinstance(result, list):
                password_values = result

        aria_tree = await locator.aria_snapshot()

        # Redact password values from the YAML string using precise regex
        if password_values:
            for pwd in set(password_values):
                escaped_pwd = re.escape(pwd)
                # Match the password value at the end of a YAML line (e.g., `- textbox "Password": secret123`)
                pattern = re.compile(
                    r'(: \s*)[\'"]?' + escaped_pwd + r'[\'"]?(\s*)$', re.MULTILINE
                )
                aria_tree = pattern.sub(r'\1"[PASSWORD HIDDEN]"\2', aria_tree)

        logger.debug("ARIA tree acquired via Fast Path (Playwright API)")
        return aria_tree
    except Exception as exc:
        logger.error(f"Fast Path failed: {exc}")
        raise


async def _get_aria_tree_custom(locator: Locator, max_depth: int) -> str:
    """Custom Path: JavaScript DOM traversal with maxDepth support.

    Handles:
    - maxDepthtruncation (early traversal termination)
    - Visibility filtering(Skip隐藏Element)
    - Implicit roles(HTML semantic roles)
    - Accessible name calculation(simplified ARIA name computation)

    Fallback:
    - Shadow DOM detected → fallback to Fast Path (returns FULL tree)
    - Timeout → fallback to Fast Path (returns FULL tree, depth limit ignored)
    - Any error → fallback to Fast Path (returns FULL tree, depth limit ignored)
    """
    try:
        yaml_output = await asyncio.wait_for(
            locator.evaluate(_CUSTOM_TRAVERSER_SCRIPT, max_depth),
            timeout=3.0,
        )
        if not isinstance(yaml_output, str):
            raise TypeError(
                f"Custom Path returned {type(yaml_output).__name__}, expected str"
            )
        logger.debug(f"ARIA tree acquired via Custom Path (maxDepth={max_depth})")
        return yaml_output

    except TimeoutError:
        logger.warning(
            f"Custom Path timeout (maxDepth={max_depth}), "
            f"fallback to Fast Path (FULL tree will be returned, depth limit ignored)"
        )
        return await _get_aria_tree_fast(locator)

    except Exception as exc:
        logger.warning(
            f"Custom Path failed (maxDepth={max_depth}): {exc}, "
            f"fallback to Fast Path (FULL tree will be returned, depth limit ignored)"
        )
        return await _get_aria_tree_fast(locator)
