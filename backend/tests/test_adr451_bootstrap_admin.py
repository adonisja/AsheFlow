"""ADR-451 D1: exactly one Owner per company.

THE BUG: `bootstrap_company_admin` matched an existing row BY EMAIL, so the
same address was idempotent and a DIFFERENT address silently created a second
admin row. Nothing enforced "one", and the UI that triggers it held its only
record of an existing admin in React state that vanished on reload.

The fix is to match on the FLAG: "does this company already have a bootstrap
admin?" must not depend on what the caller typed.
"""
import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
ROUTER = ROOT / "backend" / "app" / "routers" / "companies.py"
# The ADR-451 migration keeps its ORIGINAL filename: a migration file is
# history, and renaming it would break every database already stamped with it.
MIGRATION = (ROOT / "backend" / "alembic" / "versions"
             / "f501ec69b808_adr451_bootstrap_admin.py")
# ADR-452 renamed the column and REBUILT the index (its WHERE clause named the
# old column), so the live constraint now lives here.
RENAME_MIGRATION = (ROOT / "backend" / "alembic" / "versions"
                    / "db8751d428ad_adr452_owner_rename.py")


def _bootstrap_fn():
    tree = ast.parse(ROUTER.read_text())
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "bootstrap_company_admin")


class TestTheMatchIsOnTheFlagNotTheEmail:
    def test_it_queries_is_owner(self):
        body = ast.dump(_bootstrap_fn())
        assert "is_owner" in body, (
            "bootstrap still matches on something other than the flag — a "
            "different email will create a second admin (ADR-451 D1)"
        )

    def test_the_lookup_does_not_filter_on_the_payload_email(self):
        """THE original defect, stated precisely.

        `Employee.email == payload.email` is what made a corrected address
        create a duplicate instead of editing the existing row.
        """
        src = ROUTER.read_text()
        start = src.index("def bootstrap_company_admin")
        body = src[start:start + 2500]
        assert "Employee.email == payload.email" not in body, (
            "the existing-admin lookup still filters by the caller's email "
            "(ADR-451 D1)"
        )

    def test_a_new_row_is_created_with_the_flag_set(self):
        """Without this the constraint protects nothing: every row is false.

        Checked on the AST of the Employee(...) call rather than a text slice,
        which silently missed a branch once already (ADR-446).
        """
        creates = [
            n for n in ast.walk(_bootstrap_fn())
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "Employee"
        ]
        assert creates, "bootstrap no longer constructs an Employee"
        kwargs = {k.arg for c in creates for k in c.keywords}
        assert "is_owner" in kwargs, \
            "the created row does not set is_owner (ADR-451 D1)"


class TestASecondBootstrapAdminIsRefused:
    def test_an_active_admin_gets_409(self):
        body = ast.dump(_bootstrap_fn())
        assert "409" in body

    def test_the_message_points_at_editing_not_retrying(self):
        """"Already exists" invites a retry with a different address, which is
        exactly what created the duplicate."""
        src = ROUTER.read_text()
        start = src.index("def bootstrap_company_admin")
        body = src[start:start + 2500]
        assert "Edit their" in body or "edit" in body.lower(), (
            "the 409 does not tell the operator what to do instead"
        )


class TestAPendingAdminIsCorrectedNotDuplicated:
    def test_the_name_and_email_are_updated_in_place(self):
        """D2: nobody has accepted anything yet, so re-running bootstrap with a
        corrected address should FIX the row, not add another."""
        src = ROUTER.read_text()
        start = src.index("def bootstrap_company_admin")
        body = src[start:start + 2500]
        assert "employee.name = payload.name" in body
        assert "employee.email = payload.email" in body


class TestTheDatabaseEnforcesItToo:
    """Code can be bypassed by the next code path; a constraint cannot."""

    def test_the_migration_creates_a_unique_partial_index(self):
        """Checked on the CURRENT migration: ADR-452 rebuilt the index because
        its WHERE clause named the old column, and a renamed index would still
        reference `is_bootstrap_admin` and fail on the next write."""
        src = RENAME_MIGRATION.read_text()
        assert "ix_employees_owner" in src
        assert "UNIQUE INDEX" in src, (
            "the Owner index is not unique — two rows could be flagged for "
            "one company"
        )
        assert "WHERE is_owner" in src, (
            "a non-partial unique index on company_id would forbid a second "
            "EMPLOYEE, not a second Owner"
        )

    def test_the_original_migration_created_it_too(self):
        """A database stamped at ADR-451 and never upgraded still needs it."""
        src = MIGRATION.read_text()
        assert "unique=True" in src and "postgresql_where" in src

    def test_nothing_is_backfilled(self):
        """Inferring "the oldest admin" is wrong exactly when the original was
        offboarded and replaced: it marks someone who never held the role, and
        D3 then locks their name."""
        src = MIGRATION.read_text()
        assert "UPDATE" not in src.upper(), (
            "the migration backfills the flag — ADR-451 rejected inference"
        )
        assert "server_default=sa.false()" in src


class TestTheSummaryExposesIt:
    def test_admin_summary_carries_the_flag_and_pending_email(self):
        """D6 needs it to decide between "create" and "edit"."""
        src = ROUTER.read_text()
        start = src.index("class AdminSummary")
        body = src[start:start + 900]
        assert "is_owner" in body
        assert "pending_email" in body


def _fn(name: str):
    tree = ast.parse(ROUTER.read_text())
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == name)


def _src(name: str, span: int = 4000) -> str:
    src = ROUTER.read_text()
    start = src.index(f"def {name}")
    return src[start:start + span]


class TestAPendingAdminIsEditable:
    """ADR-451 D2. Nobody has accepted anything: no account, no session, no
    history. The row is an unclaimed placeholder."""

    def test_both_name_and_email_can_change(self):
        body = _src("edit_owner")
        assert "admin.name = payload.name" in body
        assert "admin.email = payload.email" in body

    def test_the_outstanding_invite_is_reissued(self):
        """The old link points at an address that is no longer the admin."""
        body = _src("edit_owner")
        assert "InviteToken.employee_id == admin.id).delete()" in body, \
            "editing leaves the previous invite live (ADR-451 D2)"
        # Any invite sender satisfies D2; ADR-455 moved this to the Owner
        # template, so match the shared suffix rather than one function name.
        assert "invite_email(" in body, "a fresh invite is not sent after the edit"

    def test_a_pending_admin_can_be_removed(self):
        body = _src("delete_owner")
        assert "db.delete(admin)" in body

    def test_removing_also_clears_the_invite(self):
        """An orphaned token points at an employee row that no longer exists."""
        body = _src("delete_owner")
        assert "InviteToken.employee_id == admin.id).delete()" in body


class TestAConfirmedAdminIsProtected:
    """ADR-451 D3. A real person with a Cognito account, sessions and audit
    history under their name."""

    def test_the_name_is_locked(self):
        """Same lesson: assert the guard runs, not that the message exists."""
        fn = _fn("edit_owner")
        guards = [
            n for n in ast.walk(fn)
            if isinstance(n, ast.If) and "confirmed" in ast.dump(n.test)
            and "name" in ast.dump(n.test)
        ]
        assert guards, (
            "edit_owner does not gate the name on confirmation — a "
            "confirmed admin can be renamed (ADR-451 D3)"
        )
        assert any(isinstance(n, ast.Raise) for g in guards for n in ast.walk(g))
        assert "name is fixed" in _src("edit_owner")

    def test_a_direct_email_write_is_refused(self):
        """Writing the address directly would lock a live tenant's admin out on
        a typo, and the only person who could fix it is the one locked out."""
        body = _src("edit_owner")
        assert "needs verification" in body, \
            "a confirmed admin's email can be written without proof (D4)"

    def test_a_confirmed_admin_cannot_be_deleted(self):
        """It would orphan their audit history and leave the tenant with no
        admin at all.

        Asserts the GUARD, not just its message. An earlier version of this
        test only looked for the wording, so stubbing the condition to `if
        False:` left a confirmed admin deletable with every test green.
        """
        fn = _fn("delete_owner")
        # The refusal must be reached by comparing account_status, and the
        # delete must not be reachable without passing that comparison.
        guards = [
            n for n in ast.walk(fn)
            if isinstance(n, ast.If)
            and "account_status" in ast.dump(n.test)
            and "pending_verification" in ast.dump(n.test)
        ]
        assert guards, (
            "delete_owner does not branch on account_status — a "
            "confirmed admin can be deleted (ADR-451 D3)"
        )
        assert any(
            isinstance(n, ast.Raise) for g in guards for n in ast.walk(g)
        ), "the account_status branch does not raise"
        assert "cannot be removed" in _src("delete_owner")

    def test_the_refusals_say_what_to_do_instead(self):
        """A 409 that only refuses sends an operator back to the same action."""
        assert "offboard" in _src("delete_owner").lower()
        assert "email change flow" in _src("edit_owner")


class TestBothEndpointsAreGuarded:
    def test_they_are_super_admin_only(self):
        for name in ("edit_owner", "delete_owner"):
            args = ast.dump(_fn(name).args)
            assert "get_super_admin" in args, f"{name} is not super-admin gated"

    def test_they_are_scoped_to_the_company(self):
        """Dimension 1: the lookup must not find another tenant's admin."""
        body = _src("_owner_or_404")
        assert "Employee.company_id == company_id" in body

    def test_the_delete_is_audited_before_the_row_goes(self):
        """An audit row naming a row about to vanish is the only record it
        existed (cf. ADR-450 D5)."""
        body = _src("delete_owner")
        assert body.index("write_audit(") < body.index("db.delete(admin)")

    def test_the_patch_body_forbids_unknown_keys(self):
        """Dimension 9: a request body is attacker-controlled input."""
        src = ROUTER.read_text()
        start = src.index("class BootstrapAdminPatch")
        assert 'extra="forbid"' in src[start:start + 400]


class TestTheListPageSeesTheOwner:
    """ADR-451 D6. The bug was not the missing constraint -- it was that the
    operator could not SEE what they were about to duplicate.

    `Companies.tsx` held the result of its own last bootstrap call in React
    state, which its own comment admits is "gone on reload".
    """

    TSX = ROOT / "frontend" / "src" / "pages" / "superadmin" / "Companies.tsx"

    def test_the_list_response_carries_the_owner(self):
        src = ROUTER.read_text()
        i = src.index("class CompanyResponse")
        assert "owner: Optional[AdminSummary]" in src[i:i + 900], (
            "the companies list returns only has_admin, which says WHETHER an "
            "admin exists and not WHO (ADR-451 D6)"
        )

    def test_owners_are_fetched_in_one_query(self):
        """This list grows with the tenant count; an N+1 here is a page that
        gets slower as the business succeeds.

        Counts queries INSIDE THE LOOP, not in the function. An earlier version
        counted `.query(` calls anywhere in the body, so moving the lookup into
        the `for` changed nothing and the test passed on a genuine N+1.
        """
        fn = _fn("list_companies")
        loops = [n for n in ast.walk(fn) if isinstance(n, ast.For)]
        assert loops, "list_companies no longer iterates companies"

        in_loop = [
            n for loop in loops for n in ast.walk(loop)
            if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "query"
        ]
        assert not in_loop, (
            f"{len(in_loop)} database query/queries inside the companies loop "
            "— the Owner lookup must be batched before it (ADR-451 D6)"
        )
        assert "is_owner" in ast.dump(fn)

    def test_the_page_renders_the_owner_from_the_server(self):
        src = self.TSX.read_text()
        assert "company.owner" in src, \
            "the list page still has no server-side Owner (ADR-451 D6)"
        assert "company.owner.name" in src and "company.owner.email" in src

    def test_the_create_form_only_shows_when_there_is_no_owner(self):
        """THE ORIGINAL DEFECT. The form rendered unconditionally, so
        re-running bootstrap with a corrected address silently created a
        second admin."""
        src = self.TSX.read_text()
        owner_branch = src.index("company.owner ? (")
        form = src.index("<BootstrapForm companyId=")
        assert owner_branch < form, (
            "the create form renders before the Owner check — an operator "
            "cannot see the Owner they are about to duplicate"
        )

    def test_a_pending_email_change_is_visible(self):
        """Otherwise a reader wonders why the address looks stale."""
        src = self.TSX.read_text()
        assert "company.owner.pending_email" in src
        assert "awaiting confirmation" in src

    def test_the_invite_state_is_distinguished(self):
        """"Invite pending" and "Registered" are different situations with
        different remedies (D2 vs D3)."""
        src = self.TSX.read_text()
        assert "Invite pending" in src and "Registered" in src


class TestTheSuperAdminUsesTheHouseDropdown:
    """A native <select> renders with the OS palette, so on a dark theme it
    opens as a white panel with a system-blue highlight. SelectMenu.tsx exists
    for exactly this and says so in its own docstring; CollectionData.tsx
    records the same failure being fixed once already.
    """

    PAGES = [
        ROOT / "frontend" / "src" / "pages" / "superadmin" / "Companies.tsx",
        ROOT / "frontend" / "src" / "pages" / "superadmin" / "CompanyDetail.tsx",
    ]

    def test_no_native_select_survives(self):
        import re
        for page in self.PAGES:
            # `<select` in a comment is fine — it is how the decision is
            # explained. Only a real JSX element counts.
            code = re.sub(r"\{/\*.*?\*/\}", "", page.read_text(), flags=re.S)
            assert "<select" not in code, (
                f"{page.name} still renders a native <select>, which opens "
                "with the OS palette on a dark theme"
            )

    def test_they_use_the_shared_component(self):
        for page in self.PAGES:
            assert "SelectMenu" in page.read_text(), f"{page.name} has no SelectMenu"

    def test_the_offsets_are_computed_not_hardcoded(self):
        """Half these zones shift twice a year, and not together.

        Today Denver is MDT and Phoenix is MST — both UTC-7 — and in January
        they diverge again. A written-down offset is wrong for roughly half the
        year, silently, in a field whose whole job is to be unambiguous about
        time.
        """
        # The computation moved to utils/date.ts when four display sites
        # needed it too; the picker imports it rather than keeping a copy.
        util = (ROOT / "frontend" / "src" / "utils" / "date.ts").read_text()
        assert "Intl.DateTimeFormat" in util and "timeZoneName" in util, (
            "timezone offsets are not computed from Intl — a hardcoded table "
            "goes wrong at every DST transition"
        )
        src = self.PAGES[0].read_text()
        # A literal offset beside a city name is the smell this guards against.
        import re
        assert not re.search(r"label: '(?:New York|Chicago|Denver)[^']*UTC-\d", src), \
            "an offset is hardcoded into a label"

    def test_every_display_site_formats_the_zone(self):
        """Four pages SHOW a company timezone. A raw "America/New_York" is a
        path, not a label, and four sites rendering it four ways is how a
        format drifts."""
        import re
        sites = [
            ROOT / "frontend" / "src" / "components" / "dashboard" / "ManagementView.tsx",
            ROOT / "frontend" / "src" / "pages" / "DispatchDashboard.tsx",
            ROOT / "frontend" / "src" / "pages" / "superadmin" / "CompanyDetail.tsx",
            ROOT / "frontend" / "src" / "pages" / "superadmin" / "Companies.tsx",
        ]
        # A zone INTERPOLATED INTO TEXT: `>{...timezone}` or `({...timezone})`.
        # `value={timezone}` and `onChange={setTimezone}` are props, not text.
        rendered_re = re.compile(r"[>(]\s*\{\s*[a-zA-Z.]*[Tt]imezone\s*\}")
        for f in sites:
            src = f.read_text()
            hits = rendered_re.findall(src)
            assert not hits, (
                f"{f.name} renders a raw IANA string {hits} — it is a path, "
                "not a label (use formatZone)"
            )
            if "imezone" in src:
                assert "formatZone" in src, f"{f.name} shows a zone without formatZone"

    def test_the_formatter_lives_in_one_place(self):
        """It was briefly duplicated between the picker and the display sites."""
        date_util = (ROOT / "frontend" / "src" / "utils" / "date.ts").read_text()
        assert "export function zoneOffset" in date_util
        assert "export function formatZone" in date_util
        companies = self.PAGES[0].read_text()
        assert "function zoneHint" not in companies, \
            "the picker keeps a private copy of the offset logic"

    def test_the_zones_are_grouped_under_headers(self):
        """A flat list makes the reader parse an "America/" path prefix that
        carries no information once a heading says it."""
        src = self.PAGES[0].read_text()
        assert "header: true" in src, "the timezone list has no group headings"

    def test_the_timezone_list_is_defined_once(self):
        """Two copies drift: one page gains a zone and the other does not."""
        companies, detail = self.PAGES
        assert "export const TIMEZONES" in companies.read_text()
        assert "import { TIMEZONES }" in detail.read_text(), (
            "CompanyDetail keeps its own timezone list — it will drift from "
            "the create form"
        )
