"""DOM stability detection JavaScript generator.


[INPUT]
- functools::lru_cache (POS: function cache)

[OUTPUT]
- generate_dom_stable_js: generate DOM stability detection JavaScript (cached)

[POS]
DOM stability detection JavaScript generator.
Generated JS code monitors DOM changes via MutationObserver,
supports Shadow DOM recursive observation, animation attribute smart filtering, and race condition protection.
"""

from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=32)
def generate_dom_stable_js(max_ms: int, quiet_ms: int) -> str:
    """Generate the DOM stability detection JavaScript (cached).

    Key features:
    1. Filters animation attributes (style, class, aria-*) to reduce false positives
    2. Observes childList + subtree (structural changes)
    3. Selectively observes attributes (excludes animation-related ones)
    4. Shadow DOM support: recursively observes all shadow roots
    5. Race protection: the timer starts only after observe() has been called
    6. Cache optimized: identical parameters reuse the generated JavaScript
    """
    return f"""
    (function() {{
        const startTime = performance.now();

        return new Promise((resolve) => {{
            if (!document.body) {{
                setTimeout(() => {{
                    resolve({{
                        reason: 'nobody',
                        elapsed_ms: Math.round(performance.now() - startTime),
                        mutation_count: 0,
                        reset_count: 0,
                        shadow_count: 0
                    }});
                }}, {max_ms});
                return;
            }}

            const IGNORED_ATTRS = new Set([
                'style',
                'class',
                'data-hover',
                'aria-busy',
                'aria-live',
                'data-loading',
            ]);

            let timer = null;
            let capTimer = null;
            let mutationCount = 0;
            let resetCount = 0;
            const observers = [];
            let shadowCount = 0;

            const done = (reason) => {{
                clearTimeout(timer);
                clearTimeout(capTimer);
                observers.forEach(obs => obs.disconnect());

                const elapsed = Math.round(performance.now() - startTime);
                resolve({{
                    reason,
                    elapsed_ms: elapsed,
                    mutation_count: mutationCount,
                    reset_count: resetCount,
                    shadow_count: shadowCount
                }});
            }};

            const resetQuiet = () => {{
                clearTimeout(timer);
                resetCount++;
                timer = setTimeout(() => done('quiet'), {quiet_ms});
            }};

            const hasRelevantMutation = (mutations) => {{
                for (const m of mutations) {{
                    mutationCount++;

                    if (m.type === 'childList') {{
                        if (m.addedNodes && m.addedNodes.length > 0) {{
                            m.addedNodes.forEach(node => {{
                                if (node.nodeType === 1) {{
                                    observeShadowDOM(node);
                                }}
                            }});
                        }}
                        return true;
                    }}

                    if (m.type === 'attributes') {{
                        const attrName = m.attributeName;
                        if (attrName && !IGNORED_ATTRS.has(attrName)) {{
                            return true;
                        }}
                    }}
                }}
                return false;
            }};

            const observeShadowDOM = (root) => {{
                const walker = document.createTreeWalker(
                    root,
                    NodeFilter.SHOW_ELEMENT,
                    null
                );

                let node;
                while (node = walker.nextNode()) {{
                    if (node.shadowRoot) {{
                        shadowCount++;
                        const shadowObs = new MutationObserver((mutations) => {{
                            if (hasRelevantMutation(mutations)) {{
                                resetQuiet();
                            }}
                        }});

                        shadowObs.observe(node.shadowRoot, {{
                            childList: true,
                            subtree: true,
                            attributes: true,
                            attributeOldValue: false
                        }});

                        observers.push(shadowObs);
                        observeShadowDOM(node.shadowRoot);
                    }}
                }}
            }};

            const mainObs = new MutationObserver((mutations) => {{
                if (hasRelevantMutation(mutations)) {{
                    resetQuiet();
                }}
            }});

            mainObs.observe(document.body, {{
                childList: true,
                subtree: true,
                attributes: true,
                attributeOldValue: false
            }});

            observers.push(mainObs);
            observeShadowDOM(document.body);

            resetQuiet();
            capTimer = setTimeout(() => done('capped'), {max_ms});
        }});
    }})()
    """
