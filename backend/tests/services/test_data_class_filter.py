"""ADR-280 D5 — data-class filtering for cross-tenant queries.

The scoping rule these encode is the easy thing to get backwards: almost every
read is ALREADY scoped to caller.company_id, and adding a data_class filter to
those would return an empty page to every user of a seed tenant. These helpers
are only for queries that span tenants.
"""
import inspect

from app.models.company import Company
from app.services import data_class as dc


class TestConstants:
    def test_the_three_classes_match_the_model(self):
        assert (dc.LIVE, dc.SEED, dc.DEMO) == ("live", "seed", "demo")


class TestScopingRuleIsDocumented:
    def test_the_module_says_where_it_must_not_be_used(self):
        """The dangerous misuse is applying this to a caller-scoped query. If
        that warning is ever dropped, the next reader adds the filter to a
        dashboard and empties it for every seed-tenant user."""
        src = inspect.getsource(dc)
        assert "caller.company_id" in src
        assert "must NOT" in src

    def test_only_live_takes_the_model_explicitly(self):
        """An inferred entity is wrong the moment the query joins — and wrong
        silently, filtering on the joined table's company_id instead."""
        sig = inspect.signature(dc.only_live)
        assert list(sig.parameters) == ["q", "model"]

    def test_breakdown_aggregates_in_sql(self):
        """The table this was written for holds 1,194,365 rows. Counting them
        in a Python loop is a self-inflicted outage on a diagnostic helper."""
        src = inspect.getsource(dc.class_breakdown)
        assert "group_by" in src
        assert "func.count" in src
        assert "for data_class, _ in rows" not in src


class TestCallerScopedEndpointsAreUntouched:
    def test_no_caller_scoped_router_filters_on_data_class(self):
        """ADR-280 D5's boundary, guarded. Every analytics endpoint is already
        scoped to caller.company_id; adding data_class there returns nothing
        for seed-tenant users, which is a worse bug than the one it fixes.

        companies.py is the exception — it is the one cross-tenant surface, and
        there data_class is EXPOSED, not filtered on.
        """
        from pathlib import Path

        routers = Path(__file__).resolve().parents[2] / "app" / "routers"
        offenders = []
        for f in routers.glob("*.py"):
            if f.name == "companies.py":
                continue
            code = "\n".join(
                ln for ln in f.read_text().splitlines()
                if not ln.lstrip().startswith("#")
            )
            if "data_class ==" in code or "data_class !=" in code:
                offenders.append(f.name)
        assert not offenders, (
            f"caller-scoped routers must not filter on data_class: {offenders}"
        )

    def test_super_admin_exposes_the_class(self):
        """The one cross-tenant surface should SHOW which tenants are seed —
        the fix there is visibility, not filtering."""
        from app.routers.companies import CompanyResponse

        assert "data_class" in CompanyResponse.model_fields

    def test_super_admin_default_is_live(self):
        """Matches the model default. A company row that predates the column
        reads as real, which is the safe direction (D2)."""
        from app.routers.companies import CompanyResponse

        assert CompanyResponse.model_fields["data_class"].default == "live"


class TestModelStillAgrees:
    def test_response_default_matches_the_column_default(self):
        col = Company.__table__.columns["data_class"]
        from app.routers.companies import CompanyResponse

        assert CompanyResponse.model_fields["data_class"].default in str(
            col.server_default.arg
        )
