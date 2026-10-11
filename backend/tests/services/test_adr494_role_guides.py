"""ADR-494 D4 — the role guide seeds, and what must stay true about them.

These are AST/structure tests, not DB tests: the behaviours worth pinning here
are properties of the seed data and the version comparison, both of which are
pure. The three-case seeding behaviour (insert / follow / never-revert) was
verified against the real database during the build; what it needs from a test
suite is the version comparison it depends on, which is where the arithmetic
hides.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from app.services.role_guide_seeds import (
    MODES,
    SEED_VERSION,
    SEEDED_ROLES,
    _BODIES,
    iter_seeds,
    seed_key,
)
from app.services.seed_role_guides import _version_at_least


class TestEveryRoleHasAGuide:
    """The coverage test, written in the direction that catches a stale list.

    ADR-464's lesson (feedback_completeness_test_direction): a test that walks
    the REGISTRY and checks each entry resolves passes forever while the
    registry goes stale. So this walks the ROLE VOCABULARY -- the thing that
    grows -- and requires each role to have text.
    """

    def test_every_cognito_role_has_a_guide_in_both_modes(self):
        """A role that can hold a Cognito group must have a guide in both modes.

        ROLE_TO_COGNITO_GROUP is the nearest thing this repo has to a canonical
        role list (`Employee.role` is a free String(50) with no CHECK), and its
        own comment explains why it is the one to bind to: a role missing from
        it never syncs its group.

        When this fails, someone added a role and did not write its guide. The
        consequence is not cosmetic: role_change and operating_mode_change send
        that person to /my-role, which 404s for them specifically.
        """
        from app.routers.registration import ROLE_TO_COGNITO_GROUP

        missing = [
            (role, mode)
            for role in ROLE_TO_COGNITO_GROUP
            for mode in MODES
            if (role, mode) not in _BODIES
        ]
        assert missing == [], (
            f"roles in ROLE_TO_COGNITO_GROUP with no guide text: {missing}. "
            f"Add them to _BODIES in app/services/role_guide_seeds.py."
        )

    def test_iter_seeds_yields_one_per_role_per_mode(self):
        rows = list(iter_seeds())
        assert len(rows) == len(SEEDED_ROLES) * len(MODES)
        assert len({key for *_, key in rows}) == len(rows), "duplicate seed_key"

    def test_seed_keys_are_stable(self):
        """The key format is data, not an implementation detail.

        Changing it orphans every existing row: the next seed run finds no key
        it recognises, inserts 20 more, and the unique index on
        (company_id, role, operating_mode) raises. Pinned so that a rename has
        to be a deliberate migration rather than a refactor.
        """
        assert seed_key("walker", "full") == "role_guide:walker:full"
        assert seed_key("driver_trainee", "workforce") == "role_guide:driver_trainee:workforce"


class TestTheContentFitsItsColumns:
    """A body longer than its column is an IntegrityError on deploy, per tenant."""

    def test_titles_fit_String_80(self):
        over = [(r, m, len(t)) for r, m, t, _, _ in iter_seeds() if len(t) > 80]
        assert over == [], f"titles exceeding RoleGuide.title String(80): {over}"

    def test_bodies_fit_the_patch_limit(self):
        """Seeds must satisfy the same cap the PATCH endpoint enforces (8000).

        If a seed exceeded it, an admin could GET their guide, change one word,
        PATCH it back, and get a 422 -- with the error pointing at their edit
        rather than at our seed.
        """
        over = [(r, m, len(b)) for r, m, _, b, _ in iter_seeds() if len(b) > 8000]
        assert over == [], f"bodies exceeding the PATCH max_length: {over}"

    def test_no_body_is_a_stub(self):
        thin = [(r, m, len(b)) for r, m, _, b, _ in iter_seeds() if len(b) < 200]
        assert thin == [], (
            f"guide bodies too short to be useful: {thin}. A guide is the only "
            f"exit from a prompt -- a one-line page is the dismiss-only modal "
            f"ADR-494 D1 replaced, with extra steps."
        )


class TestAdminGuidesNameAdminCorrectly:
    """CLAUDE.md: never describe access as manager-only without including admin."""

    @pytest.mark.parametrize("mode", MODES)
    def test_management_guide_does_not_claim_exclusivity(self, mode):
        body = _BODIES[("management", mode)][1]
        # The management guide describes privileged reads. Wherever it does, it
        # must say admins have them too -- a manager reading "only you can see
        # the audit log" learns the org chart wrong.
        assert "Admins see all of this too" in body, (
            "the management guide must state that admins share its access"
        )

    @pytest.mark.parametrize("mode", MODES)
    def test_admin_guide_claims_full_access(self, mode):
        body = _BODIES[("admin", mode)][1]
        assert "full access to everything" in body


class TestVersionComparison:
    """The arithmetic that decides whether an unedited row follows a new seed.

    Found by a re-run, not by review: `seed_version` is String(16) and
    SEED_VERSION was an int, so the comparison raised TypeError -- but ONLY on
    the second run, because the insert path never compares. A dry run and a
    first --commit both passed.
    """

    def test_seed_version_type_matches_its_column(self):
        """The constant and the column must agree.

        This is the assertion that would have caught the original bug at import
        time instead of on the second deploy.
        """
        from app.models.role_guide import RoleGuide

        col = RoleGuide.__table__.c.seed_version
        assert isinstance(SEED_VERSION, str), (
            f"SEED_VERSION is {type(SEED_VERSION).__name__}; "
            f"seed_version is {col.type}. Comparing them raises TypeError."
        )
        assert len(SEED_VERSION) <= col.type.length

    @pytest.mark.parametrize("stored,target,expected", [
        (None, "1", False),      # pre-versioning row -> seed applies
        ("", "1", False),
        ("1", "1", True),        # current -> skip
        ("2", "1", True),
        ("1", "2", False),       # older -> follow
        # The ordering trap: lexically "10" < "9", so a string compare would
        # stop following seeds at the tenth revision and report nothing.
        ("9", "10", False),
        ("10", "9", True),
        ("1", "1.0", True),      # padding: "1" and "1.0" are the same version
        ("1.0", "1", True),
        ("1.1", "1", True),
        ("1.1", "1.2", False),
        ("junk", "1", False),    # unparseable -> treated as older
    ])
    def test_version_at_least(self, stored, target, expected):
        assert _version_at_least(stored, target) is expected


class TestTheSeederDoesNotCommit:
    """ADR-490: a service that commits inside someone else's transaction splits
    an atomic write in half.

    `seed_role_guides` runs inside company creation's transaction, between the
    config insert and that endpoint's write_audit/commit. A commit here would
    land the guides and the company separately -- and a later failure would
    leave guides for a company that does not exist.
    """

    def test_no_commit_in_the_seeder(self):
        src = pathlib.Path("app/services/seed_role_guides.py").read_text()
        tree = ast.parse(src)

        # Parse, do not grep: this module's docstring says the word "commit"
        # several times, and a substring search matches the prose. (That
        # mistake has its own entry in LEARNING_GUIDE; it has been made more
        # than ten times in this repo.)
        commits = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("commit", "rollback")
        ]
        assert commits == [], (
            f"seed_role_guides calls {[c.func.attr for c in commits]} at line(s) "
            f"{[c.lineno for c in commits]} -- the caller owns the transaction."
        )

    def test_the_seeder_does_flush(self):
        """It must flush, though: the caller's write_audit needs the ids."""
        src = pathlib.Path("app/services/seed_role_guides.py").read_text()
        flushes = [
            n for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "flush"
        ]
        assert flushes, "seed_role_guides must flush so the caller can audit the ids"
