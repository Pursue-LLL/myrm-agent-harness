"""BrowserSession console and network log APIs.

[INPUT]
- session.console_logger::ConsoleLogger (POS: browser console capture)
- session.network_logger::NetworkLogger (POS: network request log capture)
- session.network_intelligence::NetworkIntelligence (POS: CDP-based API response body retrieval)

[OUTPUT]
- BrowserSessionNetworkMixin: get_console_log / get_network_log / get_network_detail / replay_network_request.

[POS]
Console and network introspection APIs for BrowserSession. Delegates to NetworkLogger and
NetworkIntelligence; replay uses in-page fetch via the active tab.
"""

from __future__ import annotations

import json


class BrowserSessionNetworkMixin:
    def get_console_log(self) -> str:
        """Get captured browser console messages (errors, warnings, logs)."""
        return self._console_logger.get_summary()

    def get_network_log(self, filter_mode: str = "api") -> str:
        """Get network request logs."""
        api_summary = self._network_intelligence.get_summary()

        if api_summary and filter_mode == "api":
            parts = [
                "API Requests (use network_detail with index to view response body):",
                api_summary,
            ]
            failed_summary = self._network_logger.get_summary("failed")
            if "No network requests" not in failed_summary:
                parts.append(f"\n{failed_summary}")
            return "\n".join(parts)

        summary = self._network_logger.get_summary(filter_mode)
        if api_summary:
            summary += (
                "\n\nAPI Requests (use network_detail with index to view response body):"
                f"\n{api_summary}"
            )
        return summary

    async def get_network_detail(self, index: int) -> str:
        """Get response body for a tracked API request by index."""
        return await self._network_intelligence.get_response_body(index)

    async def replay_network_request(self, index: int) -> str:
        """Replay a tracked API request using page.evaluate(fetch(...))."""
        api_requests = self._network_intelligence.get_api_requests()
        if index < 1 or index > len(api_requests):
            return f"Error: Invalid index {index}. Valid range: 1-{len(api_requests)}"

        record = api_requests[index - 1]

        await self._ensure_components()
        page = self._tab_controller.get_active_page()

        url_js = json.dumps(record.url)
        method_js = json.dumps(record.method)

        fetch_opts_parts = [f'"method": {method_js}']
        if record.post_data and record.method in ("POST", "PUT", "PATCH"):
            body_js = json.dumps(record.post_data)
            fetch_opts_parts.append(f'"body": {body_js}')
            fetch_opts_parts.append('"headers": {"Content-Type": "application/json"}')

        fetch_opts = "{" + ", ".join(fetch_opts_parts) + "}"

        js_code = f"""
            async () => {{
                const resp = await fetch({url_js}, {fetch_opts});
                const text = await resp.text();
                return text.substring(0, 8000);
            }}
        """

        try:
            result = await page.evaluate(js_code)
            return str(result) if result else "Empty response"
        except Exception as exc:
            return f"Error replaying request: {exc}"
