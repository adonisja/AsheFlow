"""Every layout shell renders the MFA banner (ADR-396).

WHY THIS EXISTS
`SuperAdminLayout` is a separate shell from the `Layout` every other role uses,
and it correctly omits the tenant-scoped pieces: NotificationBanner,
CommandPalette and FeedbackModal all resolve the caller through an Employee row
that a super admin does not have (ADR-274 D13/D14), so they would 403.

MfaNudgeBanner is not one of those. It reads only `mfaStatus` from AuthContext.
It was dropped anyway, because nobody separated "does not apply to a super admin"
from "applies to every human with an account".

The consequence is the sharp bit: ADR-377 puts super_admin on the PRIVILEGED tier
with NO grace period, so the one role that must enrol before first use was the one
role never told to.

The one-line mount is not what this test protects. A THIRD shell will be written
eventually and will drop the banner for exactly the same reason. This enumerates
the shells, so that author either mounts it or has to edit a test that explains
why.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
LAYOUT_DIR = REPO / "frontend/src/components/layout"

# A "shell" renders <Outlet /> -- it wraps routed pages rather than being one.
SHELLS = sorted(
    p for p in LAYOUT_DIR.glob("*.tsx")
    if "<Outlet" in p.read_text()
)


def test_the_shells_were_actually_found():
    """If the glob stops matching, every assertion below passes vacuously."""
    assert len(SHELLS) >= 2, (
        f"expected at least Layout and SuperAdminLayout, found {[p.name for p in SHELLS]}"
    )
    names = {p.name for p in SHELLS}
    assert "Layout.tsx" in names
    assert "SuperAdminLayout.tsx" in names


@pytest.mark.parametrize("shell", SHELLS, ids=lambda p: p.name)
def test_every_shell_renders_the_mfa_banner(shell: Path):
    src = shell.read_text()
    assert "<MfaNudgeBanner" in src, (
        f"{shell.name} does not render MfaNudgeBanner. It reads only `mfaStatus` "
        "from AuthContext -- no Employee row, no company -- so it works in every "
        "shell. ADR-377 puts super_admin on the privileged tier with NO grace "
        "period, so a shell without it leaves the highest-privilege role with no "
        "enrolment prompt at all (ADR-396)."
    )


@pytest.mark.parametrize("shell", SHELLS, ids=lambda p: p.name)
def test_the_banner_is_imported_not_just_named(shell: Path):
    """A JSX tag with no import is a build error, but this also catches a
    half-applied edit that mounts the tag and drops the import."""
    src = shell.read_text()
    assert re.search(r"import\s+MfaNudgeBanner\s+from", src), (
        f"{shell.name} renders MfaNudgeBanner without importing it"
    )


class TestTheTenantOmissionsAreDeliberate:
    """Recorded so this file does not read as "SuperAdminLayout is missing
    things" and invite someone to add components that would 403."""

    def test_superadmin_shell_omits_the_employee_scoped_pieces(self):
        src = (LAYOUT_DIR / "SuperAdminLayout.tsx").read_text()
        for component in ("NotificationBanner", "CommandPalette", "FeedbackModal"):
            assert f"<{component}" not in src, (
                f"{component} resolves the caller through get_caller_employee, and "
                "a super admin has no Employee row by design (ADR-274 D13/D14). "
                "Mounting it produces a surface that 403s."
            )

    def test_the_main_layout_still_has_them(self):
        """The other half: if these vanish from Layout, every OTHER role loses
        them, and the test above would still pass."""
        src = (LAYOUT_DIR / "Layout.tsx").read_text()
        for component in ("NotificationBanner", "CommandPalette", "FeedbackModal"):
            assert f"<{component}" in src, f"{component} disappeared from Layout"
