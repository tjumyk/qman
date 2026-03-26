"""Tests for audit event timestamp parsing used by attribution sync."""

from __future__ import annotations

import unittest
from datetime import datetime

from app.docker_quota.attribution_sync import _audit_event_ts_float


class TestAuditEventTsFloat(unittest.TestCase):
    def test_timestamp_unix_float(self) -> None:
        self.assertAlmostEqual(
            _audit_event_ts_float({"timestamp_unix": 1774339582.741}),
            1774339582.741,
            places=3,
        )

    def test_timestamp_unix_int(self) -> None:
        self.assertEqual(
            _audit_event_ts_float({"timestamp_unix": 1700000000}),
            1700000000.0,
        )

    def test_epoch_string_in_timestamp(self) -> None:
        self.assertAlmostEqual(
            _audit_event_ts_float({"timestamp": "1774339582.741"}),
            1774339582.741,
            places=3,
        )

    def test_interpreted_date_string(self) -> None:
        s = "02/16/2026 12:34:56"
        got = _audit_event_ts_float({"timestamp": s})
        want = datetime.strptime(s, "%m/%d/%Y %H:%M:%S").timestamp()
        self.assertAlmostEqual(got, want, places=5)

    def test_prefers_timestamp_unix_over_timestamp(self) -> None:
        self.assertEqual(
            _audit_event_ts_float(
                {"timestamp_unix": 1.0, "timestamp": "02/16/2026 12:34:56"}
            ),
            1.0,
        )

    def test_empty_returns_none(self) -> None:
        self.assertIsNone(_audit_event_ts_float({}))
        self.assertIsNone(_audit_event_ts_float({"timestamp": ""}))
        self.assertIsNone(_audit_event_ts_float({"timestamp": "   "}))
