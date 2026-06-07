"""Unit tests for NetworkIntelligence — CDP-based lazy response body retrieval."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from myrm_agent_harness.toolkits.browser.session.network_intelligence import (
    CdpRequestRecord,
    NetworkIntelligence,
)


class TestCdpRequestRecord:
    """Test CdpRequestRecord dataclass."""

    def test_creation(self):
        record = CdpRequestRecord(
            request_id="1234.5",
            url="https://api.example.com/data",
            method="GET",
            resource_type="XHR",
            status=200,
            mime_type="application/json",
        )
        assert record.request_id == "1234.5"
        assert record.url == "https://api.example.com/data"
        assert record.method == "GET"
        assert record.resource_type == "XHR"
        assert record.status == 200
        assert record.mime_type == "application/json"

    def test_post_data_preview(self):
        record = CdpRequestRecord(
            request_id="1",
            url="https://api.example.com/graphql",
            method="POST",
            resource_type="Fetch",
            post_data='{"operationName":"GetIssues","query":"..."}',
        )
        assert record.post_data == '{"operationName":"GetIssues","query":"..."}'

    def test_frozen(self):
        record = CdpRequestRecord(
            request_id="1",
            url="https://example.com",
            method="GET",
            resource_type="XHR",
        )
        with pytest.raises(Exception):
            record.url = "https://other.com"  # type: ignore[misc]


class TestNetworkIntelligence:
    """Test NetworkIntelligence component."""

    def test_initial_state(self):
        ni = NetworkIntelligence()
        assert not ni.is_enabled
        assert ni.get_api_requests() == []
        assert ni.get_summary() == ""

    def test_on_request_will_be_sent_xhr(self):
        ni = NetworkIntelligence()
        params = {
            "requestId": "req-1",
            "type": "XHR",
            "request": {
                "url": "https://api.example.com/data",
                "method": "GET",
            },
        }
        ni._on_request_will_be_sent(params)
        assert len(ni.get_api_requests()) == 1
        assert ni.get_api_requests()[0].request_id == "req-1"
        assert ni.get_api_requests()[0].url == "https://api.example.com/data"

    def test_on_request_will_be_sent_fetch(self):
        ni = NetworkIntelligence()
        params = {
            "requestId": "req-2",
            "type": "Fetch",
            "request": {
                "url": "https://api.example.com/graphql",
                "method": "POST",
                "postData": '{"operationName":"GetUsers","variables":{}}',
            },
        }
        ni._on_request_will_be_sent(params)
        requests = ni.get_api_requests()
        assert len(requests) == 1
        assert requests[0].method == "POST"
        assert requests[0].post_data == '{"operationName":"GetUsers","variables":{}}'

    def test_ignores_non_api_resource_types(self):
        ni = NetworkIntelligence()
        for resource_type in ["Image", "Stylesheet", "Script", "Font"]:
            params = {
                "requestId": f"req-{resource_type}",
                "type": resource_type,
                "request": {"url": "https://cdn.example.com/style.css", "method": "GET"},
            }
            ni._on_request_will_be_sent(params)
        assert len(ni.get_api_requests()) == 0

    def test_on_response_received_updates_status(self):
        ni = NetworkIntelligence()
        ni._on_request_will_be_sent({
            "requestId": "req-1",
            "type": "XHR",
            "request": {"url": "https://api.example.com/data", "method": "GET"},
        })

        ni._on_response_received({
            "requestId": "req-1",
            "response": {"status": 200, "mimeType": "application/json"},
        })

        requests = ni.get_api_requests()
        assert requests[0].status == 200
        assert requests[0].mime_type == "application/json"

    def test_post_data_truncation(self):
        ni = NetworkIntelligence()
        long_body = "x" * 500
        params = {
            "requestId": "req-1",
            "type": "Fetch",
            "request": {
                "url": "https://api.example.com/submit",
                "method": "POST",
                "postData": long_body,
            },
        }
        ni._on_request_will_be_sent(params)
        assert len(ni.get_api_requests()[0].post_data) == 200  # type: ignore[arg-type]

    def test_max_requests_limit(self):
        ni = NetworkIntelligence(max_requests=5)
        for i in range(10):
            ni._on_request_will_be_sent({
                "requestId": f"req-{i}",
                "type": "XHR",
                "request": {"url": f"https://api.example.com/{i}", "method": "GET"},
            })
        assert len(ni.get_api_requests()) == 5
        assert ni.get_api_requests()[0].request_id == "req-5"

    def test_get_summary(self):
        ni = NetworkIntelligence()
        ni._on_request_will_be_sent({
            "requestId": "req-1",
            "type": "XHR",
            "request": {"url": "https://api.example.com/users", "method": "GET"},
        })
        ni._on_response_received({
            "requestId": "req-1",
            "response": {"status": 200, "mimeType": "application/json"},
        })

        ni._on_request_will_be_sent({
            "requestId": "req-2",
            "type": "Fetch",
            "request": {
                "url": "https://api.example.com/graphql",
                "method": "POST",
                "postData": '{"operationName":"GetIssues"}',
            },
        })

        summary = ni.get_summary()
        assert "GET https://api.example.com/users" in summary
        assert "POST https://api.example.com/graphql" in summary
        assert '{"operationName":"GetIssues"}' in summary

    def test_clear(self):
        ni = NetworkIntelligence()
        ni._on_request_will_be_sent({
            "requestId": "req-1",
            "type": "XHR",
            "request": {"url": "https://api.example.com/data", "method": "GET"},
        })
        assert len(ni.get_api_requests()) == 1

        ni.clear()
        assert len(ni.get_api_requests()) == 0

    @pytest.mark.asyncio
    async def test_attach_success(self):
        mock_page = MagicMock()
        mock_cdp = AsyncMock()
        mock_page.context.new_cdp_session = AsyncMock(return_value=mock_cdp)

        ni = NetworkIntelligence()
        await ni.attach(mock_page)

        assert ni.is_enabled
        mock_page.context.new_cdp_session.assert_awaited_once_with(mock_page)
        mock_cdp.send.assert_awaited_once_with("Network.enable")
        assert mock_cdp.on.call_count == 2

    @pytest.mark.asyncio
    async def test_attach_failure_non_critical(self):
        mock_page = MagicMock()
        mock_page.context.new_cdp_session = AsyncMock(side_effect=Exception("CDP failed"))

        ni = NetworkIntelligence()
        await ni.attach(mock_page)

        assert not ni.is_enabled

    @pytest.mark.asyncio
    async def test_attach_idempotent(self):
        mock_page = MagicMock()
        mock_cdp = AsyncMock()
        mock_page.context.new_cdp_session = AsyncMock(return_value=mock_cdp)

        ni = NetworkIntelligence()
        await ni.attach(mock_page)
        await ni.attach(mock_page)

        mock_page.context.new_cdp_session.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_detach(self):
        mock_page = MagicMock()
        mock_cdp = AsyncMock()
        mock_page.context.new_cdp_session = AsyncMock(return_value=mock_cdp)

        ni = NetworkIntelligence()
        await ni.attach(mock_page)
        assert ni.is_enabled

        await ni.detach()
        assert not ni.is_enabled
        mock_cdp.detach.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_response_body_success(self):
        ni = NetworkIntelligence()
        ni._on_request_will_be_sent({
            "requestId": "req-1",
            "type": "XHR",
            "request": {"url": "https://api.example.com/data", "method": "GET"},
        })

        mock_cdp = AsyncMock()
        mock_cdp.send = AsyncMock(return_value={"body": '{"users": [1, 2, 3]}', "base64Encoded": False})
        ni._cdp_session = mock_cdp

        result = await ni.get_response_body(1)
        assert '{"users": [1, 2, 3]}' == result
        mock_cdp.send.assert_awaited_once_with(
            "Network.getResponseBody", {"requestId": "req-1"}
        )

    @pytest.mark.asyncio
    async def test_get_response_body_binary(self):
        ni = NetworkIntelligence()
        ni._on_request_will_be_sent({
            "requestId": "req-1",
            "type": "XHR",
            "request": {"url": "https://api.example.com/image", "method": "GET"},
        })
        ni._on_response_received({
            "requestId": "req-1",
            "response": {"status": 200, "mimeType": "image/png"},
        })

        mock_cdp = AsyncMock()
        mock_cdp.send = AsyncMock(return_value={"body": "iVBORw0KGgo=", "base64Encoded": True})
        ni._cdp_session = mock_cdp

        result = await ni.get_response_body(1)
        assert "Binary response" in result
        assert "image/png" in result

    @pytest.mark.asyncio
    async def test_get_response_body_no_cdp(self):
        ni = NetworkIntelligence()
        ni._on_request_will_be_sent({
            "requestId": "req-1",
            "type": "XHR",
            "request": {"url": "https://api.example.com/data", "method": "GET"},
        })

        result = await ni.get_response_body(1)
        assert "Error: CDP session not available" in result

    @pytest.mark.asyncio
    async def test_get_response_body_invalid_index(self):
        ni = NetworkIntelligence()
        mock_cdp = AsyncMock()
        ni._cdp_session = mock_cdp

        result = await ni.get_response_body(1)
        assert "Error: Invalid index" in result

    @pytest.mark.asyncio
    async def test_get_response_body_expired_request(self):
        ni = NetworkIntelligence()
        ni._on_request_will_be_sent({
            "requestId": "req-1",
            "type": "XHR",
            "request": {"url": "https://api.example.com/data", "method": "GET"},
        })

        mock_cdp = AsyncMock()
        mock_cdp.send = AsyncMock(
            side_effect=Exception("No resource with given identifier found")
        )
        ni._cdp_session = mock_cdp

        result = await ni.get_response_body(1)
        assert "no longer available" in result
        assert "navigated away" in result

    @pytest.mark.asyncio
    async def test_get_response_body_truncation(self):
        ni = NetworkIntelligence()
        ni._on_request_will_be_sent({
            "requestId": "req-1",
            "type": "XHR",
            "request": {"url": "https://api.example.com/data", "method": "GET"},
        })

        large_body = "x" * 10000
        mock_cdp = AsyncMock()
        mock_cdp.send = AsyncMock(return_value={"body": large_body, "base64Encoded": False})
        ni._cdp_session = mock_cdp

        result = await ni.get_response_body(1)
        assert "truncated" in result
        assert len(result) < 10000

    def test_document_type_tracked(self):
        """Document type requests should also be tracked for navigation API discovery."""
        ni = NetworkIntelligence()
        ni._on_request_will_be_sent({
            "requestId": "req-doc",
            "type": "Document",
            "request": {"url": "https://example.com/page", "method": "GET"},
        })
        # Document is tracked in _requests but not in get_api_requests()
        assert len(ni._requests) == 1
        assert len(ni.get_api_requests()) == 0
