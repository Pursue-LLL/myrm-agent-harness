"""ARIA tree renderer (Layer 4).

Formats EnhancedNode tree into text output (YAML or compact format).
Separates data from presentation (MVC principle).


[INPUT]

[OUTPUT]
- text: YAML or compact formatted string
- SnapshotMeta: ref count and token estimation
- truncate_snapshot: 按 token 预算Truncate snapshottext

[POS]
Layer 4 of the four-layer ARIA snapshot architecture.
Converts structured data to text representation for LLM consumption.
Includes post-processing utilities like text truncation.
"""

from __future__ import annotations

from .aria_types import EnhancedNode, SnapshotMeta

_CHARS_PER_TOKEN = 4


def render_to_yaml(
    nodes: list[EnhancedNode],
    *,
    compact: bool = False,
) -> tuple[str, SnapshotMeta]:
    """Render EnhancedNode tree to YAML or compact format.

    Args:
        nodes: EnhancedNode tree from aria_enhancer.
        compact: Use compact single-line format (e0:role at top-left).

    Returns:
        (text, metadata) where:
        - text: Formatted string for LLM consumption
        - metadata: SnapshotMeta with ref_count and estimated_tokens

    Notes:
        - YAML format: `- role "name" [ref=e0] at top-left`
        - Compact format: `e0:role at top-left`
        - Indentation preserves tree hierarchy in YAML mode
    """
    lines: list[str] = []
    ref_count = 0

    def _render_node(node: EnhancedNode) -> None:
        """Recursively render a single node."""
        nonlocal ref_count

        role = node.node.role
        name = node.node.name
        indent_str = "  " * node.node.indent
        position_suffix = f" {node.position}" if node.position else ""

        if node.ref_id:
            ref_count += 1
            if compact:
                lines.append(f"{node.ref_id}:{role}{position_suffix}")
            else:
                # Reconstruct attributes string
                attrs = node.node.attributes
                rest = " ".join(f"[{k}={v}]" for k, v in attrs.items()) if attrs else ""
                rest = f" {rest}" if rest else ""
                lines.append(f'{indent_str}- {role} "{name}" [ref={node.ref_id}]{position_suffix}{rest}')
        else:
            # Non-ref element
            if compact:
                # Compact mode: show as 'role "name"' without ref
                if name:
                    lines.append(f'{role} "{name}"')
            else:
                # Reconstruct original YAML line
                attrs = node.node.attributes
                rest = " ".join(f"[{k}={v}]" for k, v in attrs.items()) if attrs else ""
                rest = f" {rest}" if rest else ""
                if name:
                    lines.append(f'{indent_str}- {role} "{name}"{rest}')
                else:
                    lines.append(f'{indent_str}- {role} ""{rest}')

        # Recursively render children
        for child in node.children:
            _render_node(child)

    for node in nodes:
        _render_node(node)

    text = "\n".join(lines)
    estimated_tokens = max(len(text) // _CHARS_PER_TOKEN, 0) if text else 0
    meta = SnapshotMeta(ref_count=ref_count, estimated_tokens=estimated_tokens)

    return text, meta


def truncate_snapshot(text: str, max_tokens: int) -> tuple[str, bool]:
    """Legacy string-based fallback truncation."""
    if max_tokens <= 0:
        return text, False

    lines = text.split("\n")
    tokens_used = 0
    for i, line in enumerate(lines):
        tokens_used += max(len(line) // _CHARS_PER_TOKEN, 1)
        if tokens_used > max_tokens:
            remaining = len(lines) - i
            kept = "\n".join(lines[:i])
            return f"{kept}\n(... {remaining} more lines, truncated at ~{max_tokens} tokens)", True
    return text, False

def smart_truncate_snapshot(nodes: list[EnhancedNode], max_tokens: int, compact: bool = False) -> tuple[str, SnapshotMeta, bool]:
    """
    Intelligently truncate the ARIA snapshot tree to fit within max_tokens.
    Returns (rendered_yaml, metadata, was_truncated).
    """
    if max_tokens <= 0:
        yaml_text, meta = render_to_yaml(nodes, compact=compact)
        return yaml_text, meta, False

    from myrm_agent_harness.utils.tree_truncator import truncate_aria_tree
    truncated_nodes, was_truncated = truncate_aria_tree(nodes, max_tokens)
    yaml_text, meta = render_to_yaml(truncated_nodes, compact=compact)
    return yaml_text, meta, was_truncated
