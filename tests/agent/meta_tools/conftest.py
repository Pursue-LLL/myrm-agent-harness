import pytest


@pytest.fixture(autouse=True)
def disable_ssrf_shield(monkeypatch):
    monkeypatch.setenv("MYRM_ENABLE_SSRF_SHIELD", "false")
