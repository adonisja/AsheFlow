"""GET /companies/my-info must reach the role that needs it.

The Dispatch Dashboard calls this on every load to render the timezone beside
the dispatch date. The endpoint was gated to management/admin, so every
DISPATCH user — the role that lives on that page — got a 403.

The frontend swallows the error, so nothing broke visibly. The only symptom was
a timezone label that never rendered for dispatch, on the page where the date
matters most, plus a 403 on every load hiding real errors in the console.

The response is `{name, timezone}` for the CALLER'S OWN company: not sensitive,
and company-scoped by construction.
"""
import inspect

from app.routers import companies
from app.services.constants import OVERSIGHT_ROLES


class TestTheGate:
    def test_dispatch_can_read_it(self):
        assert "dispatch" in companies.allow_oversight.allowed_roles

    def test_management_and_admin_keep_access(self):
        for r in ("management", "admin"):
            assert r in companies.allow_oversight.allowed_roles

    def test_it_uses_the_canonical_role_set(self):
        """A hand-written list is a second spelling of 'who oversees
        operations' — the notification fan-out already uses OVERSIGHT_ROLES."""
        assert set(companies.allow_oversight.allowed_roles) == set(OVERSIGHT_ROLES)

    def test_field_staff_still_cannot(self):
        """Widening the gate must not reach the whole company."""
        for r in ("walker", "driver", "trainee", "trainer", "captain", "driver_trainee"):
            assert r not in companies.allow_oversight.allowed_roles

    def test_the_endpoint_uses_it(self):
        src = inspect.getsource(companies.get_my_company_info)
        assert "Depends(allow_oversight)" in src
        assert "allow_management" not in src


class TestTheResponseStaysMinimal:
    def test_it_returns_only_name_and_timezone(self):
        """The gate is safe BECAUSE the payload is small. If this grows, the
        widened gate needs re-examining."""
        src = inspect.getsource(companies.get_my_company_info)
        assert 'return {"name": company.name, "timezone": company.timezone}' in src

    def test_it_is_scoped_to_the_callers_own_company(self):
        src = inspect.getsource(companies.get_my_company_info)
        assert "Company.id == caller.company_id" in src
