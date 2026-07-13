"""Tests for runtime lazy dependency installer."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from myrm_agent_harness.runtime import lazy_deps


@pytest.mark.parametrize(
    "feature,specs",
    [
        ("platform.discord", ("discord-py[voice]>=2.7.1",)),
        ("platform.feishu", ("lark-oapi>=1.6.8",)),
        ("platform.matrix", ("mautrix>=0.21.0", "aiohttp-socks>=0.11.0")),
        ("platform.matrix-e2ee", ("mautrix[encryption]>=0.21.0",)),
        ("platform.wechat-silk", ("pilk>=0.2.4",)),
        ("platform.voice-tts", ("edge-tts>=7.2.8",)),
    ],
)
def test_feature_specs_known(feature: str, specs: tuple[str, ...]) -> None:
    assert lazy_deps.feature_specs(feature) == specs


def test_feature_missing_when_satisfied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lazy_deps, "_is_satisfied", lambda _spec: True)
    assert lazy_deps.feature_missing("platform.matrix") == ()


def test_ensure_raises_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lazy_deps, "_is_satisfied", lambda _spec: False)
    monkeypatch.setattr(lazy_deps, "_allow_lazy_installs", lambda: False)
    with pytest.raises(lazy_deps.FeatureUnavailable, match="MYRM_DISABLE_LAZY_INSTALLS"):
        lazy_deps.ensure("platform.matrix", prompt=False)


def test_ensure_skips_install_when_already_satisfied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lazy_deps, "_is_satisfied", lambda _spec: True)

    with patch.object(lazy_deps, "_venv_pip_install") as mock_install:
        lazy_deps.ensure("platform.matrix", prompt=False)

    mock_install.assert_not_called()
