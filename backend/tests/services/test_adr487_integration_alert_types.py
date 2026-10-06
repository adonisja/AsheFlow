"""An integration outage must actually reach somebody (ADR-487 D4, ADR-335).

THE DEFECT, AND WHY NOTHING CAUGHT IT
=====================================

`alert_admins_integration_down` raises a Notification whose type comes from a
DEFAULT PARAMETER VALUE:

    def alert_admins_integration_down(
        db, company_id, ..., notif_type: str = DISCORD_INTEGRATION_FAILED,
    ):
        write_notification(db, ..., type=notif_type)

All four call sites pass two positional arguments and take the default, so the
literal `"discord_integration_failed"` appears nowhere that a grep for
`type="..."` or an AST walk over `type=` keyword constants would find it. The
82-row registry review therefore never saw these three types, and
`_resolve_raisable` refused all three.

The refusal was then swallowed:

    except Exception:
        logger.exception("integration alert: could not notify admins ...")
        return 0

and because `write_notification` raised at the TOP of the try block, the
`raise_platform_alert` call BELOW it never ran either. So an outage notified
neither the company's admins (who need to know crews are on in-app only) nor the
super admin (the only person who can rotate the credential) — and left one log
line behind.

THE TRANSFERABLE PART
=====================

A registry that refuses unknown types converts "unroutable notification" into
"exception at the call site", which is the right trade — but only where the
exception is VISIBLE. Behind a broad `except`, a refusing registry turns a
cosmetic gap into a silent total failure. The two features have to be designed
together: anything that refuses needs its callers audited for swallowing.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from tests.conftest import code_only

from app.services import integration_alerts as IA
from app.services.notification_spec import RETIRED, SPEC, Severity
from app.services.notify import _resolve_raisable

_ALERT_TYPES = (
    IA.DISCORD_INTEGRATION_FAILED,
    IA.EMAIL_DELIVERY_FAILED,
    IA.IDENTITY_REVOCATION_FAILED,
)


class TestTheAlertTypesAreDeclared:
    @pytest.mark.parametrize("ntype", _ALERT_TYPES)
    def test_the_registry_accepts_it(self, ntype):
        """Before this, all three raised UndeclaredNotificationType."""
        spec = _resolve_raisable(ntype)
        assert spec.label, f"{ntype} resolves but has no label"

    @pytest.mark.parametrize("ntype", _ALERT_TYPES)
    def test_it_is_actionable_not_informational(self, ntype):
        """Each message names something the admin must now do by hand — verify
        in the Cognito console, check SES, restart the bot."""
        assert _resolve_raisable(ntype).severity is Severity.ACTION

    def test_revocation_failure_is_the_most_severe_tone(self):
        """An offboarded employee who can still sign in (ADR-336 D2) is a
        security finding, not a degraded convenience."""
        from app.services.notification_spec import Tone
        assert _resolve_raisable(IA.IDENTITY_REVOCATION_FAILED).tone is Tone.BAD

    @pytest.mark.parametrize("ntype", _ALERT_TYPES)
    def test_it_does_not_route_over_the_channel_that_is_down(self, ntype):
        """Delivering "Discord is down" over Discord is the shape to avoid, and
        it generalises: an integration's own failure notice must not depend on
        that integration."""
        from app.services.notification_spec import Channel
        assert Channel.DISCORD not in _resolve_raisable(ntype).channels


class TestTheDefaultParameterIsStillTheGap:
    """The structural reason the review missed these. Kept as a test because the
    NEXT type added this way will be missed the same way."""

    def test_the_type_comes_from_a_default_not_a_literal(self):
        """If this ever becomes an explicit argument at every call site, the
        hazard is gone and this test can go. While it is a default, the
        completeness check below is what covers it."""
        sig = inspect.signature(IA.alert_admins_integration_down)
        assert sig.parameters["notif_type"].default == IA.DISCORD_INTEGRATION_FAILED

    def test_every_type_reaching_write_notification_is_declared(self):
        """Walks the CODE for what can reach `write_notification`, rather than
        walking the registry — the direction that matters (ADR-464's lesson): a
        registry-walking test passes forever while the registry goes stale.

        Scoped by USE, not by name. The first version matched every constant
        ending `_FAILED` and immediately flagged `BACKUP_FAILED` — which is
        correct to exclude: ADR-344 D5 routes it through
        `raise_platform_alert` ONLY, because a failed backup is platform
        infrastructure and a super admin has no Employee row to address
        (ADR-324 D2). Two vocabularies the ADRs deliberately keep apart, which
        a name-based heuristic cannot tell apart.

        So this derives the set from the function that actually raises
        notifications: whatever `notif_type` can be bound to.
        """
        known = set(SPEC) | set(RETIRED)

        # `inspect.signature` rather than reading fn.args by hand. The first
        # version zipped `fn.args.args` against `fn.args.defaults` and found
        # NOTHING, because `notif_type` is KEYWORD-ONLY and therefore lives in
        # `kwonlyargs`/`kw_defaults` — a separate list. Reimplementing Python's
        # parameter-binding rules in AST is a second source of truth for a
        # question the stdlib already answers; the guard below is what caught it.
        notification_types: set[str] = set()
        for name, obj in vars(IA).items():
            if not callable(obj) or not hasattr(obj, "__code__"):
                continue
            try:
                body = inspect.getsource(obj)
            except (OSError, TypeError):
                continue
            if "write_notification" not in body:
                continue
            for pname, param in inspect.signature(obj).parameters.items():
                if pname != "notif_type":
                    continue
                if isinstance(param.default, str):
                    notification_types.add(param.default)

        # Plus whatever the callers pass explicitly, across the whole app.
        root = pathlib.Path(__file__).resolve().parents[2] / "app"
        for mod in root.rglob("*.py"):
            msrc = mod.read_text()
            if "alert_admins_integration_down" not in msrc:
                continue
            for call in ast.walk(ast.parse(msrc)):
                if not isinstance(call, ast.Call):
                    continue
                nm = getattr(call.func, "attr", getattr(call.func, "id", ""))
                if nm != "alert_admins_integration_down":
                    continue
                for kw in call.keywords:
                    if kw.arg == "notif_type" and isinstance(kw.value, ast.Name):
                        val = getattr(IA, kw.value.id, None)
                        if isinstance(val, str):
                            notification_types.add(val)

        assert notification_types, (
            "the walk found no notification types at all — it has stopped "
            "testing anything, which is the failure mode of a source-walking test"
        )
        undeclared = sorted(t for t in notification_types if t not in known)
        assert not undeclared, (
            "a type that reaches write_notification is not in SPEC or RETIRED, "
            "so the registry will refuse it and the except-block in "
            f"alert_admins_integration_down will swallow the refusal: {undeclared}"
        )

    def test_a_platform_only_type_is_correctly_absent(self):
        """The counterpart: BACKUP_FAILED must NOT be in the registry.

        ADR-344 D5 routes it through raise_platform_alert alone, and ADR-324 D2
        gives the reason — a super admin has no Employee row, so a Notification
        cannot address them. Declaring it would invite someone to raise it as a
        notification that reaches a tenant's admins about infrastructure they
        cannot act on.
        """
        assert IA.BACKUP_FAILED not in SPEC, (
            "backup_failed is platform-only (ADR-344 D5); a registry entry "
            "would invite raising it at tenant admins who cannot fix a backup"
        )


class TestTheTwoAudiencesFailIndependently:
    """The coupling that made the defect total rather than partial.

    `raise_platform_alert` once sat BELOW the notification loop in the SAME
    `try`, so the registry's refusal on the first statement meant it was never
    reached — and the super admin, the only person who can rotate a revoked
    credential, heard nothing. ADR-324 D2 makes the audiences irreducible (a
    super admin has no Employee row), so a failure to reach one must not
    suppress the other.

    Fixed by splitting into two independent blocks with the platform alert
    FIRST. The ordering is load-bearing: it is the half that reaches the person
    who can fix the thing, so it is the half that must survive anything going
    wrong in the other.
    """

    def test_the_platform_alert_is_outside_the_try(self):
        """Inside it, any failure above it still skips it — which is the
        original defect wearing a different shape.

        Parsed, not string-compared. The previous version of this test asserted
        `src.index("write_notification") < src.index("raise_platform_alert")`
        and PASSED after the order was inverted, because `write_notification`
        appears earlier in the DOCSTRING than `raise_platform_alert` does in the
        code. A semantic inversion slipped through a green test — the tenth
        prose-not-code match in this body of work, and the first to hide a real
        behaviour change rather than merely fail noisily.
        """
        tree = ast.parse(inspect.getsource(IA.alert_admins_integration_down).lstrip())
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))

        def _calls(node):
            return {
                c.func.id if isinstance(c.func, ast.Name) else getattr(c.func, "attr", "")
                for c in ast.walk(node) if isinstance(c, ast.Call)
            }

        tries = [n for n in fn.body if isinstance(n, ast.Try)]
        assert tries, "the notification half must still be guarded"
        guarded = set().union(*(_calls(t) for t in tries))
        assert "write_notification" in guarded, (
            "the notification loop lost its guard — an alerting bug would now "
            "break the request that is already handling a failure"
        )
        assert "raise_platform_alert" not in guarded, (
            "the platform alert is inside a try whose earlier statements can "
            "skip it; that is the original ADR-487 defect in a new shape"
        )

    def test_the_platform_alert_comes_first_in_the_code(self):
        """By statement position in the AST, not by substring index."""
        tree = ast.parse(inspect.getsource(IA.alert_admins_integration_down).lstrip())
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))

        def _line_of(name):
            for n in ast.walk(fn):
                if isinstance(n, ast.Call):
                    nm = n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
                    if nm == name:
                        return n.lineno
            return None

        pa, wn = _line_of("raise_platform_alert"), _line_of("write_notification")
        assert pa is not None and wn is not None
        assert pa < wn, (
            "the platform alert must run BEFORE the notification loop: it is "
            "the half that reaches the only person who can fix the credential"
        )

    def test_the_notification_half_still_swallows_and_logs(self):
        """Not a complaint — the `except` is correct (ADR-335: an alerting bug
        must not become the thing that breaks the request). Recorded because it
        is why the defect was invisible, so a reader knows the log line is the
        only signal."""
        src = inspect.getsource(IA.alert_admins_integration_down)
        assert "except Exception:" in src
        assert "logger.exception" in src, (
            "the broad except must at least log with a traceback — it is the "
            "only trace an alerting failure leaves"
        )

    def test_the_log_line_says_the_platform_alert_survived(self):
        """The message is the operational difference the split bought: this now
        means "the admins were not told", not "nobody was told"."""
        src = inspect.getsource(IA.alert_admins_integration_down)
        block = src[src.index("except Exception:"):]
        assert "platform alert was still raised" in block, (
            "the failure log does not distinguish a partial failure from a "
            "total one, which is the whole point of splitting the blocks"
        )

    def test_the_platform_alert_is_not_double_guarded(self):
        """`raise_platform_alert` has its own try and is documented 'never
        raises'. Wrapping it again reads as though it could throw and invites
        someone to rely on that."""
        src = code_only(IA.raise_platform_alert)
        assert "except Exception:" in src, (
            "raise_platform_alert no longer guards itself, so the call site "
            "above it now DOES need a try — fix one or the other"
        )
