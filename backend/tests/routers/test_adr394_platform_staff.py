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
        from botocore.exceptions import ClientError

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
        from botocore.exceptions import ClientError

        body = P.PlatformStaffCreate(
            email="ok@example.com", name="OK", group="platform_support",
        )
        client = MagicMock()
        # ADR-396: the username is derived from the NAME, and derivation probes
        # Cognito for collisions. UserNotFoundException means the name is free.
        client.admin_get_user.side_effect = ClientError(
            {"Error": {"Code": "UserNotFoundException"}}, "AdminGetUser")
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


class TestCreateDoesNotGrantTheGroup:
    """ADR-397. Granting at create makes the account unable to sign in AT ALL:
    PreAuthentication reads the groups, sees an empty UserMFASettingList, and
    refuses BEFORE any password challenge -- so it never reaches enrolment.
    Confirmed in production on `nicoy.hunt`."""

    def test_create_never_calls_add_user_to_group(self):
        src = inspect.getsource(P.create_platform_staff)
        assert "admin_add_user_to_group" not in src, (
            "granting the group at create produces an account that can never "
            "sign in to enrol (ADR-397)"
        )

    def test_the_intended_group_is_recorded_instead(self):
        src = inspect.getsource(P.create_platform_staff)
        assert "custom:pending_group" in src

    def test_the_created_account_is_marked_pending(self):
        from unittest.mock import MagicMock, patch
        from botocore.exceptions import ClientError
        body = P.PlatformStaffCreate(
            email="p@example.com", name="Pending Person", group="super_admin")
        c = MagicMock()
        c.admin_get_user.side_effect = ClientError(
            {"Error": {"Code": "UserNotFoundException"}}, "AdminGetUser")
        with patch("boto3.client", return_value=c), patch.object(P, "write_audit"):
            out = P.create_platform_staff(body=body, _super={}, db=MagicMock())
        assert out.pending is True, "the UI must be able to show unfinished work"


class TestActivateRequiresAFactor:
    def _user(self, *, pending="super_admin", mfa=None, status="CONFIRMED"):
        attrs = [{"Name": "email", "Value": "p@example.com"},
                 {"Name": "name", "Value": "Pending Person"}]
        if pending:
            attrs.append({"Name": "custom:pending_group", "Value": pending})
        u = {"UserAttributes": attrs, "UserStatus": status}
        if mfa:
            u["UserMFASettingList"] = mfa
        return u

    def test_an_account_with_no_factor_is_refused(self):
        """THE guard. Without it this endpoint reintroduces the exact lockout it
        exists to prevent."""
        import pytest
        from fastapi import HTTPException
        from unittest.mock import MagicMock, patch
        c = MagicMock()
        c.admin_get_user.return_value = self._user(mfa=None)
        with patch("boto3.client", return_value=c):
            with pytest.raises(HTTPException) as exc:
                P.activate_platform_staff(username="p", _super={}, db=MagicMock())
        assert exc.value.status_code == 409
        c.admin_add_user_to_group.assert_not_called()

    def test_an_enrolled_account_is_granted(self):
        from unittest.mock import MagicMock, patch
        c = MagicMock()
        c.admin_get_user.return_value = self._user(mfa=["SOFTWARE_TOKEN_MFA"])
        with patch("boto3.client", return_value=c), patch.object(P, "write_audit"):
            out = P.activate_platform_staff(username="p", _super={}, db=MagicMock())
        c.admin_add_user_to_group.assert_called_once()
        assert out.pending is False

    def test_the_marker_is_cleared_only_after_the_grant(self):
        """A failure between the two must leave the account visibly pending
        rather than silently orphaned."""
        order = []
        from unittest.mock import MagicMock, patch
        c = MagicMock()
        c.admin_get_user.return_value = self._user(mfa=["SOFTWARE_TOKEN_MFA"])
        c.admin_add_user_to_group.side_effect = lambda **k: order.append("grant")
        c.admin_delete_user_attributes.side_effect = lambda **k: order.append("clear")
        with patch("boto3.client", return_value=c), patch.object(P, "write_audit"):
            P.activate_platform_staff(username="p", _super={}, db=MagicMock())
        assert order == ["grant", "clear"], order

    def test_a_tampered_group_is_refused(self):
        """The attribute is user-visible metadata; it must not become a grant."""
        import pytest
        from fastapi import HTTPException
        from unittest.mock import MagicMock, patch
        c = MagicMock()
        c.admin_get_user.return_value = self._user(
            pending="admin", mfa=["SOFTWARE_TOKEN_MFA"])
        with patch("boto3.client", return_value=c):
            with pytest.raises(HTTPException) as exc:
                P.activate_platform_staff(username="p", _super={}, db=MagicMock())
        assert exc.value.status_code == 422
        c.admin_add_user_to_group.assert_not_called()

    def test_activate_is_gated_on_super_admin(self):
        sig = inspect.signature(P.activate_platform_staff)
        deps = [p.default.dependency.__name__ for p in sig.parameters.values()
                if hasattr(p.default, "dependency")]
        assert "get_super_admin" in deps, deps


class TestTheRequestIsBounded:
    def test_extra_keys_are_forbidden(self):
        assert P.PlatformStaffCreate.model_config.get("extra") == "forbid"

    def test_name_is_length_bounded(self):
        f = P.PlatformStaffCreate.model_fields["name"]
        meta = str(f.metadata)
        assert "255" in meta, "an unbounded free-text field lands in Cognito"


class TestTheUsernameIsDerivedFromTheName:
    """ADR-396. The first version used the email as the username, making this the
    only account type whose username is not a name -- and a staff list showing
    the same string as username and email reads as a rendering bug."""

    def _free(self):
        from unittest.mock import MagicMock
        from botocore.exceptions import ClientError
        c = MagicMock()
        c.admin_get_user.side_effect = ClientError(
            {"Error": {"Code": "UserNotFoundException"}}, "AdminGetUser")
        return c

    def test_firstname_dot_lastname(self):
        assert P._derive_platform_username(self._free(), "Nicoy Hunt") == "nicoy.hunt"

    def test_punctuation_is_stripped(self):
        assert P._derive_platform_username(self._free(), "Jean-Luc Picard") == "jeanluc.picard"

    def test_a_single_word_name_has_no_dot(self):
        assert P._derive_platform_username(self._free(), "Adon") == "adon"

    def test_a_taken_name_gets_a_suffix(self):
        """Uniqueness is probed against COGNITO, not the Employee table:
        platform staff have no Employee row, so registration.py's check would
        hand out a name Cognito already holds and the create would then 409."""
        from unittest.mock import MagicMock
        from botocore.exceptions import ClientError
        c = MagicMock()
        # First candidate exists; second does not.
        c.admin_get_user.side_effect = [
            {"Username": "nicoy.hunt"},
            ClientError({"Error": {"Code": "UserNotFoundException"}}, "AdminGetUser"),
        ]
        assert P._derive_platform_username(c, "Nicoy Hunt") == "nicoy.hunt2"

    def test_a_name_with_no_usable_characters_is_refused(self):
        """Would otherwise derive an empty username and fail inside Cognito with
        an opaque InvalidParameterException."""
        import pytest
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            P._derive_platform_username(self._free(), "!!! ???")
        assert exc.value.status_code == 422

    def test_the_derivation_is_bounded(self):
        """ADR-380 D5 -- a spin here is a bug or an attack, and either deserves
        a refusal rather than an unbounded loop."""
        import inspect
        assert "MAX_SUFFIX" in inspect.getsource(P._derive_platform_username)
