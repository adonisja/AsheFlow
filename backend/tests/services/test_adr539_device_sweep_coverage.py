"""ADR-539 — the device sweep reaches accounts with no Employee row, and the
privileged limit is checked hourly.

These drive sweep_stale_devices ITSELF. ADR-385's tests pinned every part --
the TTLs, select_stale, tier_for -- and all of them passed while the task's
loop never reached adon, because adon has no Employee row on either pool.
Cognito is stubbed at the task's own seams (real names, no create=True).
"""
import uuid
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.services import device_fleet
from app.tasks import device_sweep
from tests.conftest import make_employee

# ADR-540: privileged = 12h since the last MFA; field = 7 days idle.
PRIV = (device_fleet.PRIVILEGED_CHALLENGE_TTL, "created")
FIELD = (device_fleet.FIELD_DEVICE_TTL, "last_auth")


class _Cognito:
    """Records which usernames were swept and at what TTL."""

    def __init__(self, groups_by_user=None, platform=None, enrolled=True):
        self.groups_by_user = groups_by_user or {}
        self.platform = platform
        self.enrolled = enrolled
        self.swept = {}
        self.alerts = []

    def forget_stale(self, username, pool_id, region, ttl, now=None, since="last_auth"):
        assert username not in self.swept, f"{username} swept twice"
        self.swept[username] = (ttl, since)
        return 1

    def run(self, db, **kwargs):
        with patch.object(device_sweep, "SessionLocal", return_value=db), \
             patch.object(device_sweep, "_groups_for",
                          side_effect=lambda u: self.groups_by_user.get(u, set())), \
             patch.object(device_sweep, "_platform_usernames",
                          return_value=self.platform), \
             patch.object(device_sweep.mfa_status, "is_enrolled",
                          return_value=self.enrolled), \
             patch.object(device_fleet, "forget_stale", side_effect=self.forget_stale), \
             patch.object(device_sweep, "raise_platform_alert",
                          side_effect=lambda db, **kw: self.alerts.append(kw)):
            return device_sweep.sweep_stale_devices(**kwargs)


def _registered(db, role, username):
    emp = make_employee(db, role=role)
    emp.cognito_sub = str(uuid.uuid4())
    emp.username = username
    db.commit()
    return emp


class TestAPlatformAccountWithNoRowIsSwept:
    def test_a_super_admin_with_no_employee_row_is_swept_on_the_privileged_rule(self, db):
        """The incident: adon is only in Cognito."""
        c = _Cognito(platform={"adon"})
        result = c.run(db)
        assert c.swept == {"adon": PRIV}
        assert result["platform_checked"] == 1
        assert result["platform_groups_read"] is True

    def test_it_is_swept_by_the_hourly_privileged_run_too(self, db):
        c = _Cognito(platform={"adon"})
        c.run(db, privileged_only=True)
        assert c.swept == {"adon": PRIV}

    def test_a_group_member_with_an_employee_row_is_swept_once(self, db):
        _registered(db, "trainee", "adon")
        c = _Cognito(groups_by_user={"adon": {"super_admin"}}, platform={"adon"})
        result = c.run(db)
        assert c.swept == {"adon": PRIV}
        assert result["platform_checked"] == 0   # covered by the row

    def test_an_unreadable_group_listing_still_sweeps_employees(self, db):
        _registered(db, "driver", "walk.er")
        c = _Cognito(platform=None)
        result = c.run(db)
        assert c.swept == {"walk.er": FIELD}
        assert result["platform_groups_read"] is False


class TestTheHourlyRunIsPrivilegedOnly:
    def test_field_accounts_are_left_to_the_nightly_run(self, db):
        _registered(db, "driver", "dri.ver")
        _registered(db, "admin", "ad.min")
        c = _Cognito(platform=set())
        c.run(db, privileged_only=True)
        assert c.swept == {"ad.min": PRIV}

    def test_the_nightly_run_sweeps_both_tiers(self, db):
        _registered(db, "driver", "dri.ver")
        _registered(db, "admin", "ad.min")
        c = _Cognito(platform=set())
        c.run(db)
        assert c.swept == {"dri.ver": FIELD,
                           "ad.min": PRIV}

    def test_the_hourly_entry_is_scheduled_with_the_switch(self):
        from app.celery_app import celery_app
        entry = celery_app.conf.beat_schedule["sweep-privileged-remembered-devices"]
        assert entry["task"] == "app.tasks.device_sweep.sweep_stale_devices"
        assert entry["kwargs"] == {"privileged_only": True}
        assert entry["schedule"].hour == set(range(24))


class TestTheBackstopNeedsADefiniteNo:
    def test_could_not_tell_raises_no_alert(self, db):
        _registered(db, "admin", "ad.min")
        c = _Cognito(platform={"adon"}, enrolled=None)
        c.run(db)
        assert c.alerts == []

    def test_a_platform_account_with_no_factor_alerts_with_no_tenant(self, db):
        c = _Cognito(platform={"adon"}, enrolled=False)
        c.run(db)
        assert len(c.alerts) == 1
        assert c.alerts[0]["company_id"] is None
        assert c.alerts[0]["severity"] == "critical"

    def test_a_privileged_employee_with_no_factor_still_alerts(self, db):
        company_id = _registered(db, "admin", "ad.min").company_id  # before the task closes the session
        c = _Cognito(platform=set(), enrolled=False)
        c.run(db)
        assert [a["company_id"] for a in c.alerts] == [company_id]


def test_platform_groups_are_listed_from_the_configured_pool():
    """_platform_usernames pages both groups of the pool the app is using."""
    calls = []

    class _Pager:
        def paginate(self, UserPoolId, GroupName):
            calls.append((UserPoolId, GroupName))
            return [{"Users": [{"Username": f"{GroupName}-1"}]},
                    {"Users": [{"Username": f"{GroupName}-2"}]}]

    class _Client:
        def get_paginator(self, name):
            assert name == "list_users_in_group"
            return _Pager()

    with patch("boto3.client", return_value=_Client()):
        names = device_sweep._platform_usernames()
    assert names == {"super_admin-1", "super_admin-2",
                     "platform_support-1", "platform_support-2"}
    assert {p for p, _ in calls} == {settings.aws_cognito_user_pool_id}
