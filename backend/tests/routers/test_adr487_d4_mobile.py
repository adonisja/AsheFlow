"""The registry reaches mobile too, and the two surfaces agree (ADR-487 D4, mobile half).

WHY THIS MATTERED ENOUGH TO DO AS ITS OWN PASS
==============================================

D4's contract shipped to BOTH surfaces and only web read it. Measured before this
change: `grep -c "severity\\|n.tone\\|channels"` in NotificationsScreen.tsx
returned **0**. Mobile instead carried two hardcoded tables —

    TYPE_META    52 entries of {label, icon}
    typeColor    20 string tests ending in `type.includes('approved')`

— covering 52 of the registry's 86 types, with the other 34 falling to a default
by accident rather than decision. And they DISAGREED with web for the same row
from the same endpoint: `incident_critical` was `c.danger` on mobile and a
warning tint on web.

That is the drift ADR-269 and ADR-271 §T learned the hard way, and ADR-275 D4 set
the rule against: a rule that decides what a walker sees on a phone and what a
dispatcher sees on a desktop must not exist in two differently-worded copies.

WHY THE TONE MAPS ARE *NOT* PAIRED COPIES
=========================================

`classify.ts` is byte-identical across surfaces and `check_shared_copies`
enforces that. `tone.ts` is deliberately NOT: web returns Tailwind class
strings, mobile returns colour values off the active React Native theme. "Both
surfaces need this concept" is not the same claim as "both surfaces need these
bytes" — and that difference is the whole reason the server sends a semantic role
rather than a colour.
"""
from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
SCREEN = ROOT / "mobile/src/screens/Notifications/NotificationsScreen.tsx"
TICKER = ROOT / "mobile/src/components/notifications/NotificationTicker.tsx"
TONE = ROOT / "mobile/src/components/notifications/tone.ts"
HOOK = ROOT / "mobile/src/hooks/useReducedMotionState.ts"
HOME = ROOT / "mobile/src/screens/Home/HomeScreen.tsx"
WEB_TONE = ROOT / "frontend/src/components/notifications/tone.ts"


def _code_only(src: str) -> str:
    """Comments and block comments stripped.

    Every absence assertion here needs it: these files EXPLAIN the tables they
    deleted, quoting `TYPE_META` and `type.includes('approved')` by name. The
    thirteenth occurrence of prose-not-code in this body of work, anticipated
    this time rather than discovered.
    """
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    return "\n".join(l.split("//", 1)[0] for l in src.splitlines())


class TestMobileConsumesTheContract:
    @pytest.mark.parametrize("field", ["severity", "label", "tone", "icon", "channels"])
    def test_the_type_declares_the_field(self, field):
        """`types.ts` is hand-maintained on this surface too — there is no
        codegen — so a field the server sends and mobile does not declare is
        invisible to TypeScript."""
        src = SCREEN.read_text()
        assert re.search(rf"\b{field}\??:", src), (
            f"the mobile Notification type does not declare {field}"
        )

    def test_the_render_reads_the_server_tone(self):
        src = _code_only(SCREEN.read_text())
        assert "toneStyle(item.tone" in src, (
            "the card still picks its colour without consulting the server"
        )

    def test_the_render_reads_the_server_label_and_icon(self):
        src = _code_only(SCREEN.read_text())
        assert "labelFor(item)" in src
        assert "iconFor(item)" in src


class TestTheHardcodedTablesAreGone:
    def test_type_meta_is_deleted(self):
        """52 entries covering 52 of 86 types."""
        assert "TYPE_META" not in _code_only(SCREEN.read_text()), (
            "the 52-entry label/icon table is back; the server sends both"
        )

    def test_type_color_is_deleted(self):
        assert "function typeColor" not in _code_only(SCREEN.read_text())

    def test_no_string_guessing_remains(self):
        """The chain that put `incident_critical` (URGENT) in the same bucket as
        a routine notice."""
        src = _code_only(SCREEN.read_text())
        for guess in ("includes('approved')", "includes('rejected')",
                      "includes('denied')", "includes('failed')",
                      "includes('schedule')", "includes('anchor_point')"):
            assert guess not in src, f"mobile still guesses tone from the type: {guess}"

    def test_a_fallback_survives_for_unregistered_types(self):
        """Three types reaching this screen are PlatformAlert vocabulary with no
        registry entry (ADR-324 D2), and a pre-ADR-487 row has no server fields
        at all. Both must still render something."""
        src = _code_only(SCREEN.read_text())
        assert "replace(/_/g" in src, "no title-cased fallback for an unlabelled type"
        assert "'🔔'" in src, "no fallback icon"


class TestTheToneMapsAgreeOnNAMESAndDifferOnVALUES:
    """The distinction `check_shared_copies` now records explicitly."""

    def test_both_surfaces_define_the_same_five_tones(self):
        web = _code_only(WEB_TONE.read_text())
        mob = _code_only(TONE.read_text())
        for tone in ("neutral", "good", "warn", "bad", "active"):
            assert tone in web, f"web lost the {tone} tone"
            assert tone in mob, f"mobile lost the {tone} tone"

    def test_mobile_returns_theme_values_not_css_classes(self):
        mob = _code_only(TONE.read_text())
        assert "c.danger" in mob, "mobile must map to theme values"
        assert "bg-danger" not in mob, (
            "a Tailwind class on this surface would render nothing — RN has no "
            "class names"
        )

    def test_web_returns_css_classes_not_theme_values(self):
        web = _code_only(WEB_TONE.read_text())
        assert "bg-danger" in web
        assert "c.danger" not in web, (
            "a theme object value in a className would render nothing"
        )

    def test_neither_sends_a_colour_back_to_the_server(self):
        """The server deliberately sends no colour, so neither map may be the
        authority on one: a hex from a Python file would land in one of the two
        themes unreadable."""
        import sys
        sys.path.insert(0, str(ROOT / "backend"))
        from app.schemas.notification import NotificationResponse

        assert "colour" not in NotificationResponse.model_fields
        assert "color" not in NotificationResponse.model_fields


class TestTheUrgentRegionIsOutsideTheScroll:
    """D4a on this surface. A FlatList scrolls its contents exactly as the web
    cap does, so "render it above" means a SIBLING of the list — not its
    ListHeaderComponent, which scrolls away with the rows."""

    def test_the_urgent_region_is_not_the_list_header(self):
        src = _code_only(SCREEN.read_text())
        assert "ListHeaderComponent" not in src, (
            "the URGENT region is the list header, so it scrolls away — D4a "
            "requires it outside the scrolling element"
        )

    def test_the_region_renders_before_the_list(self):
        src = _code_only(SCREEN.read_text())
        region = src.index("urgent.length > 0")
        flatlist = src.index("<FlatList")
        assert region < flatlist, "the URGENT region renders after the list"

    def test_the_list_is_fed_the_inbox_not_everything(self):
        """If the FlatList still got `notifications`, every URGENT row would
        render twice — once pinned and once in the scroll."""
        src = _code_only(SCREEN.read_text())
        assert "data={inbox}" in src, (
            "the list renders the full set, so URGENT and ticker rows appear twice"
        )

    def test_the_split_reads_the_server_not_a_type_list(self):
        """Anchored on each BINDING, not on the file.

        `isTicker(n.channels)` appears TWICE — once for `ticker` and once for
        `inbox` — so asserting it exists somewhere passed a probe that rewrote
        the ticker line to filter on severity. Fourth occurrence of the
        duplicate-needle gap in this body of work, and the second time this
        exact pair of lines caused it (web had it first).

        `src.count(needle)` is the one-line check that would have caught all
        four before the assertion was written.
        """
        src = _code_only(SCREEN.read_text())

        def binding(name: str) -> str:
            line = next(
                (l for l in src.splitlines() if f"const {name}" in l and "=" in l),
                None,
            )
            assert line, f"no `const {name} = ...` binding found"
            return line

        assert "isUrgent(" in binding("urgent")

        # BOTH halves of the split, not just the ticker. A probe that rewrote
        # the `inbox` line instead went undetected by the first fix: pinning
        # one binding leaves its complement free to disagree, and the two
        # together decide where every row lands. If `ticker` reads channels and
        # `inbox` reads severity, a row can be in neither or in both.
        for name in ("ticker", "inbox"):
            line = binding(name)
            assert "isTicker(" in line, (
                f"the {name} split must read the server's channel list; this "
                f"line derives it some other way: {line.strip()}"
            )
            assert "severity" not in line, (
                f"severity is not the ticker test — 52 types are INFO and only "
                f"20 carry 'ticker': {line.strip()}"
            )

    def test_urgent_has_no_dismiss_affordance(self):
        """Dismissable only by acting (D4a). A dismissed-but-unhandled injury
        alert is the warningless wall ADR-381 described."""
        src = SCREEN.read_text()
        start = src.index("urgent.length > 0")
        end = src.index("<FlatList", start)
        region = src[start:end]
        assert "onDismiss" not in region
        assert "markRead" not in region, "the URGENT card can be dismissed unacted"


class TestTheTicker:
    def test_it_consults_reduced_motion(self):
        assert "useReducedMotionState" in _code_only(TICKER.read_text())

    def test_the_reduced_path_is_expandable_and_counts(self):
        """Not a degraded fallback — the better-detail control from D4b's
        table."""
        src = TICKER.read_text()
        reduced = src[src.index("if (reduced)"):src.index("/* ---------------- motion")]
        assert "accessibilityState={{ expanded }}" in reduced
        assert "items.length - 1" in reduced, "no count of the remaining items"
        assert "newest.message" in reduced

    def test_the_animation_runs_off_the_js_thread(self):
        """CLAUDE.md's rule, and it matters here specifically: the strip sits
        above a FlatList, so JS-thread motion would stutter on every scroll."""
        assert "useNativeDriver: true" in _code_only(TICKER.read_text())

    def test_it_translates_by_the_measured_width(self):
        """Web can use -50% because CSS knows the element width. RN must
        measure, which is why the strip renders, measures onLayout, THEN loops."""
        src = _code_only(TICKER.read_text())
        assert "onLayout" in src
        assert "toValue: -stripWidth" in src, (
            "translating by a guessed distance leaves a visible seam or a jump"
        )

    def test_the_duplicate_is_hidden_from_the_screen_reader(self):
        src = TICKER.read_text()
        assert src.count("{line}") >= 2, "the line is not duplicated for the loop"
        assert "accessibilityElementsHidden" in src
        assert 'importantForAccessibility="no-hide-descendants"' in src

    def test_the_live_region_is_polite(self):
        """These are events with no consequence for the reader, so interrupting
        a screen reader mid-sentence would be exactly wrong.

        `_code_only`, because the component's own comment explains where
        assertive DOES belong — and the first version of this test asserted
        `"assertive" not in src` against the raw text and failed on that
        sentence. The helper was already defined at the top of this file and I
        did not use it here: the thirteenth prose-not-code match in this body of
        work, and the first where the remedy was already sitting in the same
        file."""
        src = _code_only(TICKER.read_text())
        assert 'accessibilityLiveRegion="polite"' in src
        assert "assertive" not in src

    def test_the_touch_target_meets_the_floor(self):
        """WCAG 2.5.5, the floor `primitives.MIN_TARGET` sets. The web row is
        shorter because a cursor is not a thumb."""
        src = _code_only(TICKER.read_text())
        assert "minHeight: 44" in src


class TestTheReducedMotionHookIsSubscribedState:
    def test_it_is_state_not_a_ref(self):
        """The ticker renders a DIFFERENT SUBTREE when motion is reduced, so a
        ref cannot drive it: nothing re-renders when the setting resolves, so
        the first paint would be the animated version forever."""
        src = _code_only(HOOK.read_text())
        assert "useState" in src
        assert "useRef" not in src

    def test_it_subscribes_rather_than_reading_once(self):
        """D4b names this: the setting can change while the app is open, and a
        dispatcher who turns reduce-motion ON mid-shift would keep the scrolling
        until the next cold start."""
        src = _code_only(HOOK.read_text())
        assert "addEventListener" in src
        assert "reduceMotionChanged" in src
        assert "remove" in src, "the subscription is never torn down"

    def test_it_defaults_to_animating(self):
        """Defaulting to "reduce" would disable motion for the first frame on
        every launch, and for anyone whose platform does not answer."""
        src = _code_only(HOOK.read_text())
        assert "useState(false)" in src

    def test_the_existing_ref_hook_is_left_alone(self):
        """Converting `primitives.useReduceMotion` to state would reintroduce
        the crash its own comment documents — "Rendered more hooks than during
        the previous render" in CompanyStandingCard — across three call sites
        that are correct as they are."""
        prim = (ROOT / "mobile/src/components/ui/primitives.tsx").read_text()
        assert "const reduce = useRef(false)" in prim, (
            "primitives.useReduceMotion was converted to state; its callers read "
            "it inside animation callbacks and that chain shifted the hook order"
        )


class TestTheHomeCardDistinguishesUrgentFromAwaitingAnswer:
    def test_it_has_a_separate_urgent_state(self):
        """Folding URGENT into needsResponse would label the card "needs your
        response" about an injury alert, which cannot be responded to."""
        src = _code_only(HOME.read_text())
        assert "needsUrgentAttention" in src
        assert "needsResponse" in src, "the existing state was replaced, not joined"

    def test_urgent_reads_the_server_severity(self):
        """A type list here would need editing every time the registry gains an
        URGENT type."""
        src = _code_only(HOME.read_text())
        assert "n.severity === 'urgent'" in src

    def test_urgent_is_not_gated_on_having_an_assignment(self):
        """The warning border IS gated on truckName, because "respond to your
        assignment" is meaningless with no assignment. An injury alert is worth
        seeing either way, so the urgent branch must NOT carry that gate.

        The first version asserted `"needsUrgentAttention ? c.danger" in src`,
        which a probe inserting `&& truckName` satisfied: the mutated line reads
        `needsUrgentAttention && truckName ? c.danger`, and the needle is a
        prefix of it. Asserting the absence of the gate is what actually tests
        the property.
        """
        src = _code_only(HOME.read_text())
        urgent_branches = [
            l.strip() for l in src.splitlines()
            if "needsUrgentAttention" in l and "?" in l
        ]
        assert urgent_branches, "no urgent styling branch found at all"

        for line in urgent_branches:
            cond = line.split("?", 1)[0]
            # The TERM containing needsUrgentAttention, not the whole condition.
            #
            # A first version checked the whole condition and failed on real,
            # correct code: `needsUrgentAttention || (needsResponse &&
            # truckName)` mentions truckName in service of the OTHER disjunct,
            # which is right — the warning border is gated on having an
            # assignment and the urgent one is not. Splitting on `||` is what
            # isolates the claim.
            urgent_term = next(
                (t for t in cond.split("||") if "needsUrgentAttention" in t), "",
            )
            assert "truckName" not in urgent_term, (
                f"the urgent branch itself is gated on having an assignment, so "
                f"an injury alert is invisible to anyone not dispatched: {line}"
            )

    def test_the_list_is_typed_rather_than_any(self):
        """`any[]` is why a typo in `n.severity` would have been silent: the
        field would read undefined forever and nothing would catch it."""
        src = _code_only(HOME.read_text())
        assert "const list: any[]" not in src, (
            "the notification list is `any[]`, so a misspelled field reads "
            "undefined with no error"
        )
        assert "severity?:" in src
