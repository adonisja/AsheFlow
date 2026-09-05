"""Three remembered devices, evicting least-recently-used (ADR-377 D3).

Cognito enforces NO per-user device cap, so this is ours. Two measurements from
the ADR-377 scratch-pool probe shape it:

  - Cognito holds exactly ONE software token per user. Verifying a new secret
    invalidates the old one, so "2-3 devices" cannot mean 2-3 authenticators --
    a walker enrolling on a station desktop would lock their phone out. It means
    remembered DEVICES, a separate and genuinely uncapped mechanism.
  - Remembered devices are what skip the challenge, so only they count.

Eviction rather than refusal: refusing a 4th device punishes someone for
replacing their phone and produces a support ticket at 05:00.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.device_fleet import (
    MAX_REMEMBERED_DEVICES,
    Device,
    enforce_cap,
    parse_devices,
    select_for_eviction,
)

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def _dev(key, days_ago=1, remembered=True):
    return Device(key=key, last_auth=NOW - timedelta(days=days_ago),
                  remembered=remembered)


class TestTheCap:
    def test_the_cap_is_three(self):
        """2 forces a re-challenge every time someone alternates phone/laptop."""
        assert MAX_REMEMBERED_DEVICES == 3

    def test_at_the_cap_nothing_is_evicted(self):
        assert select_for_eviction([_dev("a"), _dev("b"), _dev("c")]) == []

    def test_under_the_cap_nothing_is_evicted(self):
        assert select_for_eviction([_dev("a")]) == []

    def test_a_fourth_device_evicts_the_least_recently_used(self):
        doomed = select_for_eviction([
            _dev("phone", 1), _dev("laptop", 2), _dev("station", 3), _dev("old", 40),
        ])
        assert [d.key for d in doomed] == ["old"]

    def test_several_over_the_cap_are_all_evicted_oldest_first(self):
        doomed = select_for_eviction([
            _dev("a", 1), _dev("b", 2), _dev("c", 3),
            _dev("x", 7), _dev("y", 8), _dev("z", 9),
        ])
        assert [d.key for d in doomed] == ["z", "y", "x"], (
            "eviction must be oldest-first, and must leave exactly the cap"
        )

    def test_the_survivors_are_the_most_recently_used(self):
        all_devs = [_dev("a", 1), _dev("b", 2), _dev("c", 3), _dev("old", 40)]
        doomed = {d.key for d in select_for_eviction(all_devs)}
        survivors = {d.key for d in all_devs} - doomed
        assert survivors == {"a", "b", "c"}


class TestOnlyRememberedDevicesCount:
    def test_unremembered_devices_do_not_count_toward_the_cap(self):
        """A not_remembered row grants nothing, so counting it would evict a
        live device to make room for an inert one."""
        devs = [_dev("a"), _dev("b"), _dev("c"),
                _dev("inert", 50, remembered=False)]
        assert select_for_eviction(devs) == []

    def test_unremembered_devices_are_never_returned_for_eviction(self):
        """Forgetting an already-forgotten device is a wasted API call."""
        devs = [_dev("a", 1), _dev("b", 2), _dev("c", 3), _dev("d", 4),
                _dev("inert", 99, remembered=False)]
        assert all(d.remembered for d in select_for_eviction(devs))


class TestTheOrdering:
    def test_a_device_with_no_timestamp_is_evicted_first(self):
        """Never authenticated on. Treating a missing timestamp as NEWEST would
        protect the least proven device and evict a phone in daily use."""
        never = Device(key="never", last_auth=None, remembered=True)
        doomed = select_for_eviction([_dev("a", 1), _dev("b", 2), _dev("c", 3), never])
        assert [d.key for d in doomed] == ["never"]

    def test_a_zero_cap_is_refused(self):
        """A cap of 0 evicts every device on every sign-in, re-challenging the
        user forever. Refuse the configuration rather than enact it."""
        with pytest.raises(ValueError):
            select_for_eviction([_dev("a")], cap=0)


class TestParsing:
    def test_it_reads_the_remembered_status_attribute(self):
        raw = [{
            "DeviceKey": "us-east-2_abc",
            "DeviceLastAuthenticatedDate": NOW,
            "DeviceAttributes": [
                {"Name": "dev:device_remembered_status", "Value": "remembered"},
                {"Name": "device_status", "Value": "valid"},
            ],
        }]
        [d] = parse_devices(raw)
        assert d.key == "us-east-2_abc" and d.remembered is True

    def test_a_not_remembered_device_parses_as_not_remembered(self):
        raw = [{
            "DeviceKey": "k",
            "DeviceAttributes": [
                {"Name": "dev:device_remembered_status", "Value": "not_remembered"},
            ],
        }]
        assert parse_devices(raw)[0].remembered is False

    def test_a_missing_status_attribute_is_not_remembered(self):
        """Absent must not read as remembered -- that would count an inert row
        against the cap and evict a live device."""
        raw = [{"DeviceKey": "k", "DeviceAttributes": []}]
        assert parse_devices(raw)[0].remembered is False


class TestFailureIsNotLockout:
    def test_an_aws_failure_returns_zero_rather_than_raising(self):
        """This runs on a sign-in path. One extra remembered device is a far
        better outcome than a failed sign-in."""
        assert enforce_cap(
            username="nobody", pool_id="us-east-2_doesnotexist", region="us-east-2",
        ) == 0


class TestTheServiceNeedsIamThatIsEasyToForget:
    """enforce_cap fails SOFT, so a missing IAM permission is invisible.

    Measured on 2026-09-04: both asheflow-ec2-role-staging and -prod could call
    AdminGetUser but NOT AdminListDevices or AdminForgetDevice -- both
    implicitDeny. Eviction would have done nothing in production, logging a
    warning nobody reads, and the unit tests would still have been green.

    These pin the two actions in code so the requirement is discoverable from
    the repo rather than only from a policy simulation.
    """

    def test_the_service_names_the_two_actions_it_needs(self):
        import inspect

        from app.services import device_fleet

        src = inspect.getsource(device_fleet)
        assert "admin_list_devices" in src
        assert "admin_forget_device" in src

    def test_the_iam_requirement_is_documented_in_the_module(self):
        """A reader deploying this to a new environment must learn about the
        permissions without first watching eviction silently no-op."""
        import inspect

        from app.services import device_fleet

        doc = inspect.getdoc(device_fleet) or ""
        assert "AdminListDevices" in doc and "AdminForgetDevice" in doc, (
            "the module docstring must name the IAM actions -- enforce_cap fails "
            "soft, so a missing grant is otherwise invisible"
        )
