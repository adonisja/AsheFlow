"""URGENT sits OUTSIDE the scroll cap, and the ticker carries system events (ADR-487 D4).

WHY THIS READS THE FRONTEND FROM A BACKEND TEST
===============================================

Repo convention (ADR-485 D9, ADR-381): the claim being defended spans both
halves. This one more so than most — the server decides severity and the client
decides where severity renders, and a test living only on one side would pass
while the other moved.

WHY STRUCTURE, NOT SUBSTRING ORDER
==================================

D4a's requirement is that the URGENT region is NOT INSIDE the element carrying
`max-h-[40vh]`. The tempting assertion is source order:

    src.index('urgent.map') < src.index('max-h-[40vh]')      # WRONG

That passes when the URGENT block is nested inside the capped div but written
above the class attribute, and it passes when the capped div is moved below for
unrelated reasons. ADR-295's own test docstring records being bitten by exactly
this shape ("_run is *defined* above the Thread(...) line"), and then the test
beside it pinned a literal anyway.

So these tests count JSX nesting depth: the capped element's subtree is
delimited, and the URGENT marker must fall outside it.
"""
from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
BANNER = ROOT / "frontend/src/components/NotificationBanner.tsx"
TICKER = ROOT / "frontend/src/components/notifications/NotificationTicker.tsx"
TONE = ROOT / "frontend/src/components/notifications/tone.ts"
HOOK = ROOT / "frontend/src/hooks/useReducedMotion.ts"
CONTEXT = ROOT / "frontend/src/contexts/NotificationContext.tsx"
TW_CONFIG = ROOT / "frontend/tailwind.config.js"
HISTORY = ROOT / "frontend/src/pages/NotificationsHistory.tsx"
NAVBAR = ROOT / "frontend/src/components/layout/Navbar.tsx"


def _strip_comments(src: str) -> str:
    """Drop // and /* */ comments.

    Every absence assertion below needs this: these files EXPLAIN the thing they
    forbid (the tone map's docstring quotes `styleForType`'s guesses verbatim),
    and a naive `not in` matches the explanation. Ninth occurrence of this
    pattern in this body of work.
    """
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def _all_capped_spans(src: str) -> list[tuple[int, int]]:
    """Every `max-h-[40vh]` element's span, not just the first.

    One span is not enough: a change that adds a SECOND capped container is
    exactly the shape that slips past a first-occurrence check.
    """
    spans = []
    for m in re.finditer(r"max-h-\[40vh\]", src):
        spans.append(_span_of_element_at(src, m.start()))
    return spans


def _span_of_element_at(src: str, cap_at: int) -> tuple[int, int]:
    """Span of the <div> whose attributes contain the index `cap_at`."""
    start = src.rindex("<div", 0, cap_at)
    depth = 0
    i = start
    while i < len(src):
        if src.startswith("</div>", i):
            depth -= 1
            i += 6
            if depth == 0:
                return start, i
            continue
        if src.startswith("<div", i):
            depth += 1
            i += 4
            continue
        i += 1
    raise AssertionError("could not find the close of the capped element")


def _capped_subtree_span(src: str) -> tuple[int, int]:
    """Character span of the JSX element that carries `max-h-[40vh]`.

    Walks forward from the cap counting < and > at tag level, tracking depth,
    and returns where that element closes. Crude relative to a real JSX parser
    and sufficient for one question: is a given marker inside this element?
    """
    cap = src.index("max-h-[40vh]")
    # back up to the opening `<div` of the element that carries the class
    start = src.rindex("<div", 0, cap)

    depth = 0
    i = start
    while i < len(src):
        if src.startswith("</div>", i):
            depth -= 1
            i += 6
            if depth == 0:
                return start, i
            continue
        if src.startswith("<div", i):
            # a self-closing div would not nest, but none exist here
            depth += 1
            i += 4
            continue
        i += 1
    raise AssertionError("could not find the close of the capped element")


class TestTheUrgentRegionIsOutsideTheCap:
    """D4a. The cap works by SCROLLING its contents, so anything inside it can
    be scrolled past and left unseen — acceptable for an announcement, not for
    an injury."""

    def test_the_cap_still_exists(self):
        """The failure mode of this change: 'fixing' the structure by deleting
        the cap, which is what keeps page content visible (ADR-275 D3)."""
        assert "max-h-[40vh]" in BANNER.read_text()

    def test_no_urgent_render_is_nested_inside_any_capped_element(self):
        """EVERY occurrence against EVERY cap, not the first against the first.

        The first version compared `src.index("urgent.map")` to one span, and a
        probe that ADDED a second capped region holding its own `urgent.map`
        went undetected: the first occurrence was still the original region
        above the cap, and the first cap was still the real one. Checking only
        the first of each is how a duplicate render escapes.
        """
        src = BANNER.read_text()
        spans = _all_capped_spans(src)
        assert spans, "no max-h-[40vh] element found at all"

        renders = [m.start() for m in re.finditer(r"urgent\.map", src)]
        assert renders, "the URGENT region is not rendered anywhere"

        for at in renders:
            for start, end in spans:
                assert not (start < at < end), (
                    f"an URGENT render at char {at} is INSIDE a max-h-[40vh] "
                    f"element ({start}..{end}), so an injury alert can be "
                    f"scrolled past — D4a requires it above the cap"
                )

    def test_the_outer_wrapper_is_uncapped(self):
        """The banner's own root must not carry the cap, or moving the region
        inside it achieves nothing."""
        src = BANNER.read_text()
        root = src.index("<div className=\"w-full space-y-2 animate-slide-up")
        root_attrs = src[root:src.index(">", root)]
        assert "max-h-" not in root_attrs, (
            "the outer wrapper is capped, so the URGENT region is capped too"
        )

    def test_the_news_group_is_still_inside_the_cap(self):
        """Half-fix check: hoisting everything out of the cap would make the cap
        decorative and let a multi-truck day push content off screen.

        `<NotificationTicker`, with the angle bracket: the bare name also
        appears in the import on line 8, which is at character 442 and
        therefore "outside the cap" for trivially uninteresting reasons. The
        first version of this test failed on exactly that and the code was
        fine — a reminder that a substring is not a reference.
        """
        src = BANNER.read_text()
        start, end = _capped_subtree_span(src)
        for marker in ("news.length === 1", "<NotificationTicker"):
            at = src.index(marker)
            assert start < at < end, f"{marker} escaped the scroll region"


class TestUrgentCannotBeDismissedUnacted:
    def test_urgent_is_excluded_from_bulk_dismiss(self):
        """ADR-275's note — 'dismissing an unanswered assignment is not the same
        as clearing an announcement' — applies here with more force."""
        src = _strip_comments(BANNER.read_text())
        block = src[src.index("const dismissAll"):src.index("const dismissTicker")]
        assert "urgent" not in block, "dismissAll can clear an URGENT alert"
        assert "ticker" in block and "news" in block

    def test_bulk_dismiss_does_not_call_markAllRead(self):
        """markAllRead only spares actionable dispatch_assignments server-side,
        so a bulk call would clear an injury alert in the database."""
        src = _strip_comments(BANNER.read_text())
        block = src[src.index("const dismissAll"):src.index("const dismissTicker")]
        assert "markAllRead" not in block, (
            "markAllRead spares only dispatch_assignment, so it would mark an "
            "URGENT notification read server-side"
        )

    def test_the_urgent_card_has_no_dismiss_button(self):
        """Dismissable only by ACTING. A dismissed-but-unhandled injury alert is
        the warningless wall ADR-381 described."""
        src = BANNER.read_text()
        start = src.index("{urgent.length > 0 &&")
        end = src.index("HEIGHT CAP", start)
        region = src[start:end]
        assert "onDismiss" not in region and "<X " not in region, (
            "the URGENT card offers a dismiss affordance"
        )

    def test_the_urgent_card_carries_an_action_link(self):
        src = BANNER.read_text()
        start = src.index("{urgent.length > 0 &&")
        end = src.index("HEIGHT CAP", start)
        assert "urgentDestination" in src[start:end]

    def test_every_urgent_type_has_a_real_route(self):
        """A link to an invented path is ADR-381 in its purest form: the feature
        ships, the type is exported, nothing is reachable."""
        import sys
        sys.path.insert(0, str(ROOT / "backend"))
        from app.services.notification_spec import SPEC, Severity

        banner = BANNER.read_text()
        table = banner[banner.index("const URGENT_ROUTES"):banner.index("function urgentDestination")]
        app_routes = (ROOT / "frontend/src/App.tsx").read_text()

        urgent_types = [t for t, s in SPEC.items() if s.severity is Severity.URGENT]
        assert urgent_types, "no URGENT types in the registry — fixture assumption changed"

        for t in urgent_types:
            assert t in table, f"URGENT type {t} has no route entry (falls back to /notifications)"

        for path in re.findall(r"to: '([^']+)'", table):
            assert f'path="{path}"' in app_routes, f"URGENT link targets {path}, which App.tsx does not define"


class TestTheTickerRoutesBySubjectNotSeverity:
    """52 types are INFO and only 20 carry TICKER. `pto_approved` is INFO and
    must not scroll past: it is a decision about the reader's own time off."""

    def test_the_banner_splits_on_channels_not_severity(self):
        """The ASSIGNMENT to `ticker`, not merely the presence of the string.

        `isTicker(n.channels)` appears twice — once for `ticker` and once for
        `news` — so asserting it exists somewhere passed even when the ticker
        line itself was rewritten to filter on severity. Anchor on the binding.
        """
        src = _strip_comments(BANNER.read_text())
        line = next(
            (l for l in src.splitlines() if "const ticker" in l and "=" in l),
            None,
        )
        assert line, "no `const ticker = ...` binding found"
        assert "isTicker(" in line, (
            f"the ticker split must read the server's channel list; this line "
            f"derives it some other way and would put pto_approved (INFO, "
            f"about the reader) into the ticker: {line.strip()}"
        )
        assert "severity" not in line, (
            f"severity is not the ticker test — 52 types are INFO and only 20 "
            f"carry 'ticker': {line.strip()}"
        )

    def test_isTicker_reads_the_channel_list(self):
        assert "includes('ticker')" in TONE.read_text()

    def test_the_context_types_channels(self):
        """types.ts is hand-maintained — there is no codegen — so a field the
        server sends and the client does not type is invisible to TS."""
        src = CONTEXT.read_text()
        assert "channels: string[]" in src
        for f in ("severity:", "label:", "tone:", "icon:"):
            assert f in src, f"the Notification interface is missing {f}"


class TestTheReducedMotionPathIsTheInformativeOne:
    """With motion reduced the ticker renders as the collapsed row it replaced —
    a static strip with a count and the newest item, expandable in place. Not a
    degraded fallback: the better-detail control."""

    def test_the_ticker_consults_reduced_motion(self):
        assert "useReducedMotion" in TICKER.read_text()

    def test_the_reduced_path_is_expandable(self):
        src = TICKER.read_text()
        reduced = src[src.index("if (reduced)"):src.index("/* ---------------- motion")]
        assert "aria-expanded" in reduced
        assert "setExpanded" in reduced

    def test_the_reduced_path_shows_a_count_and_the_newest_item(self):
        src = TICKER.read_text()
        reduced = src[src.index("if (reduced)"):src.index("/* ---------------- motion")]
        assert "newest.message" in reduced
        assert "items.length - 1" in reduced, "no count of the remaining items"

    def test_the_hook_subscribes_rather_than_reading_once(self):
        """The bug D4b names explicitly: a dispatcher who turns reduced motion ON
        mid-shift — plausibly because the ticker is bothering them — would keep
        the scrolling until the next full reload."""
        src = _strip_comments(HOOK.read_text())
        assert "addEventListener" in src or "addListener" in src, (
            "the hook reads the media query once; the setting can change while "
            "the page is open"
        )
        assert "removeEventListener" in src or "removeListener" in src, (
            "the subscription is never torn down"
        )
        # Reached, not merely present. A probe that changed the feature-detect
        # to `if (false)` left both calls in a dead branch and this test passed:
        # the strings were still there, and nothing subscribed.
        assert "if (false)" not in src and "if (0)" not in src, (
            "the subscription sits behind a disabled branch"
        )
        assert "mq.addEventListener)" in src or "mq.addListener)" in src, (
            "the feature-detect must test the real method, so the subscription "
            "is reachable on every browser that has one"
        )

    def test_the_hook_defaults_to_animating_when_unsupported(self):
        """Defaulting to 'reduce' would silently disable motion for anyone whose
        browser does not report the setting."""
        src = _strip_comments(HOOK.read_text())
        assert "return false" in src


class TestTheAnimationExistsAndLoopsSeamlessly:
    def test_the_keyframe_is_defined(self):
        """`animate-ticker` with no keyframe is a class that does nothing — the
        strip would render static with no indication anything is wrong."""
        cfg = TW_CONFIG.read_text()
        assert "'ticker'" in cfg, "no ticker entry in tailwind animation config"
        assert "ticker: {" in cfg, "no ticker keyframe"

    def test_it_translates_fifty_percent_not_one_hundred(self):
        """The strip renders the line TWICE, so -50% lands the duplicate exactly
        where the original started. -100% scrolls it off and snaps back."""
        cfg = _strip_comments(TW_CONFIG.read_text())
        kf = cfg[cfg.index("ticker: {"):]
        assert "translateX(-50%)" in kf[:200]

    def test_the_duplicate_is_hidden_from_screen_readers(self):
        """It exists only so the loop has no visible gap."""
        src = TICKER.read_text()
        assert src.count("{line}") == 2, "the line is not duplicated for the loop"
        dup = src[src.index("{line}"):]
        assert 'aria-hidden="true"' in dup, "a screen reader would read the line twice"

    def test_the_live_region_is_polite(self):
        """These are events with no consequence for the reader, so interrupting
        a screen reader mid-sentence would be exactly wrong."""
        src = TICKER.read_text()
        assert 'aria-live="polite"' in src
        assert 'aria-live="assertive"' not in src


class TestTheTypeStringGuessingIsGone:
    """`styleForType` put `incident_critical` (URGENT) and `timecard_adjustment`
    (INFO) in the same bucket because both matched `includes('critical')` /
    `'warning'`. That is the gap ADR-487 opens with."""

    def test_no_component_guesses_tone_from_the_type_string(self):
        src = _strip_comments(BANNER.read_text())
        for guess in ("includes('critical')", "endsWith('_rejected')",
                      "startsWith('anchor_point')", "includes('warning')"):
            assert guess not in src, f"tone is still guessed from the type: {guess}"

    def test_cards_take_their_colour_from_the_server_tone(self):
        src = _strip_comments(BANNER.read_text())
        assert "TONE_CARD[n.tone]" in src

    def test_the_assignment_card_keeps_its_own_palette(self):
        """dispatch_assignment is deliberately `primary`, not a registry tone:
        'awaiting your answer' is a different axis from good/warn/bad, and a
        tone would make it look like news."""
        src = BANNER.read_text()
        assert "ASSIGNMENT_CARD" in src
        assert "bg-primary/10" in src


class TestEverySurfaceReadingTheEndpointUsesTheRegistry:
    """D8. `/notifications/{id}` has TWO consumers on web: the banner and the
    history page. Both now receive `label`/`tone`/`icon`, and before this the
    history page derived its own.

    The visible symptom was two names for one row from one endpoint:
    `type.replace(/_/g, ' ')` title-cased gave "Rts Rejected" on the archive
    page while the banner showed the registry's "RTS Rejected". Found by asking
    D8's question — "which existing read responses should now include a field
    from this new object?" — not by a test.
    """

    def test_the_history_page_prefers_the_server_label(self):
        src = _strip_comments(HISTORY.read_text())
        assert "n.label" in src, "the history page ignores the server's label"

    def test_the_history_page_prefers_the_server_icon(self):
        """Guarded on the VALUE, not merely mentioning it.

        The first version asserted `"n.icon" in src`, which survived a probe
        that changed the guard to `if (false)` — the string was still there and
        nothing read it. Third time in this session that a presence assertion
        passed over a disabled branch.
        """
        src = _strip_comments(HISTORY.read_text())
        assert "if (n.icon)" in src, (
            "the server icon must gate the branch that renders it; a mention "
            "inside a dead branch renders nothing"
        )
        assert "if (false)" not in src and "if (0)" not in src, (
            "the server-icon branch is disabled"
        )

    def test_the_history_page_no_longer_guesses_from_the_type_string(self):
        """The same `includes('critical')` chain that put an URGENT incident in
        the same bucket as a timecard adjustment."""
        src = _strip_comments(HISTORY.read_text())
        for guess in ("includes('critical')", "includes('warning')",
                      "startsWith('anchor_point')", "endsWith('_rejected')",
                      "endsWith('_approved')"):
            assert guess not in src, f"the history page still guesses: {guess}"

    def test_the_platform_alert_labels_still_win(self):
        """Three types reaching this page are PlatformAlert vocabulary, NOT
        Notification types — ADR-324 D2 keeps them apart because a super admin
        has no Employee row. They have no registry entry, and FAILURE_LABELS
        words them better than any generic rule ("Discord is down").

        So the fallback order is load-bearing: FAILURE_LABELS, then the server,
        then a title-cased type. Checked by position, because reversing it would
        silently replace the good wording the moment a registry entry appeared.
        """
        src = _strip_comments(HISTORY.read_text())
        body = src[src.index("function labelFor"):]
        fl = body.index("FAILURE_LABELS")
        srv = body.index("n.label")
        assert fl < srv, (
            "the server label is checked before FAILURE_LABELS, so a registry "
            "entry would override the better-worded platform-alert names"
        )

    def test_the_fallback_chain_still_has_a_final_default(self):
        """A row with no registry entry AND no FAILURE_LABELS entry must still
        render something — a blank label is worse than a title-cased type."""
        src = _strip_comments(HISTORY.read_text())
        body = src[src.index("function labelFor"):]
        assert "replace(/_/g" in body, "no final fallback for an unlabelled type"


class TestNoSurfaceStillGuessesFromTheTypeString:
    """FIVE copies of the same chain existed, each worded slightly differently:
    NotificationBanner, NotificationsHistory, Navbar's dropdown, and mobile's
    TYPE_META (deferred to the mobile pass). One notification could render as
    warning in the navbar and info in the banner two components away.

    Walks the surfaces rather than naming assertions per file, so a sixth copy
    in a new component fails here.
    """

    _SURFACES = ("NotificationBanner.tsx", "NotificationsHistory.tsx", "Navbar.tsx")
    _GUESSES = (
        "includes('critical')",
        "includes('warning')",
        "endsWith('_rejected')",
        "endsWith('_approved')",
        "startsWith('anchor_point')",
    )

    def test_no_web_surface_guesses_tone_from_the_type(self):
        offenders = []
        web = ROOT / "frontend/src"
        for path in web.rglob("*.tsx"):
            if path.name not in self._SURFACES:
                continue
            src = _strip_comments(path.read_text())
            for guess in self._GUESSES:
                if guess in src:
                    offenders.append(f"{path.name}: {guess}")
        assert not offenders, (
            "a surface still guesses tone from the type string instead of "
            f"reading the server's `tone`: {offenders}"
        )

    def test_the_navbar_dropdown_uses_the_server_icon(self):
        src = _strip_comments(NAVBAR.read_text())
        assert "if (n.icon)" in src, (
            "the navbar dropdown ignores the server's icon"
        )
        assert "if (false)" not in src and "if (0)" not in src

    def test_the_dead_adp_flag_branch_is_not_reintroduced(self):
        """`timecard_adjustment && VITE_ADP_ENABLED` was dead twice over:
        the flag is `false` in .env, .env.template AND .env.production, and
        `timecard_adjustment` is not a notification type at all — every backend
        occurrence is a table name or an audit action_type. The real types are
        the six `timecard_*` entries in SPEC.
        """
        import sys
        from app.services.notification_spec import SPEC

        assert "timecard_adjustment" not in SPEC, (
            "timecard_adjustment became a declared type; if it is now raised, "
            "the clients' dead branch may need revisiting"
        )
        for path in (ROOT / "frontend/src").rglob("*.tsx"):
            if path.name not in self._SURFACES:
                continue
            src = _strip_comments(path.read_text())
            assert "VITE_ADP_ENABLED" not in src, (
                f"{path.name} styles on a flag that is false in every .env"
            )


class TestEveryToneLookupHasAFallback:
    """`TONE_TEXT[n.tone]` on an unexpected tone yields `undefined`, which
    interpolates into the className as the literal string "undefined" — a class
    that does not exist, so the text renders at the inherited colour with no
    error anywhere.

    Three ways a tone arrives unmapped: a row predating the registry (no tone at
    all), a PlatformAlert-vocabulary type with no SPEC entry, or a NEW tone added
    server-side before the client's map is updated. The last is the one that
    matters — the server can ship a sixth Tone and this map is hand-maintained.

    Found by a probe, not by review: removing the `?? TONE_TEXT.bad` from the
    URGENT card broke nothing visible and no test failed, because the guard had
    been added during the diff read and never pinned.
    """

    def test_no_bare_tone_subscript_in_a_class_string(self):
        offenders = []
        for path in (ROOT / "frontend/src").rglob("*.tsx"):
            src = _strip_comments(path.read_text())
            for m in re.finditer(r"TONE_(?:TEXT|CARD)\[[^\]]+\]", src):
                tail = src[m.end():m.end() + 24]
                if "??" not in tail:
                    line = src[:m.start()].count("\n") + 1
                    offenders.append(f"{path.name}:{line} {m.group(0)}")
        assert not offenders, (
            "an unmapped tone yields undefined, which interpolates as the "
            f'literal class "undefined" and renders silently: {offenders}'
        )

    def test_every_tone_map_covers_every_server_tone(self):
        """Each map SEPARATELY, not the file.

        There are two maps — TONE_CARD and TONE_TEXT — and every tone name
        appears in both. Searching the whole file passed a probe that removed
        `active` from TONE_TEXT alone, because TONE_CARD's entry satisfied the
        assertion. Third occurrence of the duplicate-needle gap this session.

        The maps are `Record<NotificationTone, string>`, so TypeScript catches a
        missing key — but only while the TS union and the Python enum agree, and
        those are two hand-maintained files with no codegen between them. This
        test is what notices when the server adds a sixth Tone.
        """
        from app.services.notification_spec import Tone

        src = _strip_comments(TONE.read_text())
        for map_name in ("TONE_CARD", "TONE_TEXT"):
            start = src.index(map_name)
            body = src[start:src.index("};", start)]
            for t in Tone:
                assert f"{t.value}:" in body, (
                    f"Tone.{t.name} ({t.value!r}) has no entry in {map_name}, "
                    f"so it would render with no colour at all"
                )

    def test_the_ts_union_lists_every_server_tone(self):
        """The other half of the hand-maintained pair. A Tone missing from the
        union makes the Record type accept a map that is also missing it, so the
        two files stay consistently wrong and tsc says nothing."""
        from app.services.notification_spec import Tone

        ctx = _strip_comments(CONTEXT.read_text())
        union = ctx[ctx.index("NotificationTone ="):]
        union = union[:union.index(";")]
        for t in Tone:
            assert f"'{t.value}'" in union, (
                f"Tone.{t.name} ({t.value!r}) is missing from the TS union, so "
                f"the tone maps are not required to handle it"
            )
