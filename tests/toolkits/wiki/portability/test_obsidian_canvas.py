"""Unit tests for Obsidian canvas text extraction and wikilink parsing."""

import json
from pathlib import Path

from myrm_agent_harness.toolkits.wiki.portability import (
    extract_canvas_text_nodes,
    extract_wikilinks_from_markdown,
    resolve_one_hop_wikilinks,
)


def test_extract_canvas_text_nodes(tmp_path: Path):
    canvas_file = tmp_path / "architecture.canvas"
    canvas_payload = {
        "nodes": [
            {
                "id": "node-1",
                "type": "text",
                "text": "Microservice Gateway Architecture",
            },
            {
                "id": "node-2",
                "type": "file",
                "file": "specs/auth.md",
                "label": "Authentication Service Spec",
            },
            {
                "id": "node-3",
                "type": "link",
                "url": "https://example.com/api",
                "label": "API Docs",
            },
            {
                "id": "node-4",
                "type": "group",
                "label": "Core Cluster",
            },
        ],
        "edges": [],
    }
    canvas_file.write_text(json.dumps(canvas_payload), encoding="utf-8")

    nodes = extract_canvas_text_nodes(canvas_file)
    assert len(nodes) == 4

    types = {n.node_type for n in nodes}
    assert types == {"text", "file", "link", "group"}

    text_node = next(n for n in nodes if n.node_type == "text")
    assert text_node.content == "Microservice Gateway Architecture"

    file_node = next(n for n in nodes if n.node_type == "file")
    assert file_node.content == "specs/auth.md"
    assert file_node.label == "Authentication Service Spec"


def test_extract_wikilinks_from_markdown():
    text = """
    # Design Document
    Please refer to [[Database Schema]] and [[API Gateway|Gateway V2]].
    Also check [[Risk Policy#Section 2|Risk Rules]] for compliance.

    ```markdown
    Ignore [[Fake Link in Code Block]] here.
    ```

    Final note: [[Deployment Plan]].
    """
    links = extract_wikilinks_from_markdown(text)
    targets = [link.target for link in links]

    assert "Database Schema" in targets
    assert "API Gateway" in targets
    assert "Risk Policy" in targets
    assert "Deployment Plan" in targets
    assert "Fake Link in Code Block" not in targets

    alias_map = {link.target: link.alias for link in links}
    assert alias_map["API Gateway"] == "Gateway V2"
    assert alias_map["Risk Policy"] == "Risk Rules"


def test_resolve_one_hop_wikilinks(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "specs").mkdir()

    seed = vault / "seed.md"
    seed.write_text("See [[Auth Spec]] and [[billing_rule]].", encoding="utf-8")

    auth_file = vault / "specs" / "Auth Spec.md"
    auth_file.write_text("Auth specification details", encoding="utf-8")

    billing_file = vault / "Billing_Rule.md"
    billing_file.write_text("Billing rules details", encoding="utf-8")

    resolved = resolve_one_hop_wikilinks(seed, vault, case_insensitive=True)
    assert "Auth Spec" in resolved
    assert resolved["Auth Spec"] == auth_file

    assert "billing_rule" in resolved
    assert resolved["billing_rule"] == billing_file


def test_extract_canvas_edge_cases(tmp_path: Path):
    # Non-existent file
    assert extract_canvas_text_nodes(tmp_path / "missing.canvas") == []

    # Corrupted JSON
    corrupted = tmp_path / "corrupted.canvas"
    corrupted.write_text("{bad-json}", encoding="utf-8")
    assert extract_canvas_text_nodes(corrupted) == []

    # Non-dict payload
    non_dict = tmp_path / "array.canvas"
    non_dict.write_text("[1, 2, 3]", encoding="utf-8")
    assert extract_canvas_text_nodes(non_dict) == []

    # Invalid nodes container
    invalid_nodes = tmp_path / "bad_nodes.canvas"
    invalid_nodes.write_text(json.dumps({"nodes": "not-a-list"}), encoding="utf-8")
    assert extract_canvas_text_nodes(invalid_nodes) == []

    # Non-dict node entries inside list
    mixed_nodes = tmp_path / "mixed.canvas"
    mixed_nodes.write_text(json.dumps({"nodes": ["string-node", 123, None]}), encoding="utf-8")
    assert extract_canvas_text_nodes(mixed_nodes) == []


def test_wikilinks_and_resolve_edge_cases(tmp_path: Path):
    # Empty content
    assert extract_wikilinks_from_markdown("") == []

    # Seed does not exist or vault root invalid
    assert resolve_one_hop_wikilinks(tmp_path / "none.md", tmp_path) == {}
    seed = tmp_path / "empty_seed.md"
    seed.write_text("No wikilinks here", encoding="utf-8")
    assert resolve_one_hop_wikilinks(seed, tmp_path / "non_existent_vault") == {}

    # Seed without links
    assert resolve_one_hop_wikilinks(seed, tmp_path) == {}
