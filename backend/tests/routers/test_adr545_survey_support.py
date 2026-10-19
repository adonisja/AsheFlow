"""Platform support can see and unstick surveyors without writing survey records (ADR-545).

Owner, 2026-10-19: support may SEE the survey pages and help surveyors; it never
writes survey records (ADR-504). Real rows on SQLite (the ADR-513 fixtures);
Cognito and SES stubbed at their real names.
"""
import inspect
import uuid
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.audit_log import AuditLog
from app.models.survey_register import CLAIM_RELEASE_REASONS, SurveyBlockClaim, SurveyContributor
from app.routers import survey_register as R
# The ADR-513 fixtures (tables + stubbed city) and helpers, reused as-is.
from tests.routers.test_adr513_survey_areas import (  # noqa: F401
    ATTEST, OWNER, OWNER_W, SUPPORT, _area, _block, _claim_and_walk, _record, _tables, city,
)


def _contributor(db, sub="surveyor-sub-01", username="a.contributor", email="a@example.org", revoked=False):
    from datetime import datetime, timezone
    c = SurveyContributor(id=uuid.uuid4(), cognito_sub=sub, display_name="A Contributor",
                          cognito_username=username, email=email,
                          agreement_version="v1", agreement_signed_on=date(2026, 10, 13),
                          revoked_at=datetime.now(timezone.utc) if revoked else None)
    db.add(c); db.commit()
    return c


def _cognito(status="CONFIRMED", enabled=True, groups=("surveyor",), missing=False):
    c = MagicMock()
    if missing:
        c.admin_get_user.side_effect = ClientError({"Error": {"Code": "UserNotFoundException"}}, "AdminGetUser")
    else:
        c.admin_get_user.return_value = {"UserStatus": status, "Enabled": enabled}
    c.admin_list_groups_for_user.return_value = {"Groups": [{"GroupName": g} for g in groups]}
    return c


def _audit(db, action):
    return db.query(AuditLog).filter(AuditLog.action_type == action).all()


# ── D2: Survey activity ─────────────────────────────────────────────────────

class TestActivity:
    def test_it_names_holders_and_counts_without_contents(self, db):
        c = _contributor(db)
        w = R.Writer(sub=c.cognito_sub, owner=False)
        area = _area(db)
        claim, walk = _claim_and_walk(db, w, area)
        _record(db, w, walk, 0, note="Lobby on the left")
        with patch.object(R, "_cognito", return_value=_cognito()):
            out = R.survey_activity(staff=SUPPORT, db=db)
        [h] = out.contributors
        assert (h.account_status, h.in_surveyor_group) == ("active", True)
        [cl] = out.claims
        assert cl.holder == "A Contributor" and cl.walk_open is True
        [ow] = out.open_walks
        assert (ow.holder, ow.doors_done, ow.doors_total) == ("A Contributor", 1, 3)
        assert "Lobby" not in out.model_dump_json()          # no observation contents

    def test_the_owner_is_named_as_owner(self, db):
        area = _area(db)
        _claim_and_walk(db, OWNER_W, area)
        with patch.object(R, "_cognito", return_value=_cognito()):
            out = R.survey_activity(staff=SUPPORT, db=db)
        assert out.claims[0].holder == "Owner"

    @pytest.mark.parametrize("kw,expect", [
        (dict(status="FORCE_CHANGE_PASSWORD"), ("never_signed_in", True)),
        (dict(enabled=False), ("disabled", True)),
        (dict(groups=()), ("active", False)),
        (dict(missing=True), ("missing", False)),
    ])
    def test_stuck_states_are_visible(self, db, kw, expect):
        _contributor(db)
        with patch.object(R, "_cognito", return_value=_cognito(**kw)):
            [h] = R.survey_activity(staff=SUPPORT, db=db).contributors
        assert (h.account_status, h.in_surveyor_group) == expect


# ── D3: account actions ─────────────────────────────────────────────────────

class TestResend:
    def test_only_while_never_signed_in(self, db):
        c = _contributor(db)
        cog = _cognito(status="CONFIRMED")
        with patch.object(R, "_cognito", return_value=cog):
            with pytest.raises(HTTPException) as exc:
                R.resend_contributor_signin(c.id, staff=SUPPORT, db=db)
        assert exc.value.status_code == 409 and "Forgot password" in exc.value.detail
        cog.admin_set_user_password.assert_not_called()

    def test_a_fresh_temporary_password_is_emailed(self, db):
        c = _contributor(db)
        cog = _cognito(status="FORCE_CHANGE_PASSWORD")
        with patch.object(R, "_cognito", return_value=cog), patch.object(R, "send_credentials_email") as send:
            out = R.resend_contributor_signin(c.id, staff=SUPPORT, db=db)
        kw = cog.admin_set_user_password.call_args.kwargs
        assert kw["Permanent"] is False and kw["Username"] == "a.contributor"
        assert send.call_args.kwargs["temp_password"] == kw["Password"]
        assert out.email_delivered and out.temp_password is None
        [a] = _audit(db, "survey.contributor.resend")
        assert a.after_snapshot["actor_kind"] == "platform_support"


class TestRestoreAccess:
    def test_adds_the_missing_group(self, db):
        c = _contributor(db)
        cog = _cognito(groups=())
        with patch.object(R, "_cognito", return_value=cog):
            R.restore_contributor_access(c.id, staff=SUPPORT, db=db)
        assert cog.admin_add_user_to_group.call_args.kwargs["GroupName"] == "surveyor"
        assert len(_audit(db, "survey.contributor.restore_access")) == 1

    def test_refused_for_a_revoked_contributor(self, db):
        c = _contributor(db, revoked=True)
        with patch.object(R, "_cognito", return_value=_cognito(groups=())):
            with pytest.raises(HTTPException) as exc:
                R.restore_contributor_access(c.id, staff=SUPPORT, db=db)
        assert exc.value.status_code == 409


class TestReadmit:
    def _body(self, **kw):
        return R.ReadmitIn(**{"agreement_version": "v2", "agreement_signed_on": date(2026, 10, 18),
                              "confirm_agreement_signed": True, **kw})

    def test_requires_the_agreement_again(self):
        with pytest.raises(ValidationError):
            self._body(confirm_agreement_signed=False)

    def test_clears_revocation_and_restores_access(self, db):
        c = _contributor(db, revoked=True)
        cog = _cognito(groups=())
        with patch.object(R, "_cognito", return_value=cog):
            out = R.readmit_contributor(c.id, self._body(), staff=SUPPORT, db=db)
        assert out.revoked_at is None and out.agreement_version == "v2"
        assert cog.admin_add_user_to_group.called
        assert len(_audit(db, "survey.contributor.readmit")) == 1

    def test_only_a_revoked_contributor(self, db):
        c = _contributor(db)
        with pytest.raises(HTTPException) as exc:
            R.readmit_contributor(c.id, self._body(), staff=SUPPORT, db=db)
        assert exc.value.status_code == 409

    def test_the_exclusion_is_checked_again(self, db):
        c = _contributor(db, revoked=True)
        with patch.object(R, "_assert_not_excluded", side_effect=HTTPException(403, "excluded")):
            with pytest.raises(HTTPException) as exc:
                R.readmit_contributor(c.id, self._body(), staff=SUPPORT, db=db)
        assert exc.value.status_code == 403
        db.refresh(c)
        assert c.revoked_at is not None


# ── D4: releasing a stuck claim ─────────────────────────────────────────────

class TestStaffRelease:
    def test_frees_the_block_keeps_the_walk_and_tells_the_holder(self, db):
        c = _contributor(db)
        w = R.Writer(sub=c.cognito_sub, owner=False)
        area = _area(db)
        claim, walk = _claim_and_walk(db, w, area)
        _record(db, w, walk, 0)
        with patch.object(R, "send_claim_released_notice") as notice:
            R.staff_release_claim(claim.id, R.StaffReleaseIn(reason="Idle for two days, freeing the block"),
                                  staff=SUPPORT, db=db)
        row = db.get(SurveyBlockClaim, claim.id)
        assert row.release_reason == "staff_released"
        assert notice.call_args.kwargs["to_email"] == "a@example.org"
        [a] = _audit(db, "survey.claim.staff_release")
        assert a.after_snapshot["reason"].startswith("Idle for two days")
        # The walk and its observation stand: support never writes the record.
        assert len(R.my_walks(writer=w, db=db, limit=20)) == 1

    def test_needs_a_real_reason(self):
        with pytest.raises(ValidationError):
            R.StaffReleaseIn(reason="idle")

    def test_a_reason_cannot_carry_a_code(self, db):
        c = _contributor(db)
        area = _area(db)
        claim, _ = _claim_and_walk(db, R.Writer(sub=c.cognito_sub, owner=False), area)
        with pytest.raises(HTTPException) as exc:
            R.staff_release_claim(claim.id, R.StaffReleaseIn(reason="The door code is 4512, freeing"),
                                  staff=SUPPORT, db=db)
        assert exc.value.status_code == 422

    def test_an_ended_claim_is_refused(self, db):
        c = _contributor(db)
        w = R.Writer(sub=c.cognito_sub, owner=False)
        area = _area(db)
        claim, _ = _claim_and_walk(db, w, area)
        R.release_claim(claim.id, writer=w, db=db)
        with pytest.raises(HTTPException) as exc:
            R.staff_release_claim(claim.id, R.StaffReleaseIn(reason="Idle for two days, freeing"),
                                  staff=SUPPORT, db=db)
        assert exc.value.status_code == 409

    def test_the_reason_is_allowed_by_the_constraint(self):
        assert "staff_released" in CLAIM_RELEASE_REASONS


def test_every_new_endpoint_is_platform_staff_and_support_still_cannot_write():
    for fn in (R.survey_activity, R.resend_contributor_signin, R.restore_contributor_access,
               R.readmit_contributor, R.staff_release_claim):
        params = inspect.signature(fn).parameters
        assert params["staff"].default.dependency is R.get_platform_staff, fn.__name__
    with pytest.raises(HTTPException) as exc:
        R.get_writer(current_user={**SUPPORT, "username": "support"}, db=MagicMock())
    assert exc.value.status_code == 403


# ── D1: the web routes and nav (no frontend test runner exists, so the source
#    is read; a wrong role list here silently exposes the walker pages) ──────

import pathlib
import re

_WEB = pathlib.Path(__file__).resolve().parents[3] / "frontend/src"


def _route_roles(path: str) -> set[str]:
    app = (_WEB / "App.tsx").read_text()
    m = re.search(r'<Route path="' + re.escape(path) + r'" element=\{<ProtectedRoute allowedRoles=\{\[([^\]]*)\]', app)
    assert m, f"no gated route for {path}"
    return set(re.findall(r"'([a-z_]+)'", m.group(1)))


@pytest.mark.parametrize("path", ["/survey", "/survey/walk/:walkId", "/survey/areas/:areaId"])
def test_walker_pages_are_writers_only(path):
    """Support SEES survey work through Survey activity, never the writer pages."""
    assert _route_roles(path) == {"super_admin", "surveyor"}


@pytest.mark.parametrize("path", ["/superadmin/surveyors", "/superadmin/survey-activity"])
def test_support_pages_are_platform_staff_only(path):
    assert _route_roles(path) == {"super_admin", "platform_support"}


def test_the_nav_shows_each_group_only_its_entries():
    nav = (_WEB / "components/layout/SuperAdminLayout.tsx").read_text()
    def roles(to):
        m = re.search(r"to: '" + re.escape(to) + r"'[^}]*roles: \[([^\]]*)\]", nav)
        assert m, to
        return set(re.findall(r"'([a-z_]+)'", m.group(1)))
    assert roles("/survey") == {"super_admin", "surveyor"}
    assert roles("/superadmin/survey-activity") == {"super_admin", "platform_support"}


def test_the_stand_alone_survey_bar_is_gone():
    """ADR-543 D1 superseded: one platform layout, not a fourth shell."""
    assert not (_WEB / "components/layout/SurveyLayout.tsx").exists()
