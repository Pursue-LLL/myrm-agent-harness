"""Meta-test: BrowserSession mixin methods must be unique across the MRO.

BrowserSession composes many mixins; if two mixins define the same method, the
MRO (first-wins) silently shadows the others. That happened with a stub
`_ensure_components` in BrowserSessionPersistenceMixin shadowing the real
LifecycleMixin implementation, turning component initialization into a no-op.
This test fails fast if any mixin introduces a colliding method name — both
public and private (single-underscore) names, since the shadowing bug involved
a private method. Dunder names (``__init__`` etc.) are excluded: the aggregate
root intentionally defines its own, and Python resolves them specially.
"""

from collections import defaultdict

from myrm_agent_harness.toolkits.browser.session.browser_session import BrowserSession


def _public_and_private_methods(cls: type) -> dict[str, str]:
    """Map method names directly defined on ``cls`` to their qualified source."""
    methods: dict[str, str] = {}
    for name, attr in vars(cls).items():
        if name.startswith("__") or name.endswith("__"):
            continue
        if callable(attr) or isinstance(attr, property):
            methods[name] = f"{cls.__module__}.{cls.__qualname__}"
    return methods


def test_browser_session_mixin_methods_are_unique() -> None:
    method_sources: dict[str, list[str]] = defaultdict(list)
    # Iterate in MRO order so the first (winning) definition is recorded first.
    for cls in BrowserSession.__mro__:
        if cls.__module__ == "builtins":
            continue
        for name, source in _public_and_private_methods(cls).items():
            method_sources[name].append(source)

    collisions = {name: sources for name, sources in method_sources.items() if len(sources) > 1}
    assert not collisions, f"Mixin method shadowing detected: {collisions}"
