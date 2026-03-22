"""Smoke tests: effective Docker attribution (override wins) and image cascade."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models_db  # noqa: F401  # register models on Base.metadata
from app.db import Base
from app.models_db import (
    DockerContainerAttribution,
    DockerContainerAttributionOverride,
    DockerLayerAttributionOverride,
)
import app.docker_quota.attribution_store as attr_store
from app.docker_quota.quota import _aggregate_usage_by_uid


def _memory_session_factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


class TestEffectiveDockerAttribution(unittest.TestCase):
    def setUp(self) -> None:
        self._session_factory = _memory_session_factory()
        self._patch = patch.object(attr_store, "SessionLocal", self._session_factory)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()

    def test_container_override_wins_over_auto(self) -> None:
        db = self._session_factory()
        db.add(
            DockerContainerAttribution(
                container_id="c1",
                host_user_name="auto_user",
                uid=1,
                image_id=None,
                size_bytes=0,
            )
        )
        db.add(
            DockerContainerAttributionOverride(
                container_id="c1",
                host_user_name="manual_user",
                uid=99,
                resolved_by_oauth_user_id=7,
            )
        )
        db.commit()
        db.close()

        eff = attr_store.get_container_effective_attributions()
        row = next(r for r in eff if r["container_id"] == "c1")
        self.assertEqual(row["host_user_name"], "manual_user")
        self.assertEqual(row["uid"], 99)

    def test_image_cascade_writes_layer_overrides(self) -> None:
        with (
            patch.object(attr_store, "get_layers_for_image", return_value=["L1", "L2"]),
            patch(
                "app.docker_quota.docker_client.collect_layer_id_to_size_from_all_images",
                return_value={"L1": 10, "L2": 20},
            ),
        ):
            attr_store.set_image_attribution_override(
                image_id="img1",
                puller_host_user_name="u",
                puller_uid=5,
                resolved_by_oauth_user_id=1,
                cascade=True,
            )
        o1 = attr_store.get_layer_attribution_override("L1")
        o2 = attr_store.get_layer_attribution_override("L2")
        self.assertIsNotNone(o1)
        self.assertIsNotNone(o2)
        assert o1 is not None and o2 is not None
        self.assertEqual(o1["first_puller_host_user_name"], "u")
        self.assertEqual(o2["first_puller_uid"], 5)
        self.assertEqual(o1["size_bytes"], 10)
        self.assertEqual(o2["size_bytes"], 20)

    def test_layer_effective_override_only_null_size_is_none(self) -> None:
        db = self._session_factory()
        db.add(
            DockerLayerAttributionOverride(
                layer_id="L0",
                first_puller_host_user_name="u",
                first_puller_uid=3,
                size_bytes=None,
                resolved_by_oauth_user_id=1,
            )
        )
        db.commit()
        db.close()

        eff = attr_store.get_layer_effective_attributions()
        row = next(r for r in eff if r["layer_id"] == "L0")
        self.assertIsNone(row["size_bytes"])

    def test_layer_effective_override_only_zero_size_is_zero(self) -> None:
        db = self._session_factory()
        db.add(
            DockerLayerAttributionOverride(
                layer_id="Lz",
                first_puller_host_user_name="u",
                first_puller_uid=3,
                size_bytes=0,
                resolved_by_oauth_user_id=1,
            )
        )
        db.commit()
        db.close()

        eff = attr_store.get_layer_effective_attributions()
        row = next(r for r in eff if r["layer_id"] == "Lz")
        self.assertEqual(row["size_bytes"], 0)

    def test_aggregate_does_not_scan_images_when_layer_size_known_zero(self) -> None:
        layer_row = {
            "layer_id": "Lz",
            "first_puller_uid": 10,
            "first_puller_host_user_name": "u10",
            "size_bytes": 0,
            "first_seen_at": None,
            "creation_method": None,
        }

        def _fail_collect(*_a: object, **_k: object) -> dict[str, int]:
            raise AssertionError("collect_layer_id_to_size_from_all_images should not run")

        with (
            patch("app.docker_quota.quota.get_container_effective_attributions", return_value=[]),
            patch("app.docker_quota.quota.get_layer_effective_attributions", return_value=[layer_row]),
            patch("app.docker_quota.quota.get_volume_effective_attributions", return_value=[]),
            patch("app.docker_quota.quota.get_volume_disk_usage_all", return_value=[]),
            patch("app.docker_quota.quota.get_system_df", return_value={"containers": {}, "images": {}, "volumes": {}}),
            patch(
                "app.docker_quota.quota.collect_layer_id_to_size_from_all_images",
                side_effect=_fail_collect,
            ),
        ):
            usage_by_uid, _total, _unattributed, _bd = _aggregate_usage_by_uid(
                "/var/lib/docker", None, container_ids=[], use_cache=False
            )
        self.assertEqual(usage_by_uid.get(10, 0), 0)

    def test_aggregate_scans_when_layer_size_unknown(self) -> None:
        layer_row = {
            "layer_id": "Lu",
            "first_puller_uid": 11,
            "first_puller_host_user_name": "u11",
            "size_bytes": None,
            "first_seen_at": None,
            "creation_method": None,
        }
        with (
            patch("app.docker_quota.quota.get_container_effective_attributions", return_value=[]),
            patch("app.docker_quota.quota.get_layer_effective_attributions", return_value=[layer_row]),
            patch("app.docker_quota.quota.get_volume_effective_attributions", return_value=[]),
            patch("app.docker_quota.quota.get_volume_disk_usage_all", return_value=[]),
            patch("app.docker_quota.quota.get_system_df", return_value={"containers": {}, "images": {}, "volumes": {}}),
            patch(
                "app.docker_quota.quota.collect_layer_id_to_size_from_all_images",
                return_value={"Lu": 42},
            ),
        ):
            usage_by_uid, _total, _unattributed, _bd = _aggregate_usage_by_uid(
                "/var/lib/docker", None, container_ids=[], use_cache=False
            )
        self.assertEqual(usage_by_uid.get(11), 42)


if __name__ == "__main__":
    unittest.main()
