"""Every notification type, as the owner will see it (ADR-507).

Messages are built where a notification is raised, not stored in the registry,
so there is no single place that says what a type actually reads like. This
module recovers it from the source:

* **Templates** (64 of 86 types, measured 2026-10-13): every
  `write_notification` / `fan_out` / alert call with a literal `type=` is found
  by AST, and its `message=` is rendered. Literals pass through; f-string
  interpolations become marked placeholders (`‹caller.name›`); a `message=`
  that is a variable is followed back to its assignment in the same function.
  Each template carries `file:line`, because the page is platform-only and the
  owner will edit the copy there.

* **Samples** (the rest): types raised through an INDIRECT site
  (`type=notif_type`, `type=f"rts_{...}"`) cannot be paired with a message by
  reading one call. Their text below was copied from the code that builds it.
  Types raised by nothing at all are marked `unraised`: declared, configured,
  and invisible to every user. The gallery shows them so that is a decision,
  not an accident.

A test walks SPEC and fails if any type has neither, so a new type cannot be
added without the gallery being able to show it.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

from app.services.notification_spec import SPEC

#: The calls that raise a notification and take `type=` + `message=`.
_RAISERS = {"write_notification", "fan_out", "alert_admins_integration_down", "notify_company_admins"}

#: Where the source lives: the `app/` package this module is part of.
_APP_ROOT = Path(__file__).resolve().parents[1]

#: How a sample marks itself everywhere it can appear, including an
#: acknowledgement snapshot, which ADR-505 keeps for three years.
SAMPLE_PREFIX = "Sample · "

#: Types whose message cannot be read from one call site. `indirect`: raised,
#: but the type is computed. `unraised`: nothing in app/ raises it. Text copied
#: from the code that builds each message (sites in the comments).
SAMPLES: dict[str, tuple[str, str]] = {
    # routers/anchor_points.py: _notify(..., notif_type, message)
    "anchor_point_arrived": ("indirect", "✅ ‹truck_name› — ‹caller.name› arrived at: ‹ap.location›"),
    "anchor_point_departed": ("indirect", "🚚 ‹truck_name› — ‹caller.name› left ‹ap.location› at ‹departed_str›"),
    "anchor_point_running_late": ("indirect", "⏰ ‹truck_name› — ‹driver_name› is running late (ETA was ‹ap.eta›, ‹minutes_late› min overdue)"),
    "anchor_point_submitted": ("indirect", "📍 ‹truck_name› posted its anchor point: ‹ap.location›"),
    # routers/incidents.py: notif_type = f"incident_{severity}"
    "incident_info": ("indirect", "INFO — ‹category_label› incident reported by ‹reporter.name› on ‹incident.date›. ‹incident.description›"),
    "incident_warning": ("indirect", "WARNING — ‹category_label› incident reported by ‹reporter.name› on ‹incident.date›. ‹incident.description›"),
    "incident_critical": ("indirect", "CRITICAL — ‹category_label› incident reported by ‹reporter.name› on ‹incident.date›. ‹incident.description›"),
    # routers/shift_ops.py: type=f"rts_{payload.status}"
    "rts_approved": ("indirect", "Your RTS report for ‹target_date› has been approved. You are cleared to return to the station."),
    "rts_rejected": ("indirect", "Your RTS report for ‹target_date› was not approved. Dispatch notes: ‹payload.dispatch_notes› Contact dispatch for further instructions."),
    # services/graduate_trainees.py: outcome_type (management copy)
    "trainee_graduated": ("indirect", "‹trainee.name› passed the graduation quiz and was automatically promoted from Trainee to Walker on ‹target_date›."),
    # services/integration_alerts.py: notif_type + module-level messages
    "discord_integration_failed": ("indirect", "Discord messages are not being delivered — the bot could not be reached."),
    "email_delivery_failed": ("indirect", "Outbound email is failing (AWS SES). Registration credentials, invites and password resets are not reaching recipients until it is restored."),
    "identity_revocation_failed": ("indirect", "Cognito access revocation failed. One or more offboarded employees may still be able to sign in — verify in the Cognito console and disable them manually."),
    # services/record_trainer_mark.py: _notify_management(..., notification_type=...)
    "exemplary_trainer": ("indirect", "Exemplary trainer: ‹trainer_name› cleared inherited training debt and completed Phase ‹record.current_day_number› for ‹trainee_name› in a single session."),
    "underperforming_trainer": ("indirect", "Underperforming trainer alert: ‹trainer_name› has failed to close training phases for ‹distinct_trainees› different trainees. Review their training records for patterns."),
    # routers/dispatch.py: notif_type = "dispatch_assignment_info"
    "dispatch_assignment_info": ("indirect", "You have been moved to **‹truck_name›** for ‹assignment_in.date›. Your attendance is confirmed — check your new truck channel on Discord."),
    # tasks/enrich_manifest.py: _notify_dispatch(company_id, message, db)
    "manifest_enrichment": ("indirect", "Manifest for ‹sort_date› updated: ‹n› packages enriched."),
    # tasks/notice_sweep.py: type=NOTICE_TYPE, message=body (tenant-authored)
    "tenant_notice": ("indirect", "‹notice body written by the company›"),
    # Declared in the registry, raised by nothing in app/ (checked 2026-10-13,
    # including the proprietary routers). Shown so the owner decides.
    "route_ready": ("unraised", "Your route for ‹date› is ready."),
    "quiz_unsubmitted_reminder": ("unraised", "Your graduation quiz is due. Submit it to finish training."),
    "trainee_bumped": ("unraised", "‹trainee.name› was moved off ‹truck_name› for ‹date›."),
    "trainee_reset": ("unraised", "‹trainee.name›'s training was reset to Phase 1."),
    "training_record_due": ("unraised", "A training record for ‹trainee.name› is due today."),
}


@dataclass(frozen=True)
class Template:
    location: str
    text: str


def _render(node, src: str, scope, depth: int = 0) -> str | None:
    """One `message=` expression as display text, or None if it cannot be read."""
    if node is None or depth > 3:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            v.value if isinstance(v, ast.Constant)
            else "‹" + (ast.get_source_segment(src, v.value) or "…") + "›"
            for v in node.values
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        a = _render(node.left, src, scope, depth + 1)
        b = _render(node.right, src, scope, depth + 1)
        return (a or "‹…›") + (b or "‹…›") if (a or b) else None
    if isinstance(node, ast.IfExp):
        return _render(node.body, src, scope, depth + 1) or _render(node.orelse, src, scope, depth + 1)
    if isinstance(node, ast.Name) and scope is not None:
        # A variable: follow it to its assignment(s) in the same function.
        assigned = [
            a.value for a in ast.walk(scope) if isinstance(a, ast.Assign)
            for t in a.targets if isinstance(t, ast.Name) and t.id == node.id
        ]
        for value in reversed(assigned):
            text = _render(value, src, scope, depth + 1)
            if text:
                return text
    return None


@lru_cache(maxsize=1)
def extract_templates() -> dict[str, tuple[Template, ...]]:
    """type -> every renderable message template found at a literal raise site.

    Cached for the process: the source does not change while it runs, and the
    walk reads every module in app/ (about a second).
    """
    found: dict[str, list[Template]] = {}
    for path in sorted(_APP_ROOT.rglob("*.py")):
        src = path.read_text(errors="ignore")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        rel = path.relative_to(_APP_ROOT.parent).as_posix()
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for call in ast.walk(fn):
                if not isinstance(call, ast.Call):
                    continue
                name = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
                if name not in _RAISERS:
                    continue
                kw = {k.arg: k.value for k in call.keywords}
                t = kw.get("type")
                if not (isinstance(t, ast.Constant) and isinstance(t.value, str)):
                    continue
                text = _render(kw.get("message"), src, fn)
                if text:
                    tpl = Template(f"{rel}:{call.lineno}", text)
                    if tpl not in found.setdefault(t.value, []):
                        found[t.value].append(tpl)
    return {t: tuple(v) for t, v in found.items()}


_PLACEHOLDER = re.compile(r"‹([^›]*)›")


def _fill(expr: str) -> str:
    """A readable stand-in for one placeholder, chosen by what it names."""
    tail = re.split(r"[.\[\(]", expr.strip())[-1] if expr.strip() else ""
    low = expr.lower()
    # Specific before generic: `truck_name` is a truck, not a person. The first
    # version checked "name" first and previewed "Alex Rivera — Alex Rivera
    # arrived at…" for AP Arrival (caught in the browser, 2026-10-13).
    if "truck" in low:
        return "Truck 12"
    if "name" in low:
        return "Alex Rivera"
    if "date" in low or low.endswith("_day"):
        return date.today().strftime("%a, %b %d")
    if "location" in low:
        return "W 32 St & 9 Ave"
    if "minutes" in low or low.startswith("n") and len(low) <= 3:
        return "15"
    return f"[{tail or 'value'}]"


def copy_for(notification_type: str) -> tuple[str, str]:
    """(source, raw text with placeholders) for one type. source is
    'template' | 'indirect' | 'unraised'."""
    templates = extract_templates().get(notification_type)
    if templates:
        return "template", templates[0].text
    kind, text = SAMPLES[notification_type]
    return kind, text


def sample_message(notification_type: str) -> str:
    """The message a SEND uses: the type's own copy, placeholders filled, marked."""
    _, raw = copy_for(notification_type)
    return SAMPLE_PREFIX + _PLACEHOLDER.sub(lambda m: _fill(m.group(1)), raw)


def catalog() -> list[dict]:
    """Every SPEC type, with its registry facts and its copy, for the gallery."""
    from app.schemas.notification import _resolve_for_read   # the wire shape clients render

    templates = extract_templates()
    out = []
    for t in sorted(SPEC):
        fields = _resolve_for_read(t)
        source, raw = copy_for(t)
        out.append({
            "type": t,
            **fields,
            "copy_source": source,
            "templates": [{"location": x.location, "text": x.text} for x in templates.get(t, ())],
            "sample_text": raw,
            "preview_message": _PLACEHOLDER.sub(lambda m: _fill(m.group(1)), raw),
        })
    return out
