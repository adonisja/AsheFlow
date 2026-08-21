"""ADR-280 — tenant data class, and the guard that keeps seeds off live data.

The failure this prevents is not loud. A seed script that picks the wrong
company writes well-formed, correctly company-scoped rows — nothing downstream
flags them, and the only symptom is that a measurement taken months later is
quietly wrong.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from _seed_guard import LIVE, assert_not_live, assert_seedable, seed_target, seed_targets  # noqa: E402
from app.models.company import Company  # noqa: E402


class _FakeQuery:
    def __init__(self, rows):
        self._rows = list(rows)

    def filter(self, *criteria):
        # Crude but sufficient: the guard only ever filters on slug, id, or
        # data_class != LIVE. Evaluate against the real SQLAlchemy expressions
        # by reading the bound value off each criterion.
        rows = self._rows
        for c in criteria:
            col = c.left.name
            val = c.right.value
            op = c.operator.__name__
            if op == "ne":
                rows = [r for r in rows if getattr(r, col) != val]
            else:
                rows = [r for r in rows if str(getattr(r, col)) == str(val)]
        return _FakeQuery(rows)

    def order_by(self, *_):
        return _FakeQuery(sorted(self._rows, key=lambda r: r.slug))

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class _FakeDB:
    def __init__(self, rows):
        self._rows = rows

    def query(self, _model):
        return _FakeQuery(self._rows)


def _c(slug, data_class, cid=None):
    return Company(id=cid or slug, name=slug, slug=slug, data_class=data_class)


LIVE_CO = _c("acme", "live")
SEED_CO = _c("dsp-test", "seed")
DEMO_CO = _c("showcase", "demo")


class TestSeedTarget:
    def test_picks_the_seedable_tenant_over_the_live_one(self):
        db = _FakeDB([LIVE_CO, SEED_CO])
        assert seed_target(db).slug == "dsp-test"

    def test_refuses_a_live_tenant_by_slug(self):
        """The whole point: an operator naming a live tenant is stopped, not
        obeyed."""
        db = _FakeDB([LIVE_CO, SEED_CO])
        with pytest.raises(SystemExit) as e:
            seed_target(db, slug="acme")
        assert "data_class='live'" in str(e.value)

    def test_a_typo_slug_is_not_reported_as_an_empty_database(self):
        """Two different problems must not share one message — "no seedable
        company" sends the operator off to create one they already have."""
        db = _FakeDB([LIVE_CO, SEED_CO])
        with pytest.raises(SystemExit) as e:
            seed_target(db, slug="dsp-tset")
        assert "No company with slug" in str(e.value)
        assert "Create one" not in str(e.value)

    def test_live_only_database_yields_no_target(self):
        db = _FakeDB([LIVE_CO])
        with pytest.raises(SystemExit) as e:
            seed_target(db)
        assert "No seedable company" in str(e.value)

    def test_demo_tenants_are_seedable(self):
        db = _FakeDB([LIVE_CO, DEMO_CO])
        assert seed_target(db).slug == "showcase"

    def test_selection_is_deterministic(self):
        """The bare .first() this replaces had no ORDER BY, so two runs against
        the same database could pick different companies."""
        a = _FakeDB([_c("zeta", "seed"), _c("alpha", "seed")])
        b = _FakeDB([_c("alpha", "seed"), _c("zeta", "seed")])
        assert seed_target(a).slug == seed_target(b).slug == "alpha"


class TestSeedTargets:
    def test_fan_out_excludes_live_tenants(self):
        """seed_training_curriculum defaulted to every company. On a database
        with a live tenant that wrote into real customer data."""
        db = _FakeDB([LIVE_CO, SEED_CO, DEMO_CO])
        slugs = [c.slug for c in seed_targets(db)]
        assert "acme" not in slugs
        assert set(slugs) == {"dsp-test", "showcase"}


class TestAssertSeedable:
    def test_an_explicit_id_is_still_checked(self):
        """The hand-typed path is the one most likely to carry a copy-pasted
        production id, so it must not be the one without protection."""
        db = _FakeDB([LIVE_CO, SEED_CO])
        with pytest.raises(SystemExit):
            assert_seedable(db, "acme")
        assert assert_seedable(db, "dsp-test").slug == "dsp-test"

    def test_unknown_id_stops_rather_than_returning_none(self):
        db = _FakeDB([SEED_CO])
        with pytest.raises(SystemExit):
            assert_seedable(db, "nope")


class TestAssertNotLive:
    def test_destructive_work_is_refused_on_live(self):
        with pytest.raises(SystemExit):
            assert_not_live(LIVE_CO)

    def test_allowed_on_seed_and_demo(self):
        assert_not_live(SEED_CO)
        assert_not_live(DEMO_CO)


class TestModel:
    def test_default_is_live_and_that_is_the_safe_direction(self):
        """D2. A company created by a path that does not know about this column
        must be treated as real — the failure mode is "a seeded tenant was
        mistakenly protected", never "a live tenant was mistakenly wiped"."""
        col = Company.__table__.columns["data_class"]
        assert col.nullable is False
        assert "live" in str(col.server_default.arg)

    def test_it_is_indexed(self):
        assert Company.__table__.columns["data_class"].index is True


class TestNoScriptBypassesTheGuard:
    def test_no_seed_script_still_uses_a_bare_company_first(self):
        """The original bug, guarded at the source. `db.query(Company).first()`
        with no filter picks an arbitrary tenant."""
        offenders = []
        for f in (Path(__file__).resolve().parents[1] / "scripts").glob("seed_*.py"):
            code = "\n".join(
                ln for ln in f.read_text().splitlines()
                if not ln.lstrip().startswith("#")
            )
            if "query(Company).first()" in code:
                offenders.append(f.name)
        assert not offenders, f"bare Company.first() still in: {offenders}"

    def test_no_seed_script_fans_out_over_every_company(self):
        offenders = []
        for f in (Path(__file__).resolve().parents[1] / "scripts").glob("seed_*.py"):
            # Strip comments first. The fixed script explains the old pattern in
            # a comment, and a naive substring search reads its own explanation
            # as the offence.
            code = "\n".join(
                ln for ln in f.read_text().splitlines()
                if not ln.lstrip().startswith("#")
            )
            if "query(Company).all()" in code:
                offenders.append(f.name)
        assert not offenders, f"unfiltered Company.all() still in: {offenders}"

    def test_seed_demo_classifies_the_tenants_it_creates(self):
        """It is the one script that CREATES the disposable tenants, so it is
        the one place that may classify them. Without this they inherit the
        'live' default and every other seed script correctly refuses them."""
        src = (Path(__file__).resolve().parents[1] / "scripts" / "seed_demo.py").read_text()
        assert 'data_class="seed"' in src
