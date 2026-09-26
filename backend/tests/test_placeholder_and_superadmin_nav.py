"""Placeholders read as hints, and super admin gets the same nav as everyone.

Two UI defects found during the first-tenant walkthrough:

  * `DSPX1234` in the Amazon DSP Code field looked like a value somebody had
    already entered. It was a real placeholder -- but styled
    `text-muted-foreground`, the SAME token as real secondary text.
  * The super admin shell was one cramped row with no identity and no mobile
    treatment, against a two-tier tenant navbar with both.
"""
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
PALETTE = ROOT / "design" / "palette.json"
CSS = ROOT / "frontend" / "src" / "index.css"
TW = ROOT / "frontend" / "tailwind.config.js"
LAYOUT = ROOT / "frontend" / "src" / "components" / "layout" / "SuperAdminLayout.tsx"


def _rgb(h, s, l):
    import colorsys
    return colorsys.hls_to_rgb(h / 360, l / 100, s / 100)


def _lum(hsl):
    r, g, b = _rgb(*hsl)
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _ratio(a, b):
    hi, lo = sorted([_lum(a), _lum(b)], reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class TestThePlaceholderTokenIsReadableAndDistinct:
    """Two properties in tension: lighter than body text, still legible."""

    @pytest.fixture(scope="class")
    def palette(self):
        return json.loads(PALETTE.read_text())

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_it_exists_in_both_themes(self, palette, theme):
        assert "placeholder" in palette[theme], (
            f"{theme} has no placeholder token — placeholders fall back to "
            "mutedForeground, which is what made an empty field look filled"
        )

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_it_is_lighter_than_body_text(self, palette, theme):
        """If it matches mutedForeground it is not a hint, it is a value."""
        ph = palette[theme]["placeholder"]["hsl"]
        muted = palette[theme]["mutedForeground"]["hsl"]
        assert ph != muted, f"{theme} placeholder is identical to mutedForeground"
        card = palette[theme]["card"]["hsl"]
        assert _ratio(ph, card) < _ratio(muted, card), (
            f"{theme} placeholder is not visually lighter than body text"
        )

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_it_still_meets_wcag_aa(self, palette, theme):
        """A hint nobody can read is not a hint.

        This is why OPACITY was rejected: light mode's mutedForeground is only
        5.28:1 to begin with, so 0.75 alpha lands at 3.22:1.
        """
        ph = palette[theme]["placeholder"]["hsl"]
        card = palette[theme]["card"]["hsl"]
        r = _ratio(ph, card)
        assert r >= 4.5, f"{theme} placeholder is {r:.2f}:1 on card, below 4.5:1"

    @pytest.mark.parametrize("theme", ["light", "dark"])
    def test_it_is_checked_by_the_contrast_gate(self, palette, theme):
        """design/check_contrast.py fails CI on a regression — but only for
        tokens carrying a _check entry."""
        assert "_check" in palette[theme]["placeholder"], (
            "the placeholder token is not contrast-checked, so a later palette "
            "edit could drop it below AA silently"
        )


class TestEveryFieldPicksItUp:
    def test_the_base_rule_targets_input_and_textarea(self):
        css = CSS.read_text()
        assert "input::placeholder" in css and "textarea::placeholder" in css, (
            "no base placeholder rule — fields that never used .input-field "
            "keep the old colour"
        )
        assert "hsl(var(--placeholder))" in css

    def test_no_inline_override_survives(self):
        """An inline `placeholder:text-muted-foreground` beats the base rule,
        which is how six files kept the old look after .input-field was fixed.
        """
        hits = [
            f.relative_to(ROOT).as_posix()
            for f in (ROOT / "frontend" / "src").rglob("*.tsx")
            if "placeholder:text-" in f.read_text()
        ]
        assert not hits, f"inline placeholder colour overrides the base rule: {hits}"

    def test_tailwind_exposes_the_token(self):
        assert "placeholder: 'hsl(var(--placeholder))'" in TW.read_text()

    def test_mobile_uses_it_too(self):
        """The palette generates both platforms; they drifted before, which is
        why design/palette.json exists."""
        stale = [
            f.relative_to(ROOT).as_posix()
            for f in (ROOT / "mobile" / "src").rglob("*.tsx")
            if "placeholderTextColor={c.mutedForeground}" in f.read_text()
        ]
        assert not stale, f"mobile placeholders still use mutedForeground: {stale}"


class TestTheSuperAdminNavMatchesTheTenantOne:
    def test_it_has_two_tiers(self):
        """One row made the links compete for width with a wordmark that never
        changes."""
        src = LAYOUT.read_text()
        assert "function TitleBar" in src, "no brand/identity row"
        assert "<nav" in src, "no separate nav strip"

    def test_it_shows_who_is_signed_in(self):
        """This surface can purge a tenant and showed nothing about the user."""
        src = LAYOUT.read_text()
        assert "Avatar" in src
        assert "displayName" in src or "username" in src

    def test_it_has_a_mobile_menu(self):
        """There was no mobile treatment at all — the links simply overflowed."""
        src = LAYOUT.read_text()
        assert "mobileOpen" in src, "no mobile menu state"
        assert "md:hidden" in src, "no mobile-only control"

    def test_it_keeps_its_own_identity(self):
        """Same bones, distinct skin: super admin spans every tenant and must
        not be mistaken for one of them."""
        src = LAYOUT.read_text()
        assert "violet" in src, "the super admin surface lost its violet identity"

    def test_it_still_omits_the_tenant_scoped_widgets(self):
        """ADR-396. NotificationBanner, CommandPalette and FeedbackModal all
        resolve the caller through an Employee row a super admin does not have.
        """
        src = LAYOUT.read_text()
        # IMPORTS, not any mention: the ADR-396 comment in this file names all
        # three to explain why they are absent, and a substring check flags the
        # explanation as the violation.
        imports = "\n".join(l for l in src.splitlines() if l.startswith("import"))
        for widget in ("NotificationBanner", "CommandPalette", "FeedbackModal"):
            assert widget not in imports, (
                f"{widget} resolves an Employee row super admin does not have "
                "(ADR-396)"
            )
