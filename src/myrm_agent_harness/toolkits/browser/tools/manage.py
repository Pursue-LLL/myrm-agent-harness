"""browser_manage tool for session management.

[INPUT]
- common::mark_untrusted (POS: unified browser output security boundary; credential redaction + untrusted-content wrapping)
- domain_skills::DomainSkillStore (POS: executable-layer domain skill registry)

[OUTPUT]
- create_manage_tool: Create browser_manage tool bound to session.

[POS]
browser_manage tool for session management. Includes domain skill execution (run_site_tool/list_site_tools).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from langchain.tools import tool
from pydantic import BaseModel, Field

from .common import mark_untrusted

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..session import BrowserSession


def create_manage_tool(session: BrowserSession):
    """Create browser_manage tool bound to session."""

    class ManageInput(BaseModel):
        action: str = Field(
            description="Action: close, evaluate, new_tab, switch_tab, list_tabs, close_tab, "
            "back, forward, save_pdf, resize, emulate, wait_for_load, console_log, "
            "network_log, network_detail, network_replay, web_vitals, "
            "dialog_response, dialog_policy, "
            "save_session, restore_session, list_sessions, delete_session, "
            "trace_start, trace_stop, har_start, har_stop, recording_status, "
            "save_site_experience, list_site_experience, delete_site_experience, "
            "download_url, list_downloads, "
            "run_site_tool, list_site_tools",
        )
        value: str = Field(
            default="",
            description="Required for: JS expression (evaluate), tab_id (switch_tab/close_tab), "
            "URL (new_tab/download_url), 'WIDTHxHEIGHT' (resize), "
            "device name (emulate, e.g. 'iPhone 15 Pro', 'Pixel 8', "
            "'iPhone 15 Pro landscape', or 'desktop'), "
            "'accept'/'dismiss[:prompt]' (dialog_response), "
            "'smart'/'auto_accept'/'auto_dismiss'/'wait_for_agent' (dialog_policy), "
            "domain or 'domain:label' (save_session), domain (restore_session/delete_session), "
            "request index number (network_detail/network_replay), "
            "JSON for save_site_experience (e.g. "
            '\'{"domain":"example.com","known_traps":["login wall"],"successful_flows":["direct URL"]}\'), '
            "domain for delete_site_experience, "
            "'skill_id:tool_name:{json_args}' for run_site_tool "
            "(e.g. 'x-com:get_timeline_posts:{\"max_posts\":20}'). "
            "Omit for: close, list_tabs, list_sessions, list_site_experience, list_downloads, "
            "list_site_tools, back, forward, save_pdf, "
            "wait_for_load, console_log, network_log, web_vitals, "
            "trace_start, trace_stop, har_start, har_stop, "
            "recording_status.",
        )

    @tool("browser_manage_tool", args_schema=ManageInput)
    async def browser_manage(action: str, value: str = "") -> str:
        """Manage the browser session: tabs, navigation history, JS execution, debugging, and more.

        Tab management: new_tab, switch_tab, list_tabs, close_tab.
        History: back, forward. Evaluation: evaluate. Output: save_pdf, console_log.
        Control: close, resize, emulate, wait_for_load. Dialogs: dialog_response.
        Sessions: save_session, restore_session, list_sessions, delete_session.
        Recording: trace_start, trace_stop, har_start, har_stop, recording_status.
        Diagnostics: web_vitals (page performance metrics with ratings and fixes).
        Human-in-the-loop: use browser_ask_human_tool for 2FA, CAPTCHA, or payment gates.
        Site experience: save_site_experience, list_site_experience, delete_site_experience.
        Downloads: download_url (download file from URL), list_downloads (show download history).
        """
        match action:
            case "close":
                await session.close()
                return "Browser session closed."
            case "evaluate":
                if not value:
                    return "Error: 'value' is required for action='evaluate'"
                return mark_untrusted(await session.evaluate(value))
            case "new_tab":
                tabs_before = set(session.list_tabs())
                tab_id = await session.new_tab(value or None)
                reused = tab_id in tabs_before
                if reused:
                    tabs_info = session.list_tabs_with_info()
                    domain = next(
                        (i["domain"] for i in tabs_info if i["tab_id"] == tab_id), "unknown"
                    )
                    return f"Reused existing {tab_id} ({domain}) — same origin as requested URL"
                return f"New tab created: {tab_id}"
            case "switch_tab":
                return await session.switch_tab(value)
            case "list_tabs":
                tabs_info = session.list_tabs_with_info()
                if not tabs_info:
                    return "No open tabs"
                parts = []
                for info in tabs_info:
                    marker = " [active]" if info["active"] else ""
                    parts.append(f"{info['tab_id']}: {info['domain']}{marker}")
                return "Open tabs:\n" + "\n".join(parts)
            case "close_tab":
                return await session.close_tab(value)
            case "back":
                return await session.go_back()
            case "forward":
                return await session.go_forward()
            case "save_pdf":
                return await session.save_pdf()
            case "resize":
                try:
                    w, h = value.lower().split("x")
                    return await session.resize(int(w), int(h))
                except (ValueError, AttributeError):
                    return "Error: value must be 'WIDTHxHEIGHT' (e.g. '1920x1080')"
            case "emulate":
                if not value.strip():
                    available = ", ".join(session.list_emulatable_devices())
                    return (
                        "Error: 'value' must be a device name "
                        f"(e.g. 'iPhone 15 Pro', 'Pixel 8') or 'desktop'. "
                        "Append ' landscape' for landscape orientation. "
                        f"Available: {available}"
                    )
                return mark_untrusted(await session.emulate_device(value.strip()))
            case "wait_for_load":
                return await session.wait_for_load()
            case "console_log":
                return mark_untrusted(session.get_console_log())
            case "network_log":
                return mark_untrusted(session.get_network_log())
            case "network_detail":
                if not value.strip():
                    return "Error: 'value' must be the request index number (from network_log output)"
                try:
                    index = int(value.strip())
                except ValueError:
                    return "Error: 'value' must be an integer (request index from network_log)"
                return mark_untrusted(await session.get_network_detail(index))
            case "network_replay":
                if not value.strip():
                    return "Error: 'value' must be the request index number to replay"
                try:
                    index = int(value.strip())
                except ValueError:
                    return "Error: 'value' must be an integer (request index from network_log)"
                return mark_untrusted(await session.replay_network_request(index))
            case "dialog_response":
                parts = value.split(":", 1)
                accept = parts[0].strip().lower() != "dismiss"
                prompt_text = parts[1].strip() if len(parts) > 1 else ""
                return await session.set_dialog_response(accept, prompt_text)
            case "dialog_policy":
                from ..session.dialog_manager import DialogPolicy

                policy_str = value.strip().lower()
                try:
                    new_policy = DialogPolicy(policy_str)
                except ValueError:
                    return (
                        f"Invalid dialog policy '{policy_str}'. "
                        f"Valid: {', '.join(p.value for p in DialogPolicy)}"
                    )
                session._dialog_manager.policy = new_policy
                return f"Dialog policy changed to: {new_policy.value}"
            case "save_session":
                domain = value.strip()
                if not domain:
                    return "Error: 'value' must be domain (e.g. 'github.com')"
                return await session.save_session(domain)
            case "restore_session":
                if not value.strip():
                    return "Error: 'value' must be the domain to restore (e.g. 'github.com')"
                return await session.restore_session(value.strip())
            case "list_sessions":
                return await session.list_sessions()
            case "delete_session":
                if not value.strip():
                    return "Error: 'value' must be the domain to delete (e.g. 'github.com')"
                return await session.delete_session(value.strip())
            case "trace_start":
                return await session.start_trace()
            case "trace_stop":
                return await session.stop_trace()
            case "har_start":
                return await session.start_har()
            case "har_stop":
                return await session.stop_har()
            case "recording_status":
                status = session.get_recording_status()
                return f"Recording status:\n{status}"
            case "web_vitals":
                return mark_untrusted(await session.get_web_vitals())
            case "save_site_experience":
                return _handle_save_site_experience(value)
            case "list_site_experience":
                return _handle_list_site_experience()
            case "delete_site_experience":
                return _handle_delete_site_experience(value)
            case "download_url":
                if not value.strip():
                    return "Error: 'value' must be a URL to download"
                result = await session.download_url(value.strip())
                if result is None:
                    return f"Download failed for: {value.strip()}"
                return (
                    f"Downloaded: {result.file_name} ({result.file_size} bytes)\n"
                    f"Path: {result.path}\nType: {result.file_type or 'unknown'}"
                )
            case "list_downloads":
                downloads = session.list_downloads()
                if not downloads:
                    return "No files downloaded yet."
                lines = [f"Downloaded files ({len(downloads)}):"]
                for dl in downloads:
                    auto_tag = " [auto]" if dl.auto_download else ""
                    lines.append(f" - {dl.file_name} ({dl.file_size} bytes){auto_tag}: {dl.path}")
                return "\n".join(lines)
            case "run_site_tool":
                return await _handle_run_site_tool(session, value)
            case "list_site_tools":
                return _handle_list_site_tools()
            case _:
                return (
                    f"Unknown action '{action}'. Supported: close, evaluate, new_tab, switch_tab, "
                    "list_tabs, close_tab, back, forward, save_pdf, resize, emulate, wait_for_load, "
                    "console_log, network_log, network_detail, network_replay, web_vitals, "
                    "dialog_response, dialog_policy, "
                    "save_session, restore_session, list_sessions, delete_session, "
                    "trace_start, trace_stop, har_start, har_stop, recording_status, "
                    "save_site_experience, list_site_experience, delete_site_experience, "
                    "download_url, list_downloads, "
                    "run_site_tool, list_site_tools"
                )

    def _handle_save_site_experience(value: str) -> str:
        if not value.strip():
            return (
                "Error: 'value' must be JSON with 'domain' and optional fields: "
                "platform_features, url_patterns, known_traps, successful_flows. "
                'Example: {"domain":"example.com","known_traps":["login wall"]}'
            )
        try:
            data = json.loads(value)
        except json.JSONDecodeError:
            return "Error: value must be valid JSON"

        domain = data.get("domain", "").strip()
        if not domain:
            return "Error: JSON must include 'domain' field"

        from ...web_fetch.router import get_global_site_experience_store

        store = get_global_site_experience_store()
        exp = store.save_experience(
            domain,
            platform_features=data.get("platform_features"),
            url_patterns=data.get("url_patterns"),
            known_traps=data.get("known_traps"),
            successful_flows=data.get("successful_flows"),
        )
        store.save()
        return exp.format_full()

    def _handle_list_site_experience() -> str:
        from ...web_fetch.router import get_global_domain_metrics_manager, get_global_site_experience_store

        store = get_global_site_experience_store()
        domains = store.list_domains()
        if not domains:
            return "No site experience recorded yet."

        metrics_manager = get_global_domain_metrics_manager()
        parts: list[str] = [f"Site experience recorded for {len(domains)} domain(s):"]
        for domain in domains:
            exp, possibly_stale = store.get(domain, domain_metrics_manager=metrics_manager)
            if exp is None:
                continue
            stale_tag = " stale" if possibly_stale else ""
            parts.append(f" - {domain}{stale_tag}")
        return "\n".join(parts)

    def _handle_delete_site_experience(value: str) -> str:
        domain = value.strip()
        if not domain:
            return "Error: 'value' must be the domain to delete (e.g. 'example.com')"

        from ...web_fetch.router import get_global_site_experience_store

        store = get_global_site_experience_store()
        if store.delete(domain):
            store.save()
            return f"Deleted site experience for '{domain}'."
        return f"No site experience found for '{domain}'."

    async def _handle_run_site_tool(browser_session: BrowserSession, value: str) -> str:
        """Execute a domain skill tool in the browser session sandbox."""
        if not value.strip():
            return (
                "Error: 'value' must be 'skill_id:tool_name' or "
                "'skill_id:tool_name:{json_args}' "
                "(e.g. 'x-com:get_timeline_posts:{\"max_posts\":20}')"
            )

        parts = value.split(":", 2)
        if len(parts) < 2:
            return "Error: value must contain at least 'skill_id:tool_name'"

        skill_id = parts[0].strip()
        tool_name = parts[1].strip()
        tool_args: dict[str, str | int] = {}
        if len(parts) == 3 and parts[2].strip():
            try:
                tool_args = json.loads(parts[2].strip())
            except json.JSONDecodeError:
                return f"Error: invalid JSON args: {parts[2].strip()}"

        from ..domain_skills import get_global_domain_skill_store

        store = get_global_domain_skill_store()
        manifest = store.get(skill_id)
        if manifest is None:
            available = ", ".join(m.id for m in store.list_skills())
            return f"Error: domain skill '{skill_id}' not found. Available: {available or 'none'}"

        tool = manifest.python_tools.get(tool_name)
        if tool is None:
            available = ", ".join(manifest.python_tools.keys())
            return f"Error: tool '{tool_name}' not found in '{skill_id}'. Available: {available or 'none'}"

        script_path = store.get_tool_script_path(skill_id, tool_name)
        if script_path is None or not script_path.exists():
            return f"Error: script not found for '{skill_id}:{tool_name}'"

        script_code = script_path.read_text(encoding="utf-8")

        import importlib.util
        import sys
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(script_code)
            tmp_path = tmp.name

        try:
            spec = importlib.util.spec_from_file_location(
                f"_domain_tool_{skill_id}_{tool_name}", tmp_path
            )
            if spec is None or spec.loader is None:
                return f"Error: failed to load script for '{skill_id}:{tool_name}'"
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod.__name__] = mod
            spec.loader.exec_module(mod)

            func = getattr(mod, tool.callable_name, None)
            if func is None:
                return f"Error: callable '{tool.callable_name}' not found in script"

            import asyncio

            result = await asyncio.wait_for(
                func(browser_session, tool_args), timeout=30.0
            )
            return mark_untrusted(str(result))
        except TimeoutError:
            return f"Error: domain tool '{skill_id}:{tool_name}' timed out after 30s"
        except Exception as exc:
            logger.exception(
                "Domain tool execution failed for %s:%s",
                skill_id,
                tool_name,
            )
            return f"Error executing domain tool '{skill_id}:{tool_name}': {exc}"
        finally:
            import os as _os

            with __import__("contextlib").suppress(OSError):
                _os.unlink(tmp_path)
            sys.modules.pop(f"_domain_tool_{skill_id}_{tool_name}", None)

    def _handle_list_site_tools() -> str:
        """List all available domain skill tools."""
        from ..domain_skills import get_global_domain_skill_store

        store = get_global_domain_skill_store()
        skills = store.list_skills()
        if not skills:
            return "No domain skills available."

        lines: list[str] = [f"Domain skills ({len(skills)}):"]
        for skill in skills:
            domains = ", ".join(skill.domains[:3])
            lines.append(f"\n  [{skill.id}] {skill.name} ({domains})")
            for dom_tool in skill.python_tools.values():
                args_str = ", ".join(
                    f"{k}{'?' if a.get('required') != 'true' else ''}"
                    for k, a in dom_tool.args.items()
                )
                lines.append(f"    - {dom_tool.name}({args_str}): {dom_tool.description}")
        return "\n".join(lines)

    return browser_manage
