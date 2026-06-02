"""Canonical URLs and presets for self-hosted SearXNG."""

from __future__ import annotations

# Host-native / Tauri / WebUI-local server talking to Docker-published port
SEARXNG_HOST_URL = "http://127.0.0.1:8081"

# Backend running inside docker-compose `myrm` network
SEARXNG_DOCKER_SERVICE_URL = "http://searxng:8080"

SEARXNG_PROBE_CANDIDATE_URLS: tuple[str, ...] = (
    SEARXNG_HOST_URL,
    "http://localhost:8081",
    SEARXNG_DOCKER_SERVICE_URL,
)

SEARXNG_REGION_PRESETS: dict[str, dict[str, str]] = {
    "global": {"language": "auto", "categories": "general"},
    "china": {"language": "zh-CN", "categories": "general", "engines": "baidu,bing,google"},
    "code": {"language": "en", "categories": "it", "engines": "github,stackoverflow,npm,pypi"},
    "academic": {"language": "en", "categories": "science", "engines": "arxiv,google scholar,semantic scholar"},
}

__all__ = [
    "SEARXNG_DOCKER_SERVICE_URL",
    "SEARXNG_HOST_URL",
    "SEARXNG_PROBE_CANDIDATE_URLS",
    "SEARXNG_REGION_PRESETS",
]
