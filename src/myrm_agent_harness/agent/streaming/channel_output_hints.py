"""Per-channel output format hints — channel-aware output guidance for the agent.

Resolves channel-specific output format prompts that steer LLMs toward
generating content appropriate for the current delivery platform.

Architecture (symmetric with model_discipline.py):
    model_discipline  → per-model behavior guidance (based on LLM family)
    channel_output_hints → per-channel format guidance (based on delivery channel)

Both are fixed text (determined at init time), fully KV-Cache-safe.

Design rationale:
    The existing RenderStyle system performs post-hoc format downgrade (e.g. strip
    markdown tables after LLM generates them). Channel hints complement this with
    pre-hoc guidance — telling the LLM upfront what the platform supports, so it
    generates appropriate content from the start. Together they form a "dual insurance"
    strategy: hint guides + renderer safeguards.

See: agent/context_management/PROMPT_CACHE_PRACTICE.md §2.2

[INPUT]
- None (pure data module)

[OUTPUT]
- resolve_channel_output_hint(): channel name → hint string (empty if no match)

[POS]
Per-channel output format hints. Provides channel-aware prompt guidance to help
LLMs generate content that matches the delivery platform's rendering capabilities.
Framework-level auto-injection, symmetric with execution discipline.
"""

from __future__ import annotations

# Channel output hints: concise platform guidance (3-5 sentences each).
# Designed to be appended to system_prompt at agent initialization.
# Keys match channel_name values used throughout the system.
CHANNEL_OUTPUT_HINTS: dict[str, str] = {
    "web_chat": (
        "\n\n[Output Format] You are in a browser-based chat UI. "
        "Full Markdown is supported — headings, bold, italic, code blocks, "
        "tables, LaTeX math ($$...$$), and Mermaid diagrams all render natively. "
        "Use rich formatting to maximize clarity and readability."
    ),
    "telegram": (
        "\n\n[Output Format] You are on Telegram. "
        "Supported: **bold**, *italic*, `inline code`, ```code blocks```, "
        "[links](url), and ~~strikethrough~~. "
        "NO table syntax — use bullet lists or key: value pairs instead. "
        "Keep messages concise and chat-friendly."
    ),
    "feishu": (
        "\n\n[Output Format] You are on Feishu (Lark). "
        "Markdown is supported — bold, italic, code blocks, links, and tables work. "
        "Keep formatting clean and professional."
    ),
    "discord": (
        "\n\n[Output Format] You are in a Discord server. "
        "Markdown is supported — bold, italic, code blocks, links, and "
        "~~strikethrough~~ work. Tables do NOT render — use lists instead. "
        "Messages over 2000 chars are split automatically."
    ),
    "slack": (
        "\n\n[Output Format] You are in a Slack workspace. "
        "Slack uses mrkdwn (not standard Markdown): *bold*, _italic_, "
        "`code`, ```code blocks```, and <url|text> links. "
        "NO tables or headings — use bullet lists and bold labels."
    ),
    "whatsapp": (
        "\n\n[Output Format] You are on WhatsApp. "
        "Markdown does NOT render — use plain text only. "
        "No tables, no code fences, no headings. "
        "Keep responses concise and conversational."
    ),
    "wecom": (
        "\n\n[Output Format] You are on WeCom (企业微信). "
        "Markdown is supported — bold, links, and code blocks work. "
        "Keep messages professional and structured."
    ),
    "dingtalk": (
        "\n\n[Output Format] You are on DingTalk. "
        "Markdown is supported — bold, italic, links, code blocks, and "
        "ordered/unordered lists work. Keep messages structured."
    ),
    "teams": (
        "\n\n[Output Format] You are in Microsoft Teams. "
        "Markdown is supported — bold, italic, code blocks, links, "
        "tables, and lists all render correctly. Use rich formatting."
    ),
    "matrix": (
        "\n\n[Output Format] You are in a Matrix room. "
        "Markdown is supported and auto-converted to HTML — bold, italic, "
        "code blocks, and links work. Tables may not render well in all clients."
    ),
    "googlechat": (
        "\n\n[Output Format] You are in Google Chat. "
        "Only basic formatting works: *bold*, _italic_, and `code`. "
        "NO tables, NO headings, NO links syntax. Use plain text with structure."
    ),
    "signal": (
        "\n\n[Output Format] You are on Signal. "
        "Markdown does NOT render — use plain text only. "
        "Keep messages concise and natural."
    ),
    "sms": (
        "\n\n[Output Format] You are communicating via SMS. "
        "Plain text only — no formatting. Messages are limited in length, "
        "so be extremely brief and direct."
    ),
    "email": (
        "\n\n[Output Format] You are communicating via email. "
        "Write clear, well-structured responses in plain text. "
        "Use spacing and indentation for readability. "
        "Keep responses complete but concise."
    ),
    "cron": (
        "\n\n[Output Format] You are running as a scheduled job. "
        "Output structured plain text suitable for automated processing "
        "and delivery to messaging platforms. Avoid complex formatting "
        "like tables and code fences."
    ),
    "mattermost": (
        "\n\n[Output Format] You are in a Mattermost workspace. "
        "Full Markdown is supported — headings, bold, italic, code blocks, "
        "tables, and links all render correctly."
    ),
    "onebot": (
        "\n\n[Output Format] You are on a chat platform via OneBot protocol. "
        "Basic Markdown is supported. Keep messages chat-friendly and concise."
    ),
    "qq": (
        "\n\n[Output Format] You are on QQ. "
        "Basic Markdown is supported. Keep messages chat-friendly and concise."
    ),
    "wechat": (
        "\n\n[Output Format] You are on WeChat. "
        "Plain text only — no Markdown rendering. "
        "Keep messages concise and conversational."
    ),
    "wechat_official": (
        "\n\n[Output Format] You are on a WeChat Official Account. "
        "Plain text only — no Markdown rendering. "
        "Keep messages concise and informative."
    ),
    "wecom_aibot": (
        "\n\n[Output Format] You are on WeCom AI Bot (企业微信). "
        "Markdown is supported — bold, links, and code blocks work. "
        "Keep messages professional and structured."
    ),
    "line": (
        "\n\n[Output Format] You are on LINE. "
        "Plain text only — no Markdown rendering. "
        "Keep messages concise and conversational."
    ),
    "irc": (
        "\n\n[Output Format] You are in an IRC channel. "
        "Plain text only — no Markdown. Keep messages short and direct."
    ),
    "imessage": (
        "\n\n[Output Format] You are on iMessage. "
        "Plain text only — no Markdown rendering. "
        "Keep messages concise as they appear as text bubbles."
    ),
    "voice": (
        "\n\n[Output Format] Your response will be read aloud via text-to-speech. "
        "Use natural, conversational language. Avoid lists, bullet points, "
        "code blocks, URLs, special characters, and any visual formatting. "
        "Speak as you would to a person in conversation."
    ),
    "webhook": (
        "\n\n[Output Format] You are responding via webhook. "
        "Standard Markdown formatting is supported."
    ),
    "api_server": (
        "\n\n[Output Format] You are responding through an API endpoint. "
        "The rendering layer is unknown — use plain text without Markdown "
        "formatting for maximum compatibility."
    ),
    "zalo": (
        "\n\n[Output Format] You are on Zalo. "
        "Plain text only — no Markdown. Keep messages concise."
    ),
}


def resolve_channel_output_hint(channel_name: str | None) -> str:
    """Resolve channel-specific output format hint for system prompt injection.

    Returns the hint string if a match is found, empty string otherwise.
    The hint is designed to be appended directly to the system prompt.

    This function is called once at agent initialization — the result is
    stable for the session lifetime, making it fully KV-Cache-safe.
    """
    if not channel_name:
        return ""
    return CHANNEL_OUTPUT_HINTS.get(channel_name.lower().strip(), "")
