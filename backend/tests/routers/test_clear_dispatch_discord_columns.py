"""Clear Dispatch reads the Discord columns off the model that has them.

`clear_dispatch` built its Discord retraction payload from `Company`, on the
belief that these fields were "also named discord_* on Company". They are not —
they live on `CompanyConfig`. So every clear raised:

    AttributeError: 'Company' object has no attribute 'discord_drivers_channel_id'

and returned a 500.

**The browser reported that as a CORS error**, because the exception escapes
before the CORS middleware adds its headers. Anyone debugging from the console
message goes looking at origins and headers instead of the traceback, which is
why this is worth pinning rather than trusting a comment.

Asserted against the ORM, not by grepping the router: the failure is an
attribute that does not exist on the queried model, and only the model can say
which attributes exist.
"""
import ast
from pathlib import Path

import pytest

from app.models.company import Company, CompanyConfig

ROUTER = Path(__file__).resolve().parents[2] / "app" / "routers" / "dispatch.py"

DISCORD_SUMMARY_COLUMNS = (
    "discord_drivers_channel_id",
    "discord_trainers_channel_id",
)


class TestTheColumnsLiveOnCompanyConfig:
    @pytest.mark.parametrize("col", DISCORD_SUMMARY_COLUMNS)
    def test_company_config_has_them(self, col):
        assert col in CompanyConfig.__table__.columns, (
            f"{col} moved off CompanyConfig — clear_dispatch reads it there"
        )

    @pytest.mark.parametrize("col", DISCORD_SUMMARY_COLUMNS)
    def test_company_does_not(self, col):
        """If these are ever ADDED to Company, this test fails and someone has
        to decide which model owns them — rather than two models disagreeing."""
        assert col not in Company.__table__.columns, (
            f"{col} now exists on Company as well as CompanyConfig; two models "
            "owning one fact is how the original bug became plausible"
        )


class TestClearDispatchQueriesTheRightModel:
    def _clear_dispatch_source(self) -> str:
        tree = ast.parse(ROUTER.read_text(errors="ignore"))
        fn = next(
            n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == "clear_daily_dispatch"
        )
        return ast.unparse(fn)

    def test_it_queries_company_config(self):
        src = self._clear_dispatch_source()
        i = src.index("discord_drivers_channel_id")
        window = src[max(0, i - 800): i]
        assert "CompanyConfig" in window, (
            "the Discord columns are read from a model that does not have them"
        )

    def test_the_name_is_importable_at_module_level(self):
        """A function-local import elsewhere in the file makes `python -c
        'import app.main'` pass while this call site raises NameError."""
        tree = ast.parse(ROUTER.read_text(errors="ignore"))
        names = set()
        for n in tree.body:
            if isinstance(n, ast.ImportFrom):
                names |= {a.asname or a.name for a in n.names}
        assert "CompanyConfig" in names, (
            "CompanyConfig is not imported at module level, so clear_dispatch "
            "raises NameError at runtime even though the module imports fine"
        )
