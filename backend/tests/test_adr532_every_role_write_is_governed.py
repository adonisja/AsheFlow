"""Every place that can set a role goes through the grant rule, or says why not (ADR-532).

The owner: "Managers shouldnt be able to make someone an admin from anywhere."
That rule was implemented three times and missed three times -- single create
got it (2026-05-08), bulk import never did (2026-05-01, half-fixed 08-23),
edit checked the target's current role but not the new one, and onboarding
switched the manager check off (08-23). Each path had its own copy.

So this test does not keep a list of paths and check them. It WALKS the code
for anything that writes a role -- `x.role = ...`, `Employee(role=...)`,
`Employee(**...)`, `admin_add_user_to_group(...)` -- and fails unless that
function calls the shared rule or is exempted below WITH A REASON. A new
endpoint that grants a role fails CI until someone decides which it is.
(Lesson: completeness tests walk the world, not the list -- ADR-464.)
"""
import ast
import pathlib

APP = pathlib.Path(__file__).resolve().parents[1] / "app"

RULE_CALLS = {"_grant_refusal", "_edit_grant_refusal"}

# function -> why it may write a role without the grant rule. Keep reasons
# specific: "safe" is not a reason.
EXEMPT = {
    "companies.bootstrap_company_admin":
        "super-admin only: provisions a new tenant's first owner (platform, not a tenant caller)",
    "dispatch.swap_assignment":
        "AssignmentMember.role is a truck-slot role (driver/walker on a truck), not an employee's role",
    "employees._apply_role_transition":
        "ROLE_TRANSITIONS allows field moves only (walker/trainer/captain, driver_trainee->driver); never a protected role",
    "employees.reactivate_employee":
        "re-adds the Cognito group for the role the employee ALREADY has; protected roles refused by _assert_not_protected",
    "registration.complete_registration":
        "applies the role set at invite time, which create/bulk already governed; the registrant chooses nothing",
    "platform_alerts.activate_platform_staff":
        "super-admin only; platform staff groups, not tenant roles",
    "survey_register.invite_contributor":
        "platform staff only; fixed 'surveyor' group",
    "graduate_trainees.graduate_eligible_trainees":
        "system job: trainee -> walker on passing the graduation quiz (ADR-264); no caller",
    "adp_sync.sync_adp_employees":
        "system job: creates ADP-roster employees as walker only; no caller",
}


def _writes_role(fn: ast.AST) -> list[str]:
    why = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Attribute) and t.attr == "role":
                    why.append(".role =")
        elif isinstance(n, ast.Call):
            name = getattr(n.func, "attr", getattr(n.func, "id", ""))
            if name == "admin_add_user_to_group":
                why.append("admin_add_user_to_group")
            elif name == "Employee" and any(k.arg in ("role", None) for k in n.keywords):
                why.append("Employee(role=/**)")
    return why


def _calls(fn: ast.AST) -> set[str]:
    return {getattr(n.func, "attr", getattr(n.func, "id", ""))
            for n in ast.walk(fn) if isinstance(n, ast.Call)}


def _role_writers():
    out = {}
    for f in sorted(APP.rglob("*.py")):
        tree = ast.parse(f.read_text())
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                why = _writes_role(fn)
                if why:
                    out[f"{f.stem}.{fn.name}"] = (fn, why, f)
    return out


def test_every_role_write_is_governed_or_exempt_with_a_reason():
    ungoverned = [
        f"{key} ({', '.join(sorted(set(why)))}) in {f.relative_to(APP.parent)}:{fn.lineno}"
        for key, (fn, why, f) in _role_writers().items()
        if key not in EXEMPT and not (_calls(fn) & RULE_CALLS)
    ]
    assert not ungoverned, (
        "These functions can set a role without the ADR-532 grant rule. Call "
        "_grant_refusal/_edit_grant_refusal, or add them to EXEMPT with the "
        "specific reason a manager cannot use them to grant a role:\n  "
        + "\n  ".join(ungoverned))


def test_the_three_tenant_paths_are_governed_not_exempt():
    """The paths that were missed must stay on the rule, never drift to EXEMPT."""
    writers = _role_writers()
    for key in ("employees.create_employee", "employees.bulk_import_employees",
                "employees.update_employee"):
        assert key in writers, f"{key} no longer detected as a role writer -- detector drifted"
        assert key not in EXEMPT
        assert _calls(writers[key][0]) & RULE_CALLS, f"{key} no longer calls the grant rule"


def test_no_stale_exemptions():
    """An exemption for a function that no longer writes a role hides nothing
    today and silently covers whatever takes its name tomorrow."""
    stale = sorted(set(EXEMPT) - set(_role_writers()))
    assert not stale, f"remove stale EXEMPT entries: {stale}"


def test_every_exemption_has_a_real_reason():
    for key, why in EXEMPT.items():
        assert len(why) > 30 and why.lower() not in ("safe", "ok", "n/a"), key
