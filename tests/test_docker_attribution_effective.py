"""Smoke tests: effective Docker attribution (override wins) and image cascade."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models_db  # noqa: F401  # register models on Base.metadata
from app.db import Base
from app.models_db import DockerContainerAttribution, DockerContainerAttributionOverride
import app.docker_quota.attribution_store as attr_store


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
        with patch.object(attr_store, "get_layers_for_image", return_value=["L1", "L2"]):
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


if __name__ == "__main__":
    unittest.main()
