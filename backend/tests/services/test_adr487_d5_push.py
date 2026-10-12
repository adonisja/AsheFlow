"""Push delivery: the token, the envelope, and the quiet-hours hold (ADR-487 D5).

25 of the 86 declared notification types carry the PUSH channel and nothing
delivered any of them. These pin the properties that make the delivery path
correct, each tied to a failure the ADR names.
"""
from __future__ import annotations

import ast
import inspect
import json
from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.models.device_token import DevicePlatform, DeviceToken
from app.services import push_delivery
from app.services.notification_spec import SPEC, Channel, Severity


class TestTheTokenIsGloballyUnique:
    """A phone handed from one walker to another must MOVE, not duplicate.

    Without global uniqueness the old row keeps delivering the first person's
    notifications to the second — a cross-person leak that company scoping does
    not prevent, because both walkers are usually in the same company.
    """

    def test_the_unique_index_is_on_token_alone(self):
        idx = {i.name: ([c.name for c in i.columns], i.unique)
               for i in DeviceToken.__table__.indexes}
        assert "uq_device_tokens_token" in idx
        cols, unique = idx["uq_device_tokens_token"]
        assert unique is True
        assert cols == ["token"], (
            f"the unique index covers {cols} — scoped per-employee or per-company "
            f"it no longer collides when a device changes hands, so registration "
            f"inserts a second row and the old one keeps delivering"
        )

    def test_registration_moves_rather_than_inserting(self):
        """Parsed, not grepped: the docstring explains the move at length."""
        from app.routers import notifications as N

        tree = ast.parse(inspect.getsource(N.register_device).lstrip())
        # The move branch must assign employee_id onto the existing row.
        assigns = {
            t.attr for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            for t in node.targets
            if isinstance(t, ast.Attribute)
        }
        assert {"employee_id", "company_id"} <= assigns, (
            f"register_device assigns {sorted(assigns)} — it must reassign BOTH "
            f"employee_id and company_id on an existing token, or a transferred "
            f"device keeps delivering to its previous owner"
        )

    def test_a_move_clears_revoked_at(self):
        """Re-registering IS the signal that a device is live again."""
        from app.routers import notifications as N

        src = inspect.getsource(N.register_device)
        assert "revoked_at = None" in src, (
            "a re-registered device stays revoked, so a walker who signs out and "
            "back in silently receives nothing"
        )


class TestTheEmployeeFkCascades:
    """A departed employee's device must stop receiving."""

    def test_employee_id_cascades(self):
        fks = list(DeviceToken.__table__.c["employee_id"].foreign_keys)
        assert fks[0].ondelete == "CASCADE", (
            "a token with no owner is unroutable, and there is nothing here "
            "worth retaining — the opposite of ADR-494's acknowledgement, which "
            "is evidence"
        )

    def test_company_id_is_present_despite_the_employee_fk(self):
        """Audit Dimension 1. A token is a delivery address for tenant data."""
        assert "company_id" in DeviceToken.__table__.c
        assert DeviceToken.__table__.c["company_id"].nullable is False


class TestTheSendPathIsScoped:
    def test_live_devices_filters_on_company_and_employee_and_revoked(self):
        src = inspect.getsource(push_delivery.live_devices)
        for needle in ("company_id ==", "employee_id ==", "revoked_at.is_(None)"):
            assert needle in src, f"live_devices is missing {needle}"

    def test_the_partial_index_matches_the_send_query(self):
        """An index whose predicate does not match the query is not used."""
        idx = {i.name: i for i in DeviceToken.__table__.indexes}
        assert "ix_device_tokens_live" in idx
        cols = [c.name for c in idx["ix_device_tokens_live"].columns]
        assert cols == ["company_id", "employee_id"]
        assert idx["ix_device_tokens_live"].dialect_options["postgresql"]["where"] is not None


class TestTheSnsEnvelope:
    """SNS requires a JSON string whose values are THEMSELVES JSON strings.

    A double encoding that is easy to get wrong and that silently delivers
    nothing when it is — SNS accepts the publish and the device sees no alert.
    """

    @pytest.mark.parametrize("platform,key", [
        (DevicePlatform.IOS, "APNS"),
        (DevicePlatform.ANDROID, "GCM"),
    ])
    def test_the_inner_value_is_a_json_string(self, platform, key):
        raw = push_delivery._payload(platform, "Help Needed", "Route 12", {"x": "1"})
        outer = json.loads(raw)
        assert key in outer
        assert isinstance(outer[key], str), (
            f"{key} is a {type(outer[key]).__name__}, not a JSON string — SNS "
            f"accepts the publish and the device receives nothing"
        )
        json.loads(outer[key])          # must parse

    @pytest.mark.parametrize("platform", list(DevicePlatform))
    def test_there_is_always_a_default_fallback(self, platform):
        """SNS requires `default` when MessageStructure is json."""
        outer = json.loads(push_delivery._payload(platform, "t", "b", {}))
        assert "default" in outer

    def test_ios_uses_the_aps_envelope(self):
        inner = json.loads(json.loads(
            push_delivery._payload(DevicePlatform.IOS, "T", "B", {})
        )["APNS"])
        assert inner["aps"]["alert"] == {"title": "T", "body": "B"}


class TestDisabledIsNotBroken:
    """An empty ARN means "not set up yet", reported once, not per-send."""

    def test_push_enabled_is_false_with_no_arns(self, monkeypatch):
        monkeypatch.setattr(push_delivery.settings, "sns_apns_platform_arn", "")
        monkeypatch.setattr(push_delivery.settings, "sns_fcm_platform_arn", "")
        assert push_delivery.push_enabled() is False
        assert push_delivery.push_enabled(DevicePlatform.IOS) is False

    def test_one_platform_configured_enables_only_that_one(self, monkeypatch):
        monkeypatch.setattr(push_delivery.settings, "sns_apns_platform_arn", "arn:x")
        monkeypatch.setattr(push_delivery.settings, "sns_fcm_platform_arn", "")
        assert push_delivery.push_enabled(DevicePlatform.IOS) is True
        assert push_delivery.push_enabled(DevicePlatform.ANDROID) is False
        assert push_delivery.push_enabled() is True

    def test_create_endpoint_returns_none_rather_than_raising(self, monkeypatch):
        """Registration must succeed with push unconfigured, or a sign-in fails
        on an optional feature."""
        monkeypatch.setattr(push_delivery.settings, "sns_apns_platform_arn", "")
        device = SimpleNamespace(platform=DevicePlatform.IOS, token="t",
                                 employee_id="e", company_id="c", id="d")
        assert push_delivery.create_endpoint(device) is None

    def test_no_token_reaches_a_log_line(self):
        """A device token is a credential for delivering someone's notifications.

        Parsed: every logger call's arguments are checked for the token, rather
        than grepping a file whose docstring says the word "token" repeatedly.
        """
        tree = ast.parse(inspect.getsource(push_delivery))
        leaks = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "logger"):
                continue
            rendered = " ".join(ast.unparse(a) for a in node.args)
            if ".token" in rendered:
                leaks.append((node.lineno, rendered[:70]))
        assert leaks == [], f"a device token reaches a log line: {leaks}"


class TestQuietHours:
    """Severity's ONLY job in push: whether it may break the hold."""

    def test_only_urgent_breaks_quiet_hours(self):
        from app.services import push_quiet_hours

        assert push_quiet_hours._BREAKS_QUIET_HOURS == frozenset({Severity.URGENT}), (
            "the set of severities that may wake someone changed. URGENT alone "
            "is the point of the tier: if an injury alert can wait four hours it "
            "is not urgent and belongs in ACTION."
        )

    def test_it_uses_company_datetime_not_a_utc_relabel(self):
        """ADR-486: attaching UTC to a naive Time RELABELS it.

        07:00 New York becomes 07:00 UTC — four or five hours early depending on
        DST. That defect class was found in five places.
        """
        from app.services import push_quiet_hours

        src = inspect.getsource(push_quiet_hours)
        assert "company_datetime(" in src
        tree = ast.parse(src)
        bad = [
            n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "replace"
            and any(k.arg == "tzinfo" for k in n.keywords)
        ]
        assert bad == [], (
            f"a .replace(tzinfo=...) at line(s) {bad} — that relabels a naive "
            f"wall-clock time instead of converting it (ADR-486)"
        )

    def test_it_reads_companyconfig_not_company(self):
        """`shift_start` lives on CompanyConfig; `Company.shift_start` does not
        exist, and that mistake is an AttributeError at request time rather than
        at import (precedent ADR-446)."""
        from app.models.company import Company, CompanyConfig

        assert "shift_start" in CompanyConfig.__table__.c
        assert "shift_start" not in Company.__table__.c

    def test_a_null_anchor_sends_now_rather_than_holding(self):
        """A held push with no release time is a push that never arrives."""
        from app.services import push_quiet_hours

        src = inspect.getsource(push_quiet_hours.release_at)
        assert "if shift_start is None" in src
        tree = ast.parse(src.lstrip())
        # The NULL branch must return None (send now), never a datetime.
        for node in ast.walk(tree):
            if (isinstance(node, ast.If)
                    and "shift_start is None" in ast.unparse(node.test)):
                returns = [n for n in ast.walk(node) if isinstance(n, ast.Return)]
                assert returns and all(
                    isinstance(r.value, ast.Constant) and r.value.value is None
                    for r in returns
                ), "the no-anchor branch must return None (send now), not a hold"
                break
        else:
            pytest.fail("no `shift_start is None` branch found")


class TestTheHoldSurvivesABrokerRestart:
    """D5: a Celery `countdown=` of six hours lives in the broker and dies with
    it. A row survives."""

    def test_the_task_is_not_enqueued_with_a_countdown(self):
        from app.services import notify

        # PARSED, not grepped. The substring version failed on its first run:
        # the comment above the call EXPLAINS why there is no countdown, so
        # `"countdown" not in src` matched the prose. That is the eighteenth
        # prose-not-code false match recorded in this repo, and the better the
        # comment the more reliably it hides the thing it describes.
        tree = ast.parse(inspect.getsource(notify._enqueue).lstrip())
        push_calls = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "delay"
            and "send_push" in ast.unparse(n.func.value)
        ]
        assert push_calls, "_enqueue no longer calls send_push.delay"
        for call in push_calls:
            kwargs = {k.arg for k in call.keywords}
            assert "countdown" not in kwargs and "eta" not in kwargs, (
                f"send_push is enqueued with {sorted(kwargs)} — a countdown or "
                f"eta lives in the broker and a broker restart loses it. The "
                f"hold must be a ROW, checked at send time."
            )

    def test_a_held_push_stamps_release_at(self):
        from app.tasks import push_delivery_task

        src = inspect.getsource(push_delivery_task.send_push)
        assert "notif.release_at = release" in src, (
            "the hold is not stamped, so nothing can find the row later and the "
            "push simply never arrives"
        )

    def test_a_sent_push_clears_release_at(self):
        """Otherwise the sweep re-sends it every five minutes forever."""
        from app.tasks import push_delivery_task

        src = inspect.getsource(push_delivery_task.send_push)
        assert "notif.release_at = None" in src, (
            "release_at is never cleared, so the release sweep keeps finding a "
            "row whose hold has passed and pushes it again on every run"
        )

    def test_the_release_sweep_exists_and_is_scheduled(self):
        from app.celery_app import celery_app

        entries = [
            v for v in celery_app.conf.beat_schedule.values()
            if v["task"] == "app.tasks.notification_sweep.release_held_pushes"
        ]
        assert len(entries) == 1, (
            f"{len(entries)} beat entries for the release sweep. The resweep "
            f"deliberately EXCLUDES held rows, so with no release sweep a push "
            f"stamped at 02:00 is skipped forever and sent by nothing."
        )

    def test_the_resweep_still_excludes_held_rows(self):
        """The two sweeps must not both claim the same row."""
        from app.tasks import notification_sweep

        src = inspect.getsource(notification_sweep.resweep_undelivered)
        assert "release_at.is_(None)" in src, (
            "the resweep no longer excludes held pushes, so a held row is "
            "re-enqueued immediately and the quiet-hours hold is bypassed"
        )


class TestPushIsAdditive:
    """Every failure is swallowed: a broken push must never fail the
    notification it was announcing."""

    def test_send_to_device_returns_a_bool_rather_than_raising(self):
        sig = inspect.signature(push_delivery.send_to_device)
        assert sig.return_annotation in (bool, "bool")

    def test_the_task_swallows_everything_but_transient_aws_errors(self):
        from app.tasks import push_delivery_task

        tree = ast.parse(inspect.getsource(push_delivery_task.send_push).lstrip())
        handlers = [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)]
        assert handlers, "send_push has no exception handling at all"
        # A bare `except:` would swallow KeyboardInterrupt/SystemExit too.
        assert all(h.type is not None for h in handlers), (
            "send_push has a bare except, which swallows SystemExit"
        )

    def test_an_endpoint_disabled_revokes_the_device(self):
        """The only reliable signal that an app was deleted."""
        src = inspect.getsource(push_delivery.send_to_device)
        assert "EndpointDisabled" in src
        assert "revoked_at = datetime" in src


class TestTheRegistryStillDeclaresPush:
    def test_push_types_exist(self):
        pushing = [t for t, s in SPEC.items() if Channel.PUSH in s.channels]
        assert len(pushing) >= 20, (
            f"only {len(pushing)} types declare PUSH — this build exists because "
            f"25 did and none were delivered"
        )

    def test_notice_never_pushes(self):
        """ADR-488 D8 built the NOTICE tier ticker-only and never interruptive."""
        bad = [
            t for t, s in SPEC.items()
            if s.severity is Severity.NOTICE and Channel.PUSH in s.channels
        ]
        assert bad == [], f"NOTICE type(s) declare PUSH: {bad}"

class TestTheGlobalTokenLookupDoesNotLeak:
    """The token lookup in `register_device` is deliberately UNSCOPED.

    It has to be: the token is globally unique precisely so a transferred device
    collides and can be MOVED. Scoping it per-company would make a phone moving
    between employers insert a second row, and the old row would keep delivering
    the previous owner's notifications.

    That makes the endpoint the one place in this codebase where a query
    deliberately crosses a tenant boundary, so what it REVEALS and what it
    RECORDS both matter. Found while auditing my own code: the first version
    returned `action` ("registered" / "moved"), which told any caller whether an
    opaque token already existed somewhere in the system — including in another
    tenant. Free existence oracle, and the client had no use for it.
    """

    def test_the_response_does_not_report_whether_the_token_existed(self):
        """Parsed from the return dict, not grepped: the comment above it
        explains the omission at length and names the field."""
        from app.routers import notifications as N

        tree = ast.parse(inspect.getsource(N.register_device).lstrip())
        returns = [n for n in ast.walk(tree) if isinstance(n, ast.Return)]
        assert returns, "register_device returns nothing"
        keys: set[str] = set()
        for r in returns:
            if isinstance(r.value, ast.Dict):
                keys |= {
                    k.value for k in r.value.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)
                }
        assert "action" not in keys, (
            f"register_device returns {sorted(keys)}. `action` distinguishes "
            f"registered/refreshed/moved, so returning it tells the caller the "
            f"token already existed SOMEWHERE — including in another tenant."
        )
        assert "push_active" in keys, "the client needs to know if push is live"

    def test_a_cross_tenant_move_is_logged(self):
        """A device crossing a company boundary is either a phone changing
        employers or a replayed token. Both deserve to be visible."""
        from app.routers import notifications as N

        src = inspect.getsource(N.register_device)
        assert "moved_from_company" in src
        assert "moved across companies" in src, (
            "a cross-tenant device move is silent — the only signal that "
            "somebody replayed a token they should not hold"
        )

    def test_the_module_has_a_logger(self):
        """The warning above was a NameError when first written: this module had
        no `logger`, and the only reference was the new call — so the one line
        that exists to surface a suspicious move would have raised instead.
        """
        from app.routers import notifications as N

        assert hasattr(N, "logger"), (
            "notifications.py has no module logger, so every logger.* call in "
            "it is a NameError at the moment it fires"
        )

    def test_the_audit_still_records_the_action(self):
        """Removed from the RESPONSE, kept in the audit — where only the
        tenant's own admins can read it."""
        from app.routers import notifications as N

        src = inspect.getsource(N.register_device)
        assert 'action_type=f"device.{action}"' in src, (
            "the audit no longer records which action occurred, so a move is "
            "now invisible everywhere rather than just to the caller"
        )
