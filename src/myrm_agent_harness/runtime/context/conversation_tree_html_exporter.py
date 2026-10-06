"""Interactive HTML and Markdown exporter for tree-structured conversation graphs.

Provides self-contained interactive tree visualization and branch replay viewer
inspired by Pi Agent /export and /share capabilities without external dependencies.
"""

import html
import json

from myrm_agent_harness.runtime.context.conversation_tree_graph import (
    ConversationTreeGraph,
)


class ConversationTreeHtmlExporter:
    """Exports conversation DAG trees into interactive self-contained HTML documents."""

    def export_html(self, graph: ConversationTreeGraph, title: str = "Myrm Conversation Tree") -> str:
        """Generate a zero-dependency, self-contained interactive HTML visualization."""
        branches = graph.list_all_branches()
        bookmarks = graph.list_bookmarks()

        # Build serialized DAG payload for client-side viewer
        dag_payload = {
            "root_id": graph.root_id,
            "current_leaf_id": graph.current_leaf_id,
            "nodes": {
                n.node_id: {
                    "node_id": n.node_id,
                    "parent_id": n.parent_id,
                    "children_ids": n.children_ids,
                    "kind": n.kind.value,
                    "role": n.role,
                    "content": n.content,
                    "timestamp": n.timestamp,
                    "is_bookmarked": n.is_bookmarked,
                    "bookmark_note": n.bookmark_note,
                }
                for n in [graph.get_node(nid) for nid in graph._nodes]
                if n is not None
            },
            "branches": [
                {
                    "leaf_id": b.leaf_id,
                    "path_length": b.path_length,
                    "root_to_leaf_ids": b.root_to_leaf_ids,
                    "branch_name": b.branch_name,
                    "leaf_preview": b.leaf_preview,
                }
                for b in branches
            ],
        }

        escaped_title = html.escape(title)
        json_data = json.dumps(dag_payload)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escaped_title}</title>
<style>
  :root {{ --bg: #0f172a; --card: #1e293b; --text: #f8fafc; --accent: #38bdf8; --border: #334155; }}
  body {{ margin: 0; padding: 24px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--text); }}
  header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 16px; margin-bottom: 24px; }}
  h1 {{ margin: 0; font-size: 20px; }}
  .badge {{ background: var(--border); padding: 4px 10px; border-radius: 999px; font-size: 12px; }}
  .container {{ display: grid; grid-template-columns: 320px 1fr; gap: 24px; }}
  .sidebar {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }}
  .branch-btn {{ display: block; width: 100%; text-align: left; background: none; border: 1px solid var(--border); color: var(--text); padding: 10px; border-radius: 6px; margin-bottom: 8px; cursor: pointer; }}
  .branch-btn:hover, .branch-btn.active {{ background: #334155; border-color: var(--accent); }}
  .timeline {{ display: flex; flex-direction: column; gap: 16px; }}
  .msg-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }}
  .msg-header {{ display: flex; justify-content: space-between; font-size: 12px; color: #94a3b8; margin-bottom: 8px; }}
  .role-tag {{ font-weight: bold; text-transform: uppercase; }}
  .role-user {{ color: #38bdf8; }} .role-assistant {{ color: #4ade80; }} .role-tool {{ color: #fbbf24; }}
  .bookmark-star {{ color: #f59e0b; margin-left: 6px; }}
  pre {{ white-space: pre-wrap; word-break: break-word; margin: 0; font-family: monospace; font-size: 13px; }}
</style>
</head>
<body>
<header>
  <h1>🌿 {escaped_title}</h1>
  <div>
    <span class="badge">Nodes: {graph.total_nodes()}</span>
    <span class="badge">Branches: {len(branches)}</span>
    <span class="badge">Bookmarks: {len(bookmarks)}</span>
  </div>
</header>
<div class="container">
  <div class="sidebar">
    <h3>Branches & Paths</h3>
    <div id="branch-list"></div>
  </div>
  <div class="timeline" id="message-timeline"></div>
</div>
<script>
  const dag = {json_data};
  const branchList = document.getElementById('branch-list');
  const timeline = document.getElementById('message-timeline');

  function renderBranch(leafId) {{
    const branch = dag.branches.find(b => b.leaf_id === leafId) || dag.branches[0];
    if (!branch) return;

    document.querySelectorAll('.branch-btn').forEach(b => b.classList.toggle('active', b.dataset.id === leafId));
    timeline.innerHTML = '';

    branch.root_to_leaf_ids.forEach(nid => {{
      const node = dag.nodes[nid];
      if (!node) return;
      const card = document.createElement('div');
      card.className = 'msg-card';
      const roleClass = 'role-' + node.role;
      const star = node.is_bookmarked ? '⭐ ' + (node.bookmark_note || '') : '';
      card.innerHTML = `
        <div class="msg-header">
          <span class="role-tag ${{roleClass}}">${{node.role}} [${{node.kind}}]</span>
          <span>${{star}} ${{node.node_id}}</span>
        </div>
        <pre>${{node.content}}</pre>
      `;
      timeline.appendChild(card);
    }});
  }}

  dag.branches.forEach((b, i) => {{
    const btn = document.createElement('button');
    btn.className = 'branch-btn' + (i === 0 ? ' active' : '');
    btn.dataset.id = b.leaf_id;
    btn.innerHTML = `<strong>${{b.branch_name}}</strong><br><small>${{b.path_length}} msgs</small>`;
    btn.onclick = () => renderBranch(b.leaf_id);
    branchList.appendChild(btn);
  }});

  if (dag.branches.length > 0) {{
    renderBranch(dag.current_leaf_id || dag.branches[0].leaf_id);
  }}
</script>
</body>
</html>
"""

    def export_markdown_outline(self, graph: ConversationTreeGraph) -> str:
        """Render a concise text/markdown tree outline showing forks and depths."""
        lines: list[str] = [
            "# CONVERSATION TREE DAG OUTLINE",
            f"- Total Nodes: {graph.total_nodes()}",
            f"- Total Branches: {len(graph.list_all_branches())}",
            "",
            "## Branches Hierarchy",
        ]

        for b in graph.list_all_branches():
            lines.append(f"- **{b.branch_name}** ({b.path_length} nodes):")
            lines.append(f"  - Leaf Preview: `{b.leaf_preview}`")

        bookmarks = graph.list_bookmarks()
        if bookmarks:
            lines.append("")
            lines.append("## Starred Bookmarks")
            for bm in bookmarks:
                lines.append(f"- ⭐ `{bm.node_id}`: {bm.title} ({bm.note})")

        return "\n".join(lines)
