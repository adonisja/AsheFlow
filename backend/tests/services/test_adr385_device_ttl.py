"""Remembered devices expire by AGE, per tier (ADR-385).

WHY THIS EXISTS
`MfaConfiguration: ON` cannot express "daily for admins, weekly for field" -- it
has no per-group dimension, and it would collapse the field grace period to zero
because Cognito refuses tokens before any of our code runs. Cadence therefore
lives in a scheduled AdminForgetDevice sweep, and these tests pin its rules.

The AGE rule is distinct from the COUNT rule (MAX_REMEMBERED_DEVICES). Neither
subsumes the other, so select_stale gets its own tests rather than reusing
select_for_eviction's.
"""
from datetime import datetime, timedelta, timezone

from app.services import device_fleet as df
from app.services import mfa_status


NOW = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)


def _dev(key: str, hours_ago: float | None, remembered: bool = True) -> df.Device:
    last = None if hours_ago is None else NOW - timedelta(hours=hours_ago)
    return df.Device(key=key, last_auth=last, remembered=remembered)


class TestTheTtlsMatchThePolicy:
    def test_privileged_is_24_hours(self):
        """NIST SP 800-63B puts the AAL2 reauthentication ceiling at 24h."""
        assert df.PRIVILEGED_DEVICE_TTL == timedelta(hours=24)

    def test_field_is_7_days(self):
        """Below Duo's 30-day default deliberately; well above per-session."""
        assert df.FIELD_DEVICE_TTL == timedelta(days=7)

    def test_field_is_longer_than_privileged(self):
        """The whole point: a field phone drops sessions constantly on mobile
        networks, so it must be challenged LESS often than an admin laptop."""
        assert df.FIELD_DEVICE_TTL > df.PRIVILEGED_DEVICE_TTL


class TestSelectStale:
    def test_a_device_inside_the_ttl_survives(self):
        devs = [_dev("fresh", hours_ago=1)]
        assert df.select_stale(devs, df.PRIVILEGED_DEVICE_TTL, now=NOW) == []

    def test_a_device_past_the_ttl_is_selected(self):
        devs = [_dev("stale", hours_ago=25)]
        got = df.select_stale(devs, df.PRIVILEGED_DEVICE_TTL, now=NOW)
        assert [d.key for d in got] == ["stale"]

    def test_the_boundary_is_not_inclusive(self):
        """Exactly at the TTL is still trusted; a device is stale only once it is
        PAST it. Prevents a device being forgotten on the tick it was used."""
        devs = [_dev("exact", hours_ago=24)]
        assert df.select_stale(devs, df.PRIVILEGED_DEVICE_TTL, now=NOW) == []

    def test_a_never_authenticated_device_is_stale(self):
        """No DeviceLastAuthenticatedDate means it never completed an auth, so it
        has no claim to be trusted. Treating a missing timestamp as `now` would
        make an unproven device permanently un-forgettable."""
        devs = [_dev("never", hours_ago=None)]
        got = df.select_stale(devs, df.PRIVILEGED_DEVICE_TTL, now=NOW)
        assert [d.key for d in got] == ["never"]

    def test_a_not_remembered_device_is_left_alone(self):
        """It is already challenged on every sign-in. Forgetting it is a wasted
        API call, and the sweep runs across every employee."""
        devs = [_dev("inert", hours_ago=999, remembered=False)]
        assert df.select_stale(devs, df.FIELD_DEVICE_TTL, now=NOW) == []

    def test_the_two_tiers_disagree_about_the_same_device(self):
        """A 3-day-old device: stale for an admin, fine for a walker. This is the
        behaviour MfaConfiguration could not express at all."""
        devs = [_dev("d", hours_ago=72)]
        assert [d.key for d in df.select_stale(devs, df.PRIVILEGED_DEVICE_TTL, now=NOW)] == ["d"]
        assert df.select_stale(devs, df.FIELD_DEVICE_TTL, now=NOW) == []


class TestTierSelectionCannotInvertPrivilege:
    """The bug this nearly shipped with.

    tier_for(role, groups=None) classifies by Employee.role alone. `super_admin`
    and `platform_support` are NOT in Employee.VALID_ROLES -- a DB constraint
    rejects them -- so they exist ONLY as Cognito groups. Measured on prod:
    `adon` is `super_admin` in Cognito and `trainee` on its Employee row.
    """

    def test_role_alone_puts_a_super_admin_on_the_field_tier(self):
        assert mfa_status.tier_for("trainee", groups=None) == "field"

    def test_groups_correct_it(self):
        assert mfa_status.tier_for("trainee", groups={"super_admin"}) == "privileged"

    def test_the_ttl_that_would_have_been_applied_is_the_wrong_one(self):
        """Concretely: 7 days instead of 24 hours for the platform's highest
        privilege account."""
        wrong = (df.PRIVILEGED_DEVICE_TTL
                 if mfa_status.tier_for("trainee", groups=None) == "privileged"
                 else df.FIELD_DEVICE_TTL)
        right = (df.PRIVILEGED_DEVICE_TTL
                 if mfa_status.tier_for("trainee", groups={"super_admin"}) == "privileged"
                 else df.FIELD_DEVICE_TTL)
        assert wrong == df.FIELD_DEVICE_TTL
        assert right == df.PRIVILEGED_DEVICE_TTL

    def test_groups_never_demote(self):
        """Escalation only -- a dispatch employee whose groups are unreadable
        keeps privileged from the role, rather than being downgraded to field."""
        assert mfa_status.tier_for("dispatch", groups=None) == "privileged"
        assert mfa_status.tier_for("dispatch", groups=set()) == "privileged"
