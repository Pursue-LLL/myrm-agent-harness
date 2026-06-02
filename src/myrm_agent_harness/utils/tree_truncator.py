"""
Tree Truncator (Smart Budget-Aware Truncation)
Provides generic utilities to intelligently truncate tree structures (HTML/DOM)
based on token/character budgets and semantic weighting, guaranteeing perfectly closed tags
and avoiding LLM parser hallucinations.
"""

import copy
from dataclasses import replace
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup, NavigableString, Tag  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.browser.snapshot.aria_types import EnhancedNode


def _get_html_weight(node: Tag) -> float:
    """Assigns semantic budget weight to HTML tags. Higher weight gets more budget."""
    name = getattr(node, "name", "").lower()
    if name in {"main", "article", "section", "h1", "h2", "h3", "dialog"}:
        return 2.0
    if name in {"p", "ul", "ol", "table", "tbody", "tr", "button", "a"}:
        return 1.2
    if name in {"nav", "aside", "footer", "script", "style", "head"}:
        return 0.2
    return 1.0


def _truncate_html_leaf(node: Tag, remaining_budget: int) -> None:
    """Truncates the inner text of a node and appends a truncated marker."""
    original_text = node.get_text(strip=True)
    node.clear()

    marker = " [TRUNCATED]"
    keep_chars = max(0, remaining_budget - len(marker))

    if keep_chars > 0 and len(original_text) > keep_chars:
        node.append(NavigableString(original_text[:keep_chars] + marker))
    else:
        node.append(NavigableString(marker))


def truncate_html_soup(soup: BeautifulSoup, max_chars: int) -> tuple[BeautifulSoup, bool]:
    """
    Intelligently truncate an HTML DOM tree to fit within max_chars.
    Uses semantic weighting and iterative allocation to preserve important nodes
    and perfectly closed tags.
    """
    # Defensive deep copy to prevent mutating the original agent memory / artifacts
    soup_copy = BeautifulSoup(str(soup), 'lxml')

    total_len = len(str(soup_copy))
    if total_len <= max_chars:
        return soup_copy, False

    stack: list[tuple[Tag, int]] = [(soup_copy, max_chars)]
    was_truncated = False

    while stack:
        node, budget = stack.pop()

        node_str = str(node)
        node_size = len(node_str)

        if node_size <= budget:
            continue

        was_truncated = True
        children = [c for c in node.children if isinstance(c, Tag)]

        if not children:
            _truncate_html_leaf(node, budget)
            continue

        if len(children) == 1:
            stack.append((children[0], budget))
            continue

        inner_html_size = sum(len(str(c)) for c in children)
        tag_overhead = node_size - inner_html_size

        available_budget = budget - tag_overhead
        if available_budget <= 0:
            _truncate_html_leaf(node, budget)
            continue

        # Semantic proportional allocation
        total_weight_mass = 0.0
        child_metrics = []

        for c in children:
            c_size = len(str(c))
            c_weight = _get_html_weight(c)
            mass = c_size * c_weight
            total_weight_mass += mass
            child_metrics.append((c, c_size, mass))

        for c, c_size, mass in child_metrics:
            if total_weight_mass > 0:
                c_budget = int(available_budget * (mass / total_weight_mass))
            else:
                c_budget = int(available_budget / len(children))

            if c_budget < 50:
                # Tail-cut / prune low budget children
                c.decompose()
            elif c_budget < c_size:
                stack.append((c, c_budget))

    return soup_copy, was_truncated


def _get_aria_weight(role: str) -> float:
    role = role.lower()
    if role in {"main", "article", "dialog", "application", "region"}:
        return 2.0
    if role in {"button", "link", "textbox", "searchbox", "combobox", "listbox", "checkbox", "radio"}:
        return 1.5
    if role in {"navigation", "banner", "contentinfo", "complementary"}:
        return 0.2
    return 1.0


def _compute_aria_sizes(nodes: tuple['EnhancedNode', ...]) -> dict[int, int]:
    sizes: dict[int, int] = {}

    def _visit(node: 'EnhancedNode') -> int:
        my_size = len(node.node.role) + len(node.node.name) + 10
        if node.ref_id:
            my_size += len(node.ref_id) + 5
        child_size = sum(_visit(c) for c in node.children)
        total = my_size + child_size
        sizes[id(node)] = total
        return total

    for n in nodes:
        _visit(n)
    return sizes


def truncate_aria_tree(nodes: list['EnhancedNode'], max_tokens: int) -> tuple[list['EnhancedNode'], bool]:
    """
    Intelligently truncate an ARIA tree to fit within max_tokens.
    Returns a new deeply-copied truncated tree tuple.
    """
    chars_per_token = 4
    max_chars = max_tokens * chars_per_token

    sizes = _compute_aria_sizes(tuple(nodes))
    total_size = sum(sizes[id(n)] for n in nodes)

    if total_size <= max_chars:
        return nodes, False

    def _truncate_node(node: 'EnhancedNode', budget: int) -> 'EnhancedNode | None':
        node_size = sizes[id(node)]
        if node_size <= budget:
            return node

        my_overhead = len(node.node.role) + len(node.node.name) + 10
        if node.ref_id:
            my_overhead += len(node.ref_id) + 5

        available = budget - my_overhead

        # Deep copy AriaNode to prevent mutation
        new_aria = copy.copy(node.node)
        new_aria.children = []  # We don't use this directly anyway, EnhancedNode does

        if available <= 0 or not node.children:
            marker = " [TRUNCATED]"
            keep = max(0, budget - len(marker))
            if new_aria.name and keep > 0 and len(new_aria.name) > keep:
                new_aria.name = new_aria.name[:keep] + marker
            else:
                new_aria.name = marker
            return replace(node, node=new_aria, children=())

        if len(node.children) == 1:
            child = _truncate_node(node.children[0], available)
            new_children = (child,) if child else ()
            return replace(node, node=new_aria, children=new_children)

        child_metrics = []
        total_mass = 0.0
        for c in node.children:
            c_size = sizes[id(c)]
            c_weight = _get_aria_weight(c.node.role)
            mass = c_size * c_weight
            total_mass += mass
            child_metrics.append((c, c_size, mass))

        new_children_list = []
        for c, c_size, mass in child_metrics:
            if total_mass > 0:
                c_budget = int(available * (mass / total_mass))
            else:
                c_budget = int(available / len(node.children))

            if c_budget < 20:
                pass # Drop
            elif c_budget < c_size:
                truncated_c = _truncate_node(c, c_budget)
                if truncated_c:
                    new_children_list.append(truncated_c)
            else:
                new_children_list.append(c)

        return replace(node, node=new_aria, children=tuple(new_children_list))

    total_mass = sum(sizes[id(n)] * _get_aria_weight(n.node.role) for n in nodes)
    new_nodes = []

    for n in nodes:
        n_size = sizes[id(n)]
        mass = n_size * _get_aria_weight(n.node.role)
        n_budget = int(max_chars * (mass / total_mass)) if total_mass > 0 else int(max_chars / len(nodes))

        if n_budget < 20:
            continue
        if n_budget < n_size:
            tn = _truncate_node(n, n_budget)
            if tn:
                new_nodes.append(tn)
        else:
            new_nodes.append(n)

    return new_nodes, True
