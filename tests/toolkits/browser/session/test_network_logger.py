"""Unit tests for NetworkLogger — network request capture and filtering."""

import time
from unittest.mock import Mock

from myrm_agent_harness.toolkits.browser.session.network_logger import NetworkLogger, RequestInfo


class TestRequestInfo:
    """Test RequestInfo dataclass."""

    def test_is_api_request(self):
        """Test is_api_request property."""
        xhr_req = RequestInfo(
            method="GET",
            url="https://api.example.com/data",
            resource_type="xhr",
            timestamp=0.0,
        )
        assert xhr_req.is_api_request

        fetch_req = RequestInfo(
            method="POST",
            url="https://api.example.com/submit",
            resource_type="fetch",
            timestamp=0.0,
        )
        assert fetch_req.is_api_request

        doc_req = RequestInfo(
            method="GET",
            url="https://example.com",
            resource_type="document",
            timestamp=0.0,
        )
        assert not doc_req.is_api_request

    def test_is_failed(self):
        """Test is_failed property."""
        success_req = RequestInfo(
            method="GET",
            url="https://example.com",
            resource_type="xhr",
            timestamp=0.0,
            status=200,
        )
        assert not success_req.is_failed

        error_req = RequestInfo(
            method="GET",
            url="https://example.com",
            resource_type="xhr",
            timestamp=0.0,
            status=404,
        )
        assert error_req.is_failed

        server_error = RequestInfo(
            method="POST",
            url="https://example.com",
            resource_type="fetch",
            timestamp=0.0,
            status=500,
        )
        assert server_error.is_failed

        no_status = RequestInfo(
            method="GET",
            url="https://example.com",
            resource_type="xhr",
            timestamp=0.0,
        )
        assert not no_status.is_failed


class TestNetworkLogger:
    """Test NetworkLogger functionality."""

    def test_initialization(self):
        """Test logger initialization."""
        logger = NetworkLogger()
        assert len(logger._requests) == 0
        assert logger.get_pending_count() == 0
        assert logger.bound_page is None

        logger_custom = NetworkLogger(max_requests=10)
        assert len(logger_custom._requests) == 0

    def test_should_capture_filters_static_resources(self):
        """Test static resource filtering."""
        logger = NetworkLogger()

        assert not logger._should_capture("image")
        assert not logger._should_capture("stylesheet")
        assert not logger._should_capture("font")
        assert not logger._should_capture("media")

        assert logger._should_capture("xhr")
        assert logger._should_capture("fetch")
        assert logger._should_capture("document")

    def test_fifo_behavior(self):
        """Test FIFO storage with max_requests limit."""
        logger = NetworkLogger(max_requests=3)

        for i in range(5):
            info = RequestInfo(
                method="GET",
                url=f"https://example.com/{i}",
                resource_type="xhr",
                timestamp=float(i),
            )
            logger._requests.append(info)

        assert len(logger._requests) == 3
        urls = [r.url for r in logger._requests]
        assert urls == [
            "https://example.com/2",
            "https://example.com/3",
            "https://example.com/4",
        ]

    def test_filter_requests_api_mode(self):
        """Test filtering with 'api' mode."""
        logger = NetworkLogger()

        logger._requests.append(
            RequestInfo(method="GET", url="https://example.com", resource_type="document", timestamp=0.0)
        )
        logger._requests.append(
            RequestInfo(method="GET", url="https://api.example.com/data", resource_type="xhr", timestamp=1.0)
        )
        logger._requests.append(
            RequestInfo(method="POST", url="https://api.example.com/submit", resource_type="fetch", timestamp=2.0)
        )

        filtered = logger._filter_requests("api")
        assert len(filtered) == 2
        assert all(r.is_api_request for r in filtered)

    def test_filter_requests_failed_mode(self):
        """Test filtering with 'failed' mode."""
        logger = NetworkLogger()

        logger._requests.append(
            RequestInfo(
                method="GET",
                url="https://example.com/ok",
                resource_type="xhr",
                timestamp=0.0,
                status=200,
            )
        )
        logger._requests.append(
            RequestInfo(
                method="GET",
                url="https://example.com/notfound",
                resource_type="xhr",
                timestamp=1.0,
                status=404,
            )
        )
        logger._requests.append(
            RequestInfo(
                method="POST",
                url="https://example.com/error",
                resource_type="fetch",
                timestamp=2.0,
                status=500,
            )
        )

        filtered = logger._filter_requests("failed")
        assert len(filtered) == 2
        assert all(r.is_failed for r in filtered)

    def test_filter_requests_all_mode(self):
        """Test filtering with 'all' mode."""
        logger = NetworkLogger()

        logger._requests.append(
            RequestInfo(method="GET", url="https://example.com/1", resource_type="document", timestamp=0.0)
        )
        logger._requests.append(
            RequestInfo(method="GET", url="https://example.com/2", resource_type="xhr", timestamp=1.0)
        )

        filtered = logger._filter_requests("all")
        assert len(filtered) == 2

    def test_get_summary_empty(self):
        """Test get_summary with no requests."""
        logger = NetworkLogger()
        summary = logger.get_summary()
        assert "No network requests captured" in summary

    def test_get_summary_with_requests(self):
        """Test get_summary formatting."""
        logger = NetworkLogger()

        logger._requests.append(
            RequestInfo(
                method="GET",
                url="https://api.example.com/data",
                resource_type="xhr",
                timestamp=0.0,
                status=200,
                status_text="OK",
                duration_ms=123.5,
            )
        )
        logger._requests.append(
            RequestInfo(
                method="POST",
                url="https://api.example.com/error",
                resource_type="fetch",
                timestamp=1.0,
                status=404,
                status_text="Not Found",
                duration_ms=89.2,
            )
        )

        summary = logger.get_summary("api")

        assert "Network Log" in summary
        assert "GET https://api.example.com/data" in summary
        assert "[OK]" in summary
        assert "200 OK" in summary
        assert "124ms" in summary

        assert "POST https://api.example.com/error" in summary
        assert "[FAIL]" in summary
        assert "404 Not Found" in summary
        assert "89ms" in summary

    def test_get_summary_limits_output(self):
        """Test get_summary limits to last 20 requests."""
        logger = NetworkLogger(max_requests=50)

        for i in range(30):
            logger._requests.append(
                RequestInfo(
                    method="GET",
                    url=f"https://api.example.com/{i}",
                    resource_type="xhr",
                    timestamp=float(i),
                )
            )

        summary = logger.get_summary("api")

        assert "30 total" in summary
        assert "showing last 20" in summary

        assert "https://api.example.com/29" in summary
        assert "https://api.example.com/10" in summary
        assert "https://api.example.com/0" not in summary
        assert "https://api.example.com/9" not in summary

    def test_clear(self):
        """Test clear method."""
        logger = NetworkLogger()

        logger._requests.append(
            RequestInfo(method="GET", url="https://example.com", resource_type="xhr", timestamp=0.0)
        )

        mock_request = Mock()
        logger._pending[mock_request] = 0.0

        assert len(logger._requests) == 1
        assert len(logger._pending) == 1

        logger.clear()

        assert len(logger._requests) == 0
        assert len(logger._pending) == 0

    def test_get_pending_count(self):
        """Test get_pending_count method."""
        logger = NetworkLogger()

        mock_req1 = Mock()
        mock_req2 = Mock()
        logger._pending[mock_req1] = 0.0
        logger._pending[mock_req2] = 1.0

        assert logger.get_pending_count() == 2

    def test_on_request_captures_xhr(self):
        """Test _on_request captures XHR requests."""
        logger = NetworkLogger()

        mock_request = Mock()
        mock_request.method = "GET"
        mock_request.url = "https://api.example.com/data"
        mock_request.resource_type = "xhr"

        logger._on_request(mock_request)

        assert mock_request in logger._pending

    def test_on_request_filters_static_resources(self):
        """Test _on_request filters static resources."""
        logger = NetworkLogger()

        mock_request = Mock()
        mock_request.method = "GET"
        mock_request.url = "https://example.com/image.png"
        mock_request.resource_type = "image"

        logger._on_request(mock_request)

        assert mock_request not in logger._pending

    def test_on_request_failed_captures_failure(self):
        """Test _on_request_failed captures failed requests."""
        logger = NetworkLogger()

        mock_request = Mock()
        mock_request.method = "GET"
        mock_request.url = "https://example.com/fail"
        mock_request.resource_type = "xhr"

        logger._pending[mock_request] = 0.0

        logger._on_request_failed(mock_request)

        assert len(logger._requests) == 1
        req = logger._requests[0]
        assert req.url == "https://example.com/fail"
        assert req.status is None
        assert req.status_text == "Request Failed"

    def test_concurrent_same_url_requests(self):
        """Test handling concurrent requests to the same URL."""
        logger = NetworkLogger()

        mock_req1 = Mock()
        mock_req1.method = "GET"
        mock_req1.url = "https://api.example.com/data"
        mock_req1.resource_type = "xhr"

        mock_req2 = Mock()
        mock_req2.method = "GET"
        mock_req2.url = "https://api.example.com/data"
        mock_req2.resource_type = "xhr"

        mock_req3 = Mock()
        mock_req3.method = "GET"
        mock_req3.url = "https://api.example.com/data"
        mock_req3.resource_type = "xhr"

        logger._on_request(mock_req1)
        logger._on_request(mock_req2)
        logger._on_request(mock_req3)

        assert logger.get_pending_count() == 3

        mock_resp1 = Mock()
        mock_resp1.request = mock_req1
        mock_resp1.status = 200
        mock_resp1.status_text = "OK"

        mock_resp2 = Mock()
        mock_resp2.request = mock_req2
        mock_resp2.status = 200
        mock_resp2.status_text = "OK"

        logger._on_response(mock_resp1)
        logger._on_response(mock_resp2)

        assert len(logger._requests) == 2
        assert logger.get_pending_count() == 1


class TestNetworkLoggerIntegration:
    """Integration tests for NetworkLogger with mock Page."""

    def test_start_capture_registers_handlers(self):
        """Test start_capture registers event handlers."""
        logger = NetworkLogger()
        mock_page = Mock()

        logger.start_capture(mock_page)

        assert mock_page.on.call_count == 3
        event_names = [call[0][0] for call in mock_page.on.call_args_list]
        assert "request" in event_names
        assert "response" in event_names
        assert "requestfailed" in event_names

    def test_start_capture_idempotent_same_page(self) -> None:
        """Second start_capture on same page must not stack listeners."""
        logger = NetworkLogger()
        mock_page = Mock()
        logger.start_capture(mock_page)
        logger.start_capture(mock_page)
        assert mock_page.on.call_count == 3
        assert mock_page.off.call_count == 0

    def test_start_capture_switches_page_detaches_previous(self) -> None:
        """Binding a new page removes listeners from the previous page."""
        logger = NetworkLogger()
        page_a = Mock()
        page_b = Mock()
        logger.start_capture(page_a)
        logger.start_capture(page_b)
        assert page_a.off.call_count == 3
        assert page_b.on.call_count == 3
        assert logger.bound_page is page_b

    def test_stop_capture_detaches_when_bound(self) -> None:
        """stop_capture removes listeners from the bound page."""
        logger = NetworkLogger()
        mock_page = Mock()
        logger.start_capture(mock_page)
        logger.stop_capture()
        assert mock_page.off.call_count == 3
        assert logger.bound_page is None

    def test_detach_page_ignores_non_bound(self) -> None:
        """detach_page no-op when page is not the bound instance."""
        logger = NetworkLogger()
        page_a = Mock()
        page_b = Mock()
        logger.start_capture(page_a)
        logger.detach_page(page_b)
        assert page_a.off.call_count == 0
        assert logger.bound_page is page_a

    def test_stop_capture_clears_pending(self):
        """Test stop_capture clears pending state."""
        logger = NetworkLogger()

        mock_req = Mock()
        logger._pending[mock_req] = 0.0

        assert len(logger._pending) == 1

        logger.stop_capture()

        assert len(logger._pending) == 0

    def test_full_request_response_cycle(self):
        """Test full request/response capture cycle."""
        logger = NetworkLogger()

        mock_request = Mock()
        mock_request.method = "GET"
        mock_request.url = "https://api.example.com/data"
        mock_request.resource_type = "xhr"

        logger._on_request(mock_request)
        assert mock_request in logger._pending

        mock_response = Mock()
        mock_response.request = mock_request
        mock_response.status = 200
        mock_response.status_text = "OK"

        logger._on_response(mock_response)

        assert len(logger._requests) == 1
        req = logger._requests[0]
        assert req.method == "GET"
        assert req.url == "https://api.example.com/data"
        assert req.status == 200
        assert req.status_text == "OK"

    def test_request_failed_handling(self):
        """Test request failure handling."""
        logger = NetworkLogger()

        mock_request = Mock()
        mock_request.method = "POST"
        mock_request.url = "https://api.example.com/submit"
        mock_request.resource_type = "fetch"

        logger._on_request(mock_request)

        logger._on_request_failed(mock_request)

        assert len(logger._requests) == 1
        req = logger._requests[0]
        assert req.url == "https://api.example.com/submit"
        assert req.status is None
        assert req.status_text == "Request Failed"


class TestNetworkLoggerEdgeCases:
    """Test edge cases and error handling."""

    def test_on_request_exception_handling(self):
        """Test _on_request handles exceptions gracefully."""
        logger = NetworkLogger()

        mock_request = Mock()
        type(mock_request).resource_type = property(lambda self: (_ for _ in ()).throw(Exception("Test error")))

        logger._on_request(mock_request)

        assert len(logger._pending) == 0

    def test_on_response_exception_handling(self):
        """Test _on_response handles exceptions gracefully."""
        logger = NetworkLogger()

        mock_response = Mock()
        mock_response.request = Mock(side_effect=Exception("Test error"))

        logger._on_response(mock_response)

        assert len(logger._requests) == 0

    def test_on_response_request_not_in_pending(self):
        """Test _on_response when request is not in pending."""
        logger = NetworkLogger()

        mock_request = Mock()
        mock_response = Mock()
        mock_response.request = mock_request

        logger._on_response(mock_response)

        assert len(logger._requests) == 0

    def test_on_request_failed_exception_handling(self):
        """Test _on_request_failed handles exceptions gracefully."""
        logger = NetworkLogger()

        mock_request = Mock()
        mock_request.method = Mock(side_effect=Exception("Test error"))

        logger._on_request_failed(mock_request)

        assert len(logger._requests) == 0

    def test_on_request_failed_request_not_in_pending(self):
        """Test _on_request_failed when request is not in pending."""
        logger = NetworkLogger()

        mock_request = Mock()
        mock_request.method = "GET"
        mock_request.url = "https://example.com"
        mock_request.resource_type = "xhr"

        logger._on_request_failed(mock_request)

        assert len(logger._requests) == 0

    def test_filter_requests_unknown_mode(self):
        """Test _filter_requests with unknown mode."""
        logger = NetworkLogger()

        mock_req = Mock()
        mock_req.method = "GET"
        mock_req.url = "https://api.example.com/data"
        mock_req.resource_type = "xhr"
        mock_req.timestamp = time.time()
        mock_req.status = 200
        mock_req.status_text = "OK"
        mock_req.duration_ms = 100.0
        mock_req.is_api_request = True
        mock_req.is_failed = False

        logger._requests.append(mock_req)

        result = logger._filter_requests("unknown_mode")

        assert len(result) == 1
        assert result[0] == mock_req

    def test_format_request_with_status_text_only(self):
        """Test _format_request when status is None but status_text exists."""
        logger = NetworkLogger()

        req = RequestInfo(
            method="GET",
            url="https://example.com",
            resource_type="xhr",
            timestamp=time.time(),
            status=None,
            status_text="Network Error",
            duration_ms=50.0,
        )

        parts = logger._format_request(req, 1)

        assert "[FAIL] Network Error" in " ".join(parts)
