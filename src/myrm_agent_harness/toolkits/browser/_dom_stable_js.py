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
    """GenerateDOMstable性检测JavaScript（Cache）.

    关Key特性：
    1. Filter动画Property（style, class, aria-*）减少假阳性
    2. 监听childList + subtree（结构变化）
    3. 选择性监听attributes（Excludes动画related）
    4. Shadow DOMSupport：recursive监听AllshadowRoot
    5. 竞态防护：observe()后才Start计时器
    6. Cacheoptimized：sameParameter复用Generate JavaScript
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
