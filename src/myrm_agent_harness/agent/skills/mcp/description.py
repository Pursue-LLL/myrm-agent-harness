"""L1 description resolution for MCP skills.

[INPUT]
- langchain_core.tools::BaseTool
- agent.skills.mcp.doc_rendering (POS: shared text helpers for L1/L2)

[OUTPUT]
- resolve_description(): user description > instructions first sentence > tool summary
- build_description_from_tools(): compact summary from up to three tool descriptions

[POS]
Pure L1 description policy. Kept out of the generator so the catalog text has one
implementation and the generator stays an orchestrator.
"""

from __future__ import annotations

from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.skills.mcp.doc_rendering import clean_markdown, truncate_to_sentence


def resolve_description(
    user_description: str,
    instructions: str | None,
    tools: list[BaseTool],
    server_name: str,
) -> str:
    """Resolve skill description with 3-tier priority.

    Priority: user_description > instructions > auto-generated from tools.
    """
    if user_description:
        return user_description.strip()

    if instructions:
        return truncate_to_sentence(clean_markdown(instructions), max_len=200)

    # The catalog's routing_rules already say when to select a skill; repeating an
    # imperative in every server's line contradicts "ask the user when several apply".
    return build_description_from_tools(tools, server_name).rstrip("。.")


def build_description_from_tools(tools: list[BaseTool], server_name: str) -> str:
    """Build a concise description from tool descriptions (for metadata)."""
    functions: list[str] = []
    for tool in tools:
        desc = getattr(tool, "description", "")
        if not desc:
            continue
        short = truncate_to_sentence(desc, max_len=80)
        if short:
            functions.append(short.rstrip("。."))

    if not functions:
        display = server_name.replace("_", " ").replace("-", " ").title()
        return f"{display} ({len(tools)} tools available)"

    joined = "; ".join(functions[:3])
    suffix = f" and {len(functions) - 3} more" if len(functions) > 3 else ""
    return f"MCP {server_name}: {joined}{suffix}"
