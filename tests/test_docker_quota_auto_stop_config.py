"""Tests for DOCKER_QUOTA_AUTO_STOP_CONTAINERS config resolution."""

import pytest

from app.utils import get_docker_quota_auto_stop_containers


def test_auto_stop_default_true_when_empty_config_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCKER_QUOTA_AUTO_STOP_CONTAINERS", raising=False)
    assert get_docker_quota_auto_stop_containers({}) is True


def test_auto_stop_false_from_config_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCKER_QUOTA_AUTO_STOP_CONTAINERS", raising=False)
    assert get_docker_quota_auto_stop_containers({"DOCKER_QUOTA_AUTO_STOP_CONTAINERS": False}) is False


def test_config_dict_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKER_QUOTA_AUTO_STOP_CONTAINERS", "true")
    assert get_docker_quota_auto_stop_containers({"DOCKER_QUOTA_AUTO_STOP_CONTAINERS": False}) is False
