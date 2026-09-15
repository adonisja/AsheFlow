"""ADR-398 D3 — the account field tabs are keyed on DATA **or** FIELD ROLE.

The disjunction is the whole decision, so these tests pin both halves and the
case that motivated it. A source-text test, because the gate is client-side
presentation in Account.tsx with no endpoint to exercise.

Written against a specific failure mode: someone "simplifies" this to a role
check (breaking the promoted manager) or to a data check (breaking the walker
on day one, whose tab is where their first numbers appear).
"""
from pathlib import Path

import pytest

ACCOUNT = Path(__file__).resolve().parents[3] / "frontend" / "src" / "pages" / "Account.tsx"


@pytest.fixture(scope="module")
def src() -> str:
    assert ACCOUNT.exists(), f"Account.tsx not found at {ACCOUNT}"
    text = ACCOUNT.read_text()
    # Vacuity guard: if the file stops containing the tabs at all, every
    # assertion below would pass trivially against an empty gate.
    assert "'scorecard'" in text, "Account.tsx no longer defines the scorecard tab"
    return text


class TestFieldTabsGate:
    def test_gate_is_a_disjunction_not_a_role_check(self, src: str) -> None:
        """Role alone hides a promoted manager's own history from them."""
        assert "isFieldRole || hasFieldData === true" in src, (
            "the field-tab gate is no longer `isFieldRole || hasFieldData` — if "
            "it was narrowed to a role check, a manager promoted out of the "
            "field loses the stats they earned (ADR-398 D3)"
        )

    def test_field_roles_do_not_wait_on_the_probe(self, src: str) -> None:
        """A walker on day one has no stats; the role must settle it alone."""
        assert "if (isFieldRole) return;" in src, (
            "the probe no longer short-circuits for field roles — a walker with "
            "no completed routes would lose the tab where their first numbers "
            "appear (ADR-398 D3)"
        )

    def test_data_signal_is_years_not_delivered(self, src: str) -> None:
        """`delivered` is null in workforce mode until a Flex scan (ADR-305).

        Keying on it would hide the tab from a worker whose routes ran but were
        never scanned — real work, reported as none. Most tenants run workforce
        mode, so this is the common path, not the edge case.
        """
        assert "r.data.years?.length" in src, (
            "the field-data probe no longer keys on `years` — keying on "
            "`lifetime.delivered` breaks workforce mode, where it is null "
            "until a route is Flex-scanned (ADR-305)"
        )

    def test_tabs_render_from_the_filtered_list(self, src: str) -> None:
        assert "visibleTabs.map" in src, (
            "the tab bar renders from TABS again, so the filter is dead code "
            "and every role sees every tab (ADR-398 D3)"
        )

    def test_settings_is_never_filtered_out(self, src: str) -> None:
        assert "t.key === 'settings' || showFieldTabs" in src, (
            "Settings is no longer unconditionally visible — a career manager "
            "would be left with an empty tab bar (ADR-398 D3)"
        )

    def test_hidden_tab_cannot_strand_the_page(self, src: str) -> None:
        """The gate resolves after mount, so a selected tab can vanish."""
        assert "if (!showFieldTabs && tab !== 'settings') setTab('settings');" in src, (
            "the fallback that returns a stranded user to Settings is gone — "
            "when the probe resolves false on a tab that is already selected, "
            "the page renders nothing (ADR-398 D3)"
        )
