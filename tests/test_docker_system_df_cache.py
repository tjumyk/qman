"""Tests for get_system_df cache/stale behavior (gunicorn timeout mitigation)."""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from app.docker_quota.cache import get_cached_system_df, set_cached_system_df
from app.docker_quota.docker_client import get_system_df


def _sample_df(include_volumes: bool = False) -> dict:
    out = {
        "containers": {"cid1": 100},
        "images": {"iid1": 200},
    }
    if include_volumes:
        out["volumes"] = {"vol1": {"size": 50, "labels": {}, "ref_count": 1}}
    return out


@pytest.fixture
def fake_redis() -> MagicMock:
    store: dict[str, bytes] = {}

    client = MagicMock()

    def _get(key: str) -> bytes | None:
        return store.get(key)

    def _setex(key: str, ttl: int, value: str | bytes) -> None:
        store[key] = value if isinstance(value, bytes) else value.encode("utf-8")

    def _delete(*keys: str) -> None:
        for key in keys:
            store.pop(key, None)

    client.get.side_effect = _get
    client.setex.side_effect = _setex
    client.delete.side_effect = _delete
    client.ping.return_value = True
    return client


class TestGetCachedSystemDf:
    def test_fresh_hit(self, fake_redis: MagicMock) -> None:
        payload = {"timestamp": time.time(), "result": _sample_df()}
        fake_redis.get = MagicMock(
            return_value=json.dumps(payload).encode("utf-8"),
        )
        with patch("app.docker_quota.cache._get_redis_client", return_value=fake_redis):
            with patch("app.docker_quota.cache._get_df_cache_ttl", return_value=300):
                with patch("app.docker_quota.cache._get_df_stale_cache_ttl", return_value=3600):
                    result = get_cached_system_df(include_volumes=False, allow_stale=False)
        assert result == _sample_df()

    def test_stale_only_when_allowed(self, fake_redis: MagicMock) -> None:
        payload = {"timestamp": time.time() - 600, "result": _sample_df()}
        fake_redis.get = MagicMock(
            return_value=json.dumps(payload).encode("utf-8"),
        )
        with patch("app.docker_quota.cache._get_redis_client", return_value=fake_redis):
            with patch("app.docker_quota.cache._get_df_cache_ttl", return_value=300):
                with patch("app.docker_quota.cache._get_df_stale_cache_ttl", return_value=3600):
                    assert get_cached_system_df(include_volumes=False, allow_stale=False) is None
                    assert get_cached_system_df(include_volumes=False, allow_stale=True) == _sample_df()

    def test_too_old_returns_none(self, fake_redis: MagicMock) -> None:
        payload = {"timestamp": time.time() - 7200, "result": _sample_df()}
        fake_redis.get = MagicMock(
            return_value=json.dumps(payload).encode("utf-8"),
        )
        with patch("app.docker_quota.cache._get_redis_client", return_value=fake_redis):
            with patch("app.docker_quota.cache._get_df_cache_ttl", return_value=300):
                with patch("app.docker_quota.cache._get_df_stale_cache_ttl", return_value=3600):
                    assert get_cached_system_df(include_volumes=False, allow_stale=True) is None


class TestGetSystemDfCacheInfo:
    def test_fresh_snapshot(self, fake_redis: MagicMock) -> None:
        from app.docker_quota.cache import get_system_df_cache_info

        ts = time.time() - 60
        payload = {"timestamp": ts, "result": _sample_df()}
        fake_redis.get = MagicMock(return_value=json.dumps(payload).encode("utf-8"))
        with patch("app.docker_quota.cache._get_redis_client", return_value=fake_redis):
            with patch("app.docker_quota.cache._get_df_cache_ttl", return_value=300):
                with patch("app.docker_quota.cache._get_df_stale_cache_ttl", return_value=3600):
                    info = get_system_df_cache_info(include_volumes=False)
        assert info["available"] is True
        assert info["cached_at"] == ts
        assert info["is_stale"] is False

    def test_stale_snapshot(self, fake_redis: MagicMock) -> None:
        from app.docker_quota.cache import get_system_df_cache_info

        ts = time.time() - 600
        payload = {"timestamp": ts, "result": _sample_df()}
        fake_redis.get = MagicMock(return_value=json.dumps(payload).encode("utf-8"))
        with patch("app.docker_quota.cache._get_redis_client", return_value=fake_redis):
            with patch("app.docker_quota.cache._get_df_cache_ttl", return_value=300):
                with patch("app.docker_quota.cache._get_df_stale_cache_ttl", return_value=3600):
                    info = get_system_df_cache_info(include_volumes=False)
        assert info["available"] is True
        assert info["is_stale"] is True

    def test_missing_when_redis_unavailable(self) -> None:
        from app.docker_quota.cache import get_system_df_cache_info

        with patch("app.docker_quota.cache._get_redis_client", return_value=None):
            assert get_system_df_cache_info() == {"available": False}


class TestGetSystemDf:
    def test_use_cache_true_never_calls_docker(self) -> None:
        with patch(
            "app.docker_quota.cache.get_cached_system_df",
            side_effect=[None, None],
        ) as mock_get_cached:
            with patch("app.docker_quota.docker_client.redis_lock") as mock_lock:
                result = get_system_df(include_volumes=True, use_cache=True)
        mock_lock.assert_not_called()
        assert mock_get_cached.call_count == 2
        assert result == {"containers": {}, "images": {}, "volumes": {}}

    def test_use_cache_true_returns_stale_without_docker(self) -> None:
        stale = _sample_df(include_volumes=True)
        with patch(
            "app.docker_quota.cache.get_cached_system_df",
            side_effect=[None, stale],
        ):
            result = get_system_df(include_volumes=True, use_cache=True)
        assert result == stale

    def test_use_cache_false_calls_docker_and_writes_cache(self, fake_redis: MagicMock) -> None:
        api_df = {
            "Containers": [{"Id": "cid1", "SizeRw": 100}],
            "Images": [{"Id": "iid1", "Size": 200}],
        }
        mock_client = MagicMock()
        mock_client.api.df.return_value = api_df
        mock_docker_mod = MagicMock()
        mock_docker_mod.from_env.return_value = mock_client

        with patch.dict("sys.modules", {"docker": mock_docker_mod}):
            with patch("app.docker_quota.cache._get_redis_client", return_value=fake_redis):
                with patch("app.docker_quota.cache._get_df_stale_cache_ttl", return_value=3600):
                    result = get_system_df(use_cache=False)
                    cached = get_cached_system_df(include_volumes=False, allow_stale=True)

        mock_client.api.df.assert_called_once()
        mock_client.close.assert_called_once()
        assert result["containers"] == {"cid1": 100}
        assert result["images"] == {"iid1": 200}
        assert cached == result

    def test_use_cache_false_still_runs_when_redis_unavailable(self) -> None:
        api_df = {
            "Containers": [{"Id": "cid1", "SizeRw": 42}],
            "Images": [],
        }
        mock_client = MagicMock()
        mock_client.api.df.return_value = api_df
        mock_docker_mod = MagicMock()
        mock_docker_mod.from_env.return_value = mock_client

        with patch.dict("sys.modules", {"docker": mock_docker_mod}):
            with patch("app.docker_quota.cache._get_redis_client", return_value=None):
                result = get_system_df(use_cache=False)

        mock_client.api.df.assert_called_once()
        assert result["containers"] == {"cid1": 42}
