"""Creating platform staff in the product (ADR-394).

WHY THIS EXISTS
ADR-389 found that a super admin can neither call the MFA reset nor be its
target, so the mitigation is operational: keep two super admins. That control
lived only as two CLI commands in a runbook -- unaudited, untested, and
unavailable to anyone without AWS credentials.

The security-relevant assertions here are the GATE and the GROUP ALLOW-LIST.
Both are ways a caller could escalate their own privilege.
"""
import inspect

from app.routers import platform_alerts as P


class TestOnlyASuperAdminCanCreateStaff:
    def test_create_is_gated_on_get_super_admin(self):
        """NOT get_platform_staff. ADR-343 D1 split those so a support engineer
        onboarded to investigate cannot change a customer's world -- and creating
        a super admin is the most privileged write in the system. A
        platform_support caller reaching this could promote themselves."""
        # The SIGNATURE, not the source text: the docstring explains why
        # get_platform_staff is NOT used, so a substring check matches the prose
        # that documents the very absence being asserted.
        sig = inspect.signature(P.create_platform_staff)
        deps = [
            p.default.dependency.__name__
            for p in sig.parameters.values()
            if hasattr(p.default, "dependency")
        ]
        assert "get_super_admin" in deps, deps
        assert "get_platform_staff" not in deps, deps

    def test_listing_is_gated_on_platform_staff(self):
        """A READ. Support should see who else has access without granting it."""
        sig = inspect.signature(P.list_platform_staff)
        deps = [
            p.default.dependency.__name__
            for p in sig.parameters.values()
            if hasattr(p.default, "dependency")
        ]
        assert "get_platform_staff" in deps, deps


class TestOnlyPlatformGroupsCanBeGranted:
    def test_the_allow_list_is_exactly_the_two_platform_groups(self):
        assert P.PLATFORM_GROUPS == ("super_admin", "platform_support")

    def test_no_tenant_role_is_grantable(self):
        """Granting `admin` or `dispatch` here would create a Cognito user with
        no company and no Employee row -- the ghost-account shape that 403s on
        every request and cost a staging debugging session."""
        for role in ("admin", "management", "dispatch", "walker", "driver"):
            assert role not in P.PLATFORM_GROUPS

    def test_a_tenant_role_is_REFUSED_by_the_endpoint(self):
        """Calls the function. A source check for "PLATFORM_GROUPS" passes even
        with the validation deleted -- the name still appears in list_platform_staff's
        loop -- so removing the guard entirely survived that assertion.

        This must reject BEFORE any Cognito call: a rejected request that already
        created the user is not a rejection.
        """
        import pytest
        from fastapi import HTTPException
        from unittest.mock import MagicMock, patch

        body = P.PlatformStaffCreate(
            email="x@example.com", name="X", group="admin",
        )
        client = MagicMock()
        with patch("boto3.client", return_value=client):
            with pytest.raises(HTTPException) as exc:
                P.create_platform_staff(body=body, _super={}, db=MagicMock())
        assert exc.value.status_code == 422
        client.admin_create_user.assert_not_called()

    def test_a_platform_group_is_accepted(self):
        """The other half: the guard must not reject what it should allow."""
        from unittest.mock import MagicMock, patch

        body = P.PlatformStaffCreate(
            email="ok@example.com", name="OK", group="platform_support",
        )
        client = MagicMock()
        with patch("boto3.client", return_value=client), \
             patch.object(P, "write_audit"):
            out = P.create_platform_staff(body=body, _super={}, db=MagicMock())
        assert out.group == "platform_support"
        client.admin_create_user.assert_called_once()


class TestItDoesNotCreateAnEmployeeRow:
    def test_no_employee_model_is_touched(self):
        """get_super_admin never touches the Employee table (ADR-274 D13/D14)
        because the platform owner has no tenant. A row here would leak them into
        company-scoped queries. This is the one place a Cognito user with no
        Employee row is CORRECT rather than a ghost."""
        src = inspect.getsource(P.create_platform_staff)
        assert "Employee(" not in src
        assert "db.add(" not in src


class TestTheAuditRowSurvivesAMissingEmployeeRow:
    def test_actor_id_is_none_and_identity_is_in_detail(self):
        """actor_id is a FK to employees.id and a super admin has no row, so
        writing their sub there raises ForeignKeyViolation and 500s the endpoint
        (ADR-274 D13). The identity goes in the JSONB payload instead."""
        src = inspect.getsource(P.create_platform_staff)
        assert "actor_id=None" in src
        assert "super_admin_identity" in src


class TestNoCredentialIsReturned:
    def test_the_response_model_has_no_password_field(self):
        assert "password" not in {f.lower() for f in P.PlatformStaffOut.model_fields}

    def test_cognito_emails_the_temporary_password(self):
        src = inspect.getsource(P.create_platform_staff)
        assert 'DesiredDeliveryMediums=["EMAIL"]' in src


class TestAHalfCreatedAccountIsNotReportedAsSuccess:
    def test_a_failed_group_assignment_raises(self):
        """An account with no group holds no privilege. Reporting success would
        leave something that LOOKS like a rescuer and is not -- which is the
        ADR-389 failure this endpoint exists to prevent."""
        src = inspect.getsource(P.create_platform_staff)
        idx = src.index("admin_add_user_to_group")
        after = src[idx:]
        assert "HTTPException" in after, "a failed group assignment must not return 200"


class TestTheRequestIsBounded:
    def test_extra_keys_are_forbidden(self):
        assert P.PlatformStaffCreate.model_config.get("extra") == "forbid"

    def test_name_is_length_bounded(self):
        f = P.PlatformStaffCreate.model_fields["name"]
        meta = str(f.metadata)
        assert "255" in meta, "an unbounded free-text field lands in Cognito"
