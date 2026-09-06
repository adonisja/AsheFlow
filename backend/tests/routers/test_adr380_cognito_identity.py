"""The Cognito Username is not the email, and a group failure is not best-effort.

ADR-380 F7 — which identifier names a Cognito account depends on how far through
onboarding the employee is:

    pre-registration    AdminCreateUser used the EMAIL as the Username
    post-registration   complete_registration derived firstname.lastname

Three sites guessed the email, and each was a SILENT no-op on a registered
employee: Cognito raises UserNotFoundException and every one of them swallowed
it into a log line.

ADR-380 D1 — the group assignment during registration logged and continued. The
resulting account signs in successfully and behaves wrong: RoleChecker prefers
the DB role so the API works, but the web client routes entirely on
`groups.includes(...)`, so a dispatch hire lands on the worker view.
"""
import inspect
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from fastapi import HTTPException

from app.routers import employees as E
from app.routers import registration as R
from app.routers.employees import cognito_username_for


class _Emp:
    def __init__(self, username=None, email=None):
        self.username = username
        self.email = email


class TestUsernameResolution:
    def test_a_registered_employee_resolves_to_their_derived_username(self):
        assert cognito_username_for(_Emp("jane.smith", "jane@x.com")) == "jane.smith"

    def test_an_unregistered_employee_resolves_to_their_email(self):
        """Pre-registration the Cognito Username IS the email."""
        assert cognito_username_for(_Emp(None, "pending@x.com")) == "pending@x.com"

    def test_username_wins_over_email(self):
        """Order matters: email-first is exactly the bug."""
        assert cognito_username_for(_Emp("jane.smith", "jane@x.com")) != "jane@x.com"

    def test_neither_resolves_to_none_rather_than_a_guess(self):
        """cognito_sub is deliberately NOT a fallback -- reaching for it hides
        that neither identifier was stamped."""
        assert cognito_username_for(_Emp(None, None)) is None


class TestNoSiteGuessesTheEmail:
    """Every Cognito call in employees.py must resolve, not assume."""

    def test_no_call_site_assigns_the_bare_email(self):
        src = inspect.getsource(E)
        assert "cognito_username = db_employee.email" not in src, (
            "a site resolves the Cognito Username as the bare email -- correct "
            "only pre-registration (ADR-380 F7)"
        )
        assert "db_employee.email or db_employee.cognito_sub" not in src, (
            "a site skips Employee.username entirely (ADR-380 F7)"
        )

    def test_every_resolution_goes_through_the_helper(self):
        """One definition, not a repeated idiom that can drift again."""
        src = inspect.getsource(E)
        assigns = [l for l in src.splitlines() if "cognito_username = " in l]
        assert assigns, "no resolution sites found -- did they move?"
        assert all("cognito_username_for(" in l for l in assigns), (
            f"a site resolves without the helper: {assigns}"
        )

    def test_the_wrong_email_recovery_branches_on_registration(self):
        """A registered employee is UPDATED, not deleted-and-recreated -- the
        old path orphaned their real account and made a second one."""
        src = inspect.getsource(E.update_employee)
        assert "admin_update_user_attributes" in src
        assert "and db_employee.username):" in src, (
            "the registered branch must be selected on Employee.username"
        )

    def test_the_corrected_email_is_marked_verified(self):
        """forgot-password recovers on verified_email only; leaving it
        unverified breaks the recovery path the correction exists to restore."""
        src = inspect.getsource(E.update_employee)
        assert '{"Name": "email_verified", "Value": "true"}' in src


class TestGroupAssignmentIsNotBestEffort:
    def _cognito_that_fails_group_add(self):
        c = MagicMock()
        c.admin_create_user.return_value = {
            "User": {"Attributes": [{"Name": "sub", "Value": "sub-123"}]}
        }
        c.admin_add_user_to_group.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "no group"}},
            "AdminAddUserToGroup",
        )
        return c

    def test_it_retries_before_giving_up(self):
        src = inspect.getsource(R.complete_registration)
        assert "for attempt in range(3):" in src, (
            "a transient Cognito error must not fail a registration on the "
            "first try"
        )

    def test_it_raises_rather_than_logging_and_continuing(self):
        """The whole point. A half-provisioned account that looks fine is
        discovered by the employee on their first shift."""
        src = inspect.getsource(R.complete_registration)
        i = src.index("AdminAddUserToGroup exhausted retries")
        window = src[i:i + 1400]
        assert "raise HTTPException" in window
        assert "HTTP_502_BAD_GATEWAY" in window

    def test_it_raises_a_platform_alert(self):
        """A Cognito group is platform infrastructure -- a company admin cannot
        create one, so somebody must learn it is broken (ADR-336 D1)."""
        src = inspect.getsource(R.complete_registration)
        assert "raise_platform_alert" in src
        assert "IDENTITY_PROVISIONING_MESSAGE" in src

    def test_the_alert_message_describes_provisioning_not_revocation(self):
        """Same alert TYPE (one per integration), but the revocation message
        says the opposite thing -- someone who should not get in."""
        from app.services.integration_alerts import (
            IDENTITY_PROVISIONING_MESSAGE,
            IDENTITY_REVOCATION_MESSAGE,
        )
        assert "group assignment failed" in IDENTITY_PROVISIONING_MESSAGE.lower()
        assert IDENTITY_PROVISIONING_MESSAGE != IDENTITY_REVOCATION_MESSAGE

    def test_it_fails_before_consuming_the_invite_token(self):
        """So the employee can retry. Verified by ORDER in the source, because
        the alternative -- a burnt token and no account -- is unrecoverable
        without a manager."""
        src = inspect.getsource(R.complete_registration)
        assert src.index("AdminAddUserToGroup exhausted retries") < src.index(
            "record.used = True"
        ), "a group failure must not consume the invite token"

    def test_it_fails_before_stamping_the_employee(self):
        src = inspect.getsource(R.complete_registration)
        assert src.index("AdminAddUserToGroup exhausted retries") < src.index(
            "employee.username     = username"
        )
