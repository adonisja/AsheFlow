"""Every privileged or destructive write endpoint leaves an audit row (ADR-274 D13).

RECOGNITION CUE
---------------
A new write endpoint ships, review passes, and nothing ever notices that it
changed persisted state without recording who did it. That is how 92 unaudited
write endpoints accumulated across 28 routers — no single omission was visible.

WHAT THIS GUARDS
----------------
ADR-132 established the standard (DP-1/DP-3/DP-5: deletes of personal data need
`write_audit`), but nothing enforced it, so the standard decayed the moment
attention moved on. ADR-274 D13 audited the privileged and destructive tier —
company lifecycle and config, account provisioning, every hard DELETE, and the
dispatch writes named in the parity trace.

This test fails when a NEW write endpoint has no audit path, so the decision is
made deliberately once rather than forgotten silently.

WHY AN ALLOWLIST RATHER THAN "AUDIT EVERYTHING"
-----------------------------------------------
Auditing high-frequency operational writes (mark-notification-read, anchor-point
arrive/depart, per-shift check-in) would bury the events that matter: an audit
log dominated by routine traffic is one nobody reads. The entries below are a
recorded judgement, not a backlog — though several are genuine follow-ups, and
those are marked.

DETECTION FOLLOWS HELPERS, ONE HOP
----------------------------------
`promote_employee` looked unaudited to a naive scan, but delegates to
`_apply_role_transition`, which audits. A scan that only reads the endpoint body
reports false positives and erodes trust in its own output — so this walks local
helper calls transitively before concluding anything.
"""
import ast
from pathlib import Path

import pytest


ROUTERS = Path(__file__).resolve().parents[2] / "app" / "routers"

_AUDIT_CALLS = {"write_audit", "AuditLog"}
_WRITE_VERBS = {"post", "patch", "put", "delete"}


# Endpoints that deliberately do NOT write an audit row, with the reason.
# Adding a line here is a decision: it says "this write is routine operational
# traffic and auditing it would dilute the log", NOT "I could not be bothered".
_NO_AUDIT = {
    "anchor_points.py::arrive_anchor_point",
    "anchor_points.py::confirm_anchor_point",
    "anchor_points.py::depart_anchor_point",
    "assignment_change_requests.py::submit_change_request",
    "assignment_members.py::create_assignment_member",
    # ADR-277 D4: a preview. It parses an upload and reports what WOULD
    # import — no INSERT, no UPDATE, nothing persisted. It only trips the
    # heuristic because it is a POST (it has to be: the file is the body).
    # The write it precedes, confirm_bulk_profiles, IS audited.
    "building_profiles.py::preview_bulk_profiles",
    # ADR-290 D3: the same shape. It parses a BTR sheet and reports what was
    # READ — no INSERT, no UPDATE, nothing persisted. POST only because the
    # uploaded file is the body. Giving it no write path is precisely what
    # forces an OCR read through a human before it can reach the database;
    # test_preview_endpoint_has_no_write_path asserts that structurally.
    # The write it precedes, confirm_btr_sheet, IS audited.
    "btr_sheets.py::preview_btr_sheet",
    "building_profiles.py::lock_building_profile",
    "building_profiles.py::set_operational_note",
    "building_profiles.py::submit_building_profile",
    "building_profiles.py::verify_building_profile",
    "continuation_requests.py::accept_continuation_request",
    "continuation_requests.py::reject_continuation_request",
    "continuation_requests.py::set_request_priority",
    "continuation_requests.py::submit_continuation_request",
    "driver_surveys.py::activate_survey",
    "driver_surveys.py::submit_response",
    "employee_off_days.py::create_employee_off_day",
    "employees.py::confirm_email_change",
    "employees.py::request_discord_link",
    "employees.py::request_email_change",
    "feedback.py::create_feedback",
    "feedback.py::update_feedback_status",
    "field_ops.py::acknowledge_manifest",
    "field_ops.py::check_in",
    "field_ops.py::create_dock_assignment",
    "field_ops.py::record_departure",
    "field_ops.py::record_return",
    "field_ops.py::record_station_arrival",
    "field_ops.py::submit_inspection",
    "field_ops.py::submit_rating",
    "field_ops.py::update_dock_assignment",
    "gear_requests.py::approve_item",
    "gear_requests.py::deny_item",
    "gear_requests.py::fulfill_item",
    "gear_requests.py::submit_gear_order",
    "graduation_quiz.py::issue_quiz",
    "graduation_quiz.py::review_quiz",
    "graduation_quiz.py::submit_quiz",
    "notifications.py::mark_all_read",
    "notifications.py::mark_read",
    "package_intake.py::read_label",
    "schedule_change_requests.py::submit_schedule_change_request",
    "scorecards.py::parse_scorecard",
    "shift_ops.py::submit_crew_compliance",
    "shift_ops.py::submit_driver_check_in",
    "shift_ops.py::upsert_crew_compliance_draft",
    "sort.py::patch_manifest_package",
    "sort.py::run_sort_endpoint",
    "sort.py::seed_manifest",
    "training.py::add_manager_comment",
    "training.py::add_trainer_comment",
    "training.py::submit_phase4_observation",
    "training.py::submit_trainee_review",
    "training.py::submit_training_record",
    "training.py::update_task",
    "truck_assignments.py::create_assignment",
    "truck_assignments.py::update_assignment",
    "truck_transfers.py::create_transfers",
}

# Follow-ups from D13 that D14 closed: truck CRUD, PlaceType Library
# promotion/status, ADP timesheet upload, trainee reassignment, and relationship
# creation. Empty on purpose — every entry left in _NO_AUDIT above is now a
# settled decision that the write is routine operational traffic, not a backlog
# item. Re-populate it if a future pass defers something again.
_DEFERRED_NOT_SETTLED: set[str] = set()


def _audited_names(tree: ast.AST) -> set[str]:
    """Functions whose own body contains an audit write."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for call in ast.walk(node):
                if isinstance(call, ast.Call):
                    name = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
                    if name in _AUDIT_CALLS:
                        out.add(node.name)
                        break
    return out


def _called_names(fn: ast.AST):
    for call in ast.walk(fn):
        if isinstance(call, ast.Call):
            name = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
            if name:
                yield name


def _write_endpoints_without_audit() -> list[str]:
    """"file.py::func" for every write endpoint with no audit path."""
    missing: list[str] = []
    for path in sorted(ROUTERS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        reaches = _audited_names(tree)
        local = {
            n.name: n for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        # Transitive closure: an endpoint that calls a helper that audits is
        # audited. Three passes is well past the depth this codebase uses.
        for _ in range(3):
            for name, fn in local.items():
                if name in reaches:
                    continue
                if any(c in reaches for c in _called_names(fn)):
                    reaches.add(name)

        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            is_write = any(
                getattr(d.func if isinstance(d, ast.Call) else d, "attr", None) in _WRITE_VERBS
                for d in node.decorator_list
            )
            if is_write and node.name not in reaches:
                missing.append(f"{path.name}::{node.name}")
    return missing


class TestAuditCoverage:
    def test_no_new_unaudited_write_endpoint(self):
        missing = set(_write_endpoints_without_audit())
        new = sorted(missing - _NO_AUDIT)
        assert not new, (
            "these write endpoints change persisted state with no audit row:\n  "
            + "\n  ".join(new)
            + "\n\nAdd write_audit(...) before db.commit() (see ADR-274 D13), or add "
              "the endpoint to _NO_AUDIT with a reason if it is routine operational "
              "traffic that would dilute the audit log."
        )

    def test_allowlist_has_no_stale_entries(self):
        # An entry that has since been audited must be removed, or the allowlist
        # slowly becomes a list of things nobody re-checks.
        missing = set(_write_endpoints_without_audit())
        stale = sorted(_NO_AUDIT - missing)
        assert not stale, (
            "these endpoints now audit and should be removed from _NO_AUDIT:\n  "
            + "\n  ".join(stale)
        )

    def test_the_scan_actually_finds_endpoints(self):
        # Guards the guard. If decorator detection breaks, `missing` is empty,
        # both tests above pass vacuously, and the coverage is unprotected while
        # looking protected.
        found = _write_endpoints_without_audit()
        assert len(found) > 20, (
            f"scan found only {len(found)} unaudited endpoints — detection is "
            "probably broken, so the guard is passing for the wrong reason"
        )

    def test_deferred_set_is_a_subset_of_the_allowlist(self):
        # The deferred list is documentation; if it drifts from _NO_AUDIT it
        # stops describing anything real.
        assert _DEFERRED_NOT_SETTLED <= _NO_AUDIT, (
            "deferred entries not present in _NO_AUDIT: "
            f"{sorted(_DEFERRED_NOT_SETTLED - _NO_AUDIT)}"
        )


class TestPrivilegedTierIsAudited:
    """The tier D13 actually fixed — named explicitly so a revert is caught."""

    @pytest.mark.parametrize("entry", [
        "companies.py::create_company",
        "companies.py::update_company",
        "companies.py::deactivate_company",
        "companies.py::reactivate_company",
        "companies.py::bootstrap_company_admin",
        "companies.py::update_company_config_super_admin",
        "companies.py::update_my_company_config",
        "companies.py::update_company_discord_config",
        "companies.py::update_my_discord_config",
        "companies.py::add_check_in_deadline",
        "companies.py::delete_check_in_deadline",
        "registration.py::send_invite",
        "registration.py::resend_credentials",
        "registration.py::complete_registration",
        "dispatch.py::create_hub",
        "dispatch.py::publish_hub",
        "dispatch.py::record_confirmation",
        "dispatch.py::confirm_all_pending",
        "dispatch.py::create_package_manifest",
        "dispatch.py::update_package_manifest",
        "notifications.py::prune_notifications",
        "employee_relationships.py::clear_employee_relationships",
        "assignment_members.py::remove_assignment_member",
        "building_profiles.py::delete_building_profile",
        "assignment_change_requests.py::cancel_change_request",
        "assignment_change_requests.py::purge_pending_request",
        "schedule_change_requests.py::cancel_schedule_change_request",
        # D14 — the eight D13 flagged as follow-ups rather than settled
        "trucks.py::create_truck",
        "trucks.py::update_truck",
        "trucks.py::reactivate_truck",
        "building_profile_library.py::promote_to_library",
        "building_profile_library.py::update_library_status",
        "adp.py::upload_flex_timesheets",
        "training.py::reassign_trainee",
        "employee_relationships.py::create_employee_relationship",
    ])
    def test_endpoint_is_audited(self, entry: str):
        assert entry not in set(_write_endpoints_without_audit()), (
            f"{entry} lost its audit row — this endpoint is in the privileged or "
            "destructive tier (ADR-274 D13) and must record who acted"
        )

    def test_every_hard_delete_is_audited(self):
        # ADR-132's own standard: a DELETE removes data that cannot be recovered
        # from the row afterwards, so the audit row is the only remaining record.
        missing = _write_endpoints_without_audit()
        deletes = []
        for path in sorted(ROUTERS.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for d in node.decorator_list:
                    f = d.func if isinstance(d, ast.Call) else d
                    if getattr(f, "attr", None) == "delete":
                        deletes.append(f"{path.name}::{node.name}")
        unaudited = sorted(set(deletes) & set(missing))
        assert not unaudited, (
            "DELETE endpoints with no audit row (ADR-132 DP-1 standard):\n  "
            + "\n  ".join(unaudited)
        )


class TestSuperAdminActorHandling:
    """actor_id is a FOREIGN KEY — a super admin cannot go in it (ADR-274 D13).

    `audit_logs.actor_id` is `ForeignKey("employees.id")` and a super admin has
    no Employee row by design, so writing their Cognito sub there raises
    ForeignKeyViolation and 500s the endpoint. The first implementation did
    exactly that; staging caught it, not the unit tests, because nothing here
    exercised a real database constraint.
    """

    def _companies_src(self) -> str:
        return (ROUTERS / "companies.py").read_text(encoding="utf-8")

    def test_no_cognito_sub_is_written_to_actor_id(self):
        src = self._companies_src()
        assert "actor_id=_super_admin_actor(" not in src, (
            "a super admin's Cognito sub is being written to actor_id, which is "
            "a FK to employees.id — this raises ForeignKeyViolation at runtime"
        )

    def test_super_admin_identity_travels_in_the_payload(self):
        src = self._companies_src()
        assert "super_admin_identity" in src, (
            "super-admin audit rows must carry the actor in the JSONB payload, "
            "which has no FK constraint"
        )
        # The literal lives in the shared helper (services/audit.py), which is
        # where a second super-admin surface can reach it (ADR-274 D14).
        audit_src = (ROUTERS.parent / "services" / "audit.py").read_text(encoding="utf-8")
        assert '"actor_kind": "super_admin"' in audit_src, (
            "super_admin_identity no longer stamps actor_kind — an audit row "
            "would record the action with no identifiable actor"
        )

    def test_every_audit_block_identifies_its_actor(self):
        # A row with neither actor_id nor an identity payload records that
        # something happened but not who did it — the one thing an audit row
        # exists to answer.
        import re
        src = self._companies_src()
        anonymous = []
        for m in re.finditer(r"    write_audit\(\n(?:.*?\n)*?    \)\n", src):
            block = m.group(0)
            action = re.search(r'action_type="([^"]+)"', block)
            if "super_admin_identity" not in block and "actor_id=" not in block:
                anonymous.append(action.group(1) if action else "?")
        assert not anonymous, (
            f"audit blocks with no actor at all: {anonymous}"
        )


class TestClaimKeyNames:
    """Reading a claim that does not exist fails silently (ADR-274 D14).

    `get_current_user` returns exactly four keys — id, email, username,
    cognito_groups — and `get_super_admin` passes that dict through untouched.
    `building_profile_library` read `super_admin.get("sub")`, which is not one of
    them, so `admin_id` was **always None** and every provenance column
    (promoted_by, created_by, updated_by, note_verified_by) was written null.

    `.get()` on a missing key raises nothing. There is no type error, no 500, no
    log line — the data is simply anonymous, and stays that way until someone
    asks who promoted an entry and finds no answer.
    """

    _CLAIM_KEYS = {"id", "email", "username", "cognito_groups"}

    def test_get_current_user_still_returns_the_expected_keys(self):
        # If this changes, the assertion below is testing the wrong contract.
        deps = (ROUTERS.parent / "api" / "deps.py").read_text(encoding="utf-8")
        block = deps[deps.index("def get_current_user"):]
        block = block[:block.index("def ", 10)]
        import re
        keys = set(re.findall(r'^\s+"(\w+)":', block, re.M))
        assert self._CLAIM_KEYS <= keys, (
            f"get_current_user no longer returns {self._CLAIM_KEYS - keys}"
        )
        assert "sub" not in keys, (
            "a 'sub' key now exists — the guard below is obsolete and the "
            "historical bug it describes can no longer occur"
        )

    def test_no_router_reads_a_sub_claim(self):
        offenders = []
        for path in sorted(ROUTERS.glob("*.py")):
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if '.get("sub")' in line and not line.strip().startswith("#"):
                    offenders.append(f"{path.name}:{n}")
        assert not offenders, (
            "these read a 'sub' claim that get_current_user never sets, so the "
            f"value is always None: {offenders}"
        )
