"""Self-service Discord linking is VERIFIED, not a free field edit (ADR-270).

WHY THIS IS NOT A PLAIN PATCH
`employees.discord_id` is the bot's DM address AND the third step of the auth
lookup chain (cognito_sub -> username -> discord_id, api/deps.py). If a user
could set it freely they could point their record at a colleague's Discord and
redirect that person's dispatch DMs. So it mirrors the email-change flow: send
a code to the claimed account, prove receipt, then write.

WHAT THESE TESTS PIN
  1. the code is bound to the ID it was issued for  <- the real attack
  2. uniqueness is enforced at BOTH request and confirm time
  3. a wrong or missing code writes nothing
  4. the write target is always the caller

(1) is the one worth stating plainly. Checking only the code would let someone
request a code for a Discord account they DO control, then confirm it against
a DIFFERENT id — passing verification for an account they never proved. The
stored value is `"{discord_id}:{code}"` precisely so both must match.

These are source-and-unit level: the endpoints need Redis and a live bot, so
an HTTP round trip is not runnable in every environment. What must not regress
is the binding, the uniqueness guard and the gate — all visible without a
server.
"""
import inspect

import pytest

from app.routers import employees as emp_router
from app.schemas.employee import _validate_discord_id


class TestSnowflakeValidation:
    """ADR-083: numeric snowflake, 17-20 digits. Reused, not re-implemented."""

    def test_accepts_a_real_snowflake(self):
        assert _validate_discord_id("219476523456789012") == "219476523456789012"

    @pytest.mark.parametrize("bad", [
        "johndoe#1234",          # the pre-2023 format ADR-083 migrated away from
        "discord_seed_1",        # placeholder junk that used to live in this column
        "12345",                 # too short
        "2194765234567890123456",  # too long
        "21947652345678901a",    # not pure digits
    ])
    def test_rejects_everything_else(self, bad):
        with pytest.raises(ValueError):
            _validate_discord_id(bad)

    def test_request_schema_requires_a_value(self):
        """Empty coerces to None in the shared validator, which would write a
        null discord_id. The link endpoint must reject it instead."""
        with pytest.raises(Exception):
            emp_router._DiscordLinkRequest(discord_id="")


class TestCodeIsBoundToTheId:
    def test_stored_value_carries_the_id_not_just_the_code(self):
        """THE ATTACK THIS BLOCKS. If only the code were stored, a caller could
        request a code for their own Discord, then confirm it against a
        colleague's id and pass verification for an account they never proved."""
        src = inspect.getsource(emp_router.request_discord_link)
        assert 'f"{discord_id}:{code}"' in src, (
            "the code is no longer stored with the id it was issued for"
        )

    def test_confirm_checks_both_id_and_code(self):
        src = inspect.getsource(emp_router.confirm_discord_link)
        assert "stored_id != payload.discord_id" in src, (
            "confirm no longer verifies the id the code was issued for"
        )
        assert "compare_digest" in src, "code comparison is not constant-time"

    def test_confirm_clears_the_code_after_use(self):
        """A code that survives its use is a replay window."""
        src = inspect.getsource(emp_router.confirm_discord_link)
        assert "r.delete(_discord_code_key(caller.id))" in src


class TestUniqueness:
    def test_request_rejects_an_already_linked_id(self):
        src = inspect.getsource(emp_router.request_discord_link)
        assert "Employee.discord_id == discord_id" in src
        assert "status_code=409" in src

    def test_confirm_rechecks_at_write_time(self):
        """The 10-minute window is long enough for someone else to link the
        same id, so the request-time check alone is not sufficient."""
        src = inspect.getsource(emp_router.confirm_discord_link)
        assert "Employee.discord_id == payload.discord_id" in src
        assert "status_code=409" in src

    def test_both_checks_are_company_scoped(self):
        """UNIQUE is (company_id, discord_id) — an unscoped check would leak
        the existence of a link in another tenant (ADR-115 D1)."""
        for fn in (emp_router.request_discord_link, emp_router.confirm_discord_link):
            src = inspect.getsource(fn)
            assert "Employee.company_id == caller.company_id" in src


class TestWriteTarget:
    def test_the_write_target_is_always_the_caller(self):
        """Neither endpoint takes an employee id, so there is nothing a caller
        could pass to link someone else's account."""
        for fn in (emp_router.request_discord_link, emp_router.confirm_discord_link):
            params = inspect.signature(fn).parameters
            assert "employee_id" not in params
        src = inspect.getsource(emp_router.confirm_discord_link)
        assert "caller.discord_id = payload.discord_id" in src

    def test_the_link_is_audited(self):
        """Changing a DM target is exactly what an audit trail is for."""
        src = inspect.getsource(emp_router.confirm_discord_link)
        assert "write_audit" in src
        assert "employee.discord_linked" in src
        # flush -> audit -> commit, per CLAUDE.md
        assert src.index("db.flush()") < src.index("write_audit")
        assert src.index("write_audit") < src.index("db.commit()")


class TestGates:
    def test_request_carries_a_role_guard(self):
        """Mirrors email/request-change. The repo's own test_guard_coverage
        caught this missing on first write — every mutation endpoint needs a
        RoleChecker or a reviewed ownership entry."""
        src = inspect.getsource(emp_router.request_discord_link)
        assert "RoleChecker" in src

    def test_confirm_is_on_the_reviewed_ownership_allowlist(self):
        """confirm-link has no RoleChecker BY DESIGN: holding the DM code is
        the authorisation, exactly as the emailed code is for
        email/confirm-change. That exemption must stay reviewed rather than
        implicit, so it lives on the allowlist."""
        from tests.routers.test_guard_coverage import OWNERSHIP_ENFORCED
        assert "POST /employees/me/discord/confirm-link" in OWNERSHIP_ENFORCED


class TestRateLimit:
    def test_requests_are_rate_limited(self):
        """A code request DMs a third party, so an unbounded endpoint is a spam
        vector against arbitrary Discord users."""
        src = inspect.getsource(emp_router.request_discord_link)
        assert "_DISCORD_MAX_ATTEMPTS" in src
        assert "status_code=429" in src

    def test_codes_expire(self):
        src = inspect.getsource(emp_router.request_discord_link)
        assert "setex" in src, "the code has no TTL — it would live forever"
