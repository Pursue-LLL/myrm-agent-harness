# http/

## Overview
HTTP request toolkit. Supports streaming upload, progress callbacks, streaming download, and concurrent downloads.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | HTTP request toolkit. Supports streaming upload, progress callbacks, streaming download, and concurr | ✅ |
| client_pool.py | Core | HTTP client connection pool. Global singleton reusing TCP connections and TLS handshakes. | ✅ |
| concurrent_download.py | Core | Concurrent file downloader. Batch downloads with asyncio.gather, semaphore-based concurrency control | ✅ |
| error_classifier.py | Core | HTTP error classifier. Categorizes HTTP exceptions into 6 types and generates user-friendly error me | ✅ |
| http_request_tool.py | Core | HTTP Request Tool for Agent. | ✅ |
| multipart_upload.py | Core | Multipart upload interface (framework layer). Defines an S3-compatible multipart upload protocol for | ✅ |
| rate_limiter.py | Core | Rate limiter interface (framework layer). Defines the rate limiting protocol with a default token-bu | ✅ |
| resumable_upload.py | Core | Resumable upload interface (framework layer). Defines the checkpoint storage protocol for business-l | ✅ |
| retry_policy.py | Core | HTTP retry policy. Exponential backoff with jitter and Retry-After header support for improved succe | ✅ |
| skip_upload_helper.py | Core | Instant upload optimization. Checks if a file already exists via HEAD request with MD5 matching to s | ✅ |

## Key Dependencies

- `toolkits`
- `utils`
