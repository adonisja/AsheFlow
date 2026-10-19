"""ADR-540 D1 — a privileged device is forgotten 12 hours after it last passed
MFA, however often it is used.

ADR-385 shipped an IDLE rule (DeviceLastAuthenticatedDate), so a laptop
signed in on every morning was never re-challenged. The privileged rule now
reads DeviceCreateDate: forgetting deletes the record, so the next challenged
sign-in creates a fresh one, and its creation time IS the last MFA.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.services import device_fleet as df

NOW = datetime(2026, 10, 18, 21, 0, tzinfo=timezone.utc)


def _dev(key, created_h, used_h, remembered=True):
    ago = lambda h: None if h is None else NOW - timedelta(hours=h)
    return df.Device(key=key, last_auth=ago(used_h), remembered=remembered,
                     created=ago(created_h))


class TestTheDailyDriverIsRechallenged:
    def test_a_device_used_minutes_ago_is_forgotten_13h_after_its_mfa(self):
        """The incident: in daily use, so the idle rule never fired."""
        devs = [_dev("laptop", created_h=13, used_h=0.1)]
        assert [d.key for d in df.select_unchallenged(devs, df.PRIVILEGED_CHALLENGE_TTL, now=NOW)] == ["laptop"]
        assert df.select_stale(devs, df.PRIVILEGED_CHALLENGE_TTL, now=NOW) == []   # the old rule kept it

    def test_inside_12h_it_survives(self):
        devs = [_dev("laptop", created_h=11.9, used_h=11.9)]
        assert df.select_unchallenged(devs, df.PRIVILEGED_CHALLENGE_TTL, now=NOW) == []

    def test_the_boundary_is_not_inclusive(self):
        devs = [_dev("exact", created_h=12, used_h=1)]
        assert df.select_unchallenged(devs, df.PRIVILEGED_CHALLENGE_TTL, now=NOW) == []

    def test_a_device_with_no_creation_date_is_not_trusted(self):
        devs = [_dev("unknown", created_h=None, used_h=0)]
        assert [d.key for d in df.select_unchallenged(devs, df.PRIVILEGED_CHALLENGE_TTL, now=NOW)] == ["unknown"]

    def test_a_not_remembered_device_is_left_alone(self):
        devs = [_dev("inert", created_h=999, used_h=999, remembered=False)]
        assert df.select_unchallenged(devs, df.PRIVILEGED_CHALLENGE_TTL, now=NOW) == []

    def test_twelve_hours_covers_a_shift_with_a_buffer(self):
        """Owner, 2026-10-18: an 8-hour shift must never be interrupted."""
        assert df.PRIVILEGED_CHALLENGE_TTL >= timedelta(hours=8) + timedelta(hours=4)


class TestParseReadsTheCreationDate:
    def test_device_create_date_is_kept(self):
        created = NOW - timedelta(hours=3)
        [d] = df.parse_devices([{
            "DeviceKey": "k", "DeviceCreateDate": created, "DeviceLastAuthenticatedDate": NOW,
            "DeviceAttributes": [{"Name": "dev:device_remembered_status", "Value": "remembered"}],
        }])
        assert d.created == created


class TestForgetStaleChoosesTheRule:
    def _run(self, since):
        forgotten = []

        class _Client:
            def admin_list_devices(self, **kw):
                return {"Devices": [{
                    "DeviceKey": "laptop",
                    "DeviceCreateDate": NOW - timedelta(hours=13),
                    "DeviceLastAuthenticatedDate": NOW - timedelta(minutes=5),
                    "DeviceAttributes": [{"Name": "dev:device_remembered_status", "Value": "remembered"}],
                }]}

            def admin_forget_device(self, **kw):
                forgotten.append(kw["DeviceKey"])

        with patch("boto3.client", return_value=_Client()):
            n = df.forget_stale("adon", "pool", "us-east-2", df.PRIVILEGED_CHALLENGE_TTL,
                                now=NOW, since=since)
        return n, forgotten

    def test_created_forgets_the_daily_driver(self):
        assert self._run("created") == (1, ["laptop"])

    def test_last_auth_keeps_it(self):
        assert self._run("last_auth") == (0, [])

    def test_an_unknown_basis_is_refused(self):
        with pytest.raises(ValueError):
            self._run("whenever")
