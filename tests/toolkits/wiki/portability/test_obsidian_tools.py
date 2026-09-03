"""Unit tests for Obsidian Vault agent integration tools."""

import json
from pathlib import Path

from myrm_agent_harness.toolkits.wiki.portability.obsidian_tools import (
    create_obsidian_tools,
)


def test_create_obsidian_tools_unbound():
    tools = create_obsidian_tools(lambda: None)
    assert len(tools) == 3

    search_tool, read_tool, inbox_tool = tools
    assert search_tool.name == "obsidian_vault_search"
    assert read_tool.name == "obsidian_vault_read"
    assert inbox_tool.name == "obsidian_inbox_write"

    assert "No Obsidian vault currently bound" in search_tool.invoke({"query": "anything"})
    assert "No Obsidian vault currently bound" in read_tool.invoke({"relative_path": "note.md"})
    assert "No Obsidian vault currently bound" in inbox_tool.invoke(
        {"title": "Note", "content": "Content"}
    )


def test_obsidian_vault_search_and_read(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()

    # Hidden folder should be ignored
    hidden = vault / ".hidden"
    hidden.mkdir()
    (hidden / "secret.md").write_text("Secret query target", encoding="utf-8")

    # Regular markdown file
    note1 = vault / "Roadmap.md"
    note1.write_text("# Project Roadmap\nDiscusses authentication and payments.", encoding="utf-8")

    # Linked neighbor file
    note2 = vault / "Payments.md"
    note2.write_text("# Payment Gateway\nDetails about Stripe integration.", encoding="utf-8")

    # Markdown linking to Payments
    note1.write_text("# Project Roadmap\nSee [[Payments]] for billing details.", encoding="utf-8")

    # Canvas file
    canvas_file = vault / "Architecture.canvas"
    canvas_file.write_text(
        json.dumps({
            "nodes": [
                {"id": "n1", "type": "text", "text": "PostgreSQL database primary"},
                {"id": "n2", "type": "group", "label": "Infrastructure Group"},
            ]
        }),
        encoding="utf-8",
    )

    tools = create_obsidian_tools(lambda: str(vault))
    search_tool, read_tool, inbox_tool = tools

    # Search by filename
    search_res = search_tool.invoke({"query": "Roadmap"})
    assert "Found 1 matches" in search_res
    assert "Roadmap.md" in search_res

    # Search by markdown content
    search_content = search_tool.invoke({"query": "billing"})
    assert "Found 1 matches" in search_content
    assert "Roadmap.md" in search_content

    # Search inside canvas text node
    search_canvas = search_tool.invoke({"query": "PostgreSQL"})
    assert "Found 1 matches" in search_canvas
    assert "Architecture.canvas" in search_canvas

    # Search hidden file should not match
    search_hidden = search_tool.invoke({"query": "Secret"})
    assert "No matches found" in search_hidden

    # Read markdown without extension (fallback)
    read_res = read_tool.invoke({"relative_path": "Roadmap", "expand_wikilinks": True})
    assert "# Project Roadmap" in read_res
    assert "Linked Notes (1-hop):" in read_res
    assert "Payments" in read_res

    # Read canvas
    read_canvas = read_tool.invoke({"relative_path": "Architecture.canvas"})
    assert "# Canvas: Architecture.canvas" in read_canvas
    assert "## Group: Infrastructure Group" in read_canvas
    assert "[Text] PostgreSQL database primary" in read_canvas


def test_obsidian_inbox_write(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()

    # Direct write without approval requester
    tools = create_obsidian_tools(lambda: str(vault), inbox_folder_name="_Inbox")
    _, _, inbox_tool = tools

    res = inbox_tool.invoke({"title": "Daily Standup", "content": "- Progress made on tasks."})
    assert "Successfully written to" in res
    assert "_Inbox/Daily Standup.md" in res

    inbox_file = vault / "_Inbox" / "Daily Standup.md"
    assert inbox_file.is_file()
    assert "- Progress made on tasks." in inbox_file.read_text(encoding="utf-8")

    # Write with approval requester
    recorded_actions: list[dict] = []

    def mock_approval(data: dict) -> str:
        recorded_actions.append(data)
        return "approval-req-12345"

    tools_with_approval = create_obsidian_tools(
        lambda: str(vault),
        inbox_folder_name="_Inbox",
        approval_requester=mock_approval,
    )
    _, _, gated_inbox_tool = tools_with_approval

    gated_res = gated_inbox_tool.invoke({"title": "Q3 Goals", "content": "- Achieve OKRs."})
    assert "approval-req-12345" in gated_res
    assert len(recorded_actions) == 1
    assert recorded_actions[0]["action"] == "obsidian_inbox_write"
    assert recorded_actions[0]["title"] == "Q3 Goals"
