"""A suggested bay reaches the driver even if nobody confirms it (ADR-274 D17).

THE QUESTION THIS ANSWERS
-------------------------
Dispatch sets a truck's dock zone on the assignment page, prefilled from the
truck's last known bay. The operator asked the sharp version of the follow-up:
*what if they never confirm?*

Before this, nothing was written until dispatch clicked. So a dispatcher could
see "A3" prefilled on screen, publish without touching it, and the driver's DM
would carry NO dock line at all — the screen and the message disagreeing about
where a person should physically walk. On a busy morning that is the normal
path, not the edge case.

THE RULE
--------
Publish RESOLVES the bay, in order:
  1. what dispatch set for the day  — an explicit decision always wins
  2. the truck's last known bay     — silence means "same as always"
  3. None                           — a truck with no history at all

and writes the result back, so the decision is recorded rather than recomputed:
tomorrow's suggestion reads today's row.

Source-reading, comment-stripped. The behavioural half is covered against the
real database on staging (a source test cannot prove a query returns the right
row).
"""
from pathlib import Path

import pytest


BACKEND = Path(__file__).resolve().parents[2]
DISPATCH = BACKEND / "app" / "routers" / "dispatch.py"
PERSIST = BACKEND / "app" / "services" / "persist_zones.py"
BOT = BACKEND.parent / "bot" / "cogs" / "dispatch.py"


def _fn(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    start = text.index(f"def {name}(")
    nxt = text.find("\n@router.", start)
    if nxt == -1:
        nxt = text.find("\ndef ", start + 10)
    body = text[start:nxt if nxt != -1 else len(text)]
    if '"""' in body:
        a = body.index('"""'); b = body.index('"""', a + 3) + 3
        body = body[:a] + body[b:]
    return "\n".join(
        l.strip() for l in body.splitlines()
        if l.strip() and not l.strip().startswith("#")
    )


class TestResolverPrecedence:
    @pytest.fixture(scope="class")
    def src(self) -> str:
        return _fn(DISPATCH, "_resolve_dock_zone")

    def test_an_explicit_choice_wins(self, src: str):
        assert "if assignment.dock_zone:" in src, (
            "a bay dispatch actually set must beat the inherited one — "
            "otherwise editing today's dock does nothing"
        )
        assert "return assignment.dock_zone" in src

    def test_silence_inherits_the_last_known_bay(self, src: str):
        # The whole point: an unconfirmed suggestion still reaches the driver.
        assert "_last_known_dock(" in src, (
            "an unconfirmed truck publishes with no dock, so the DM omits the "
            "line the dispatcher was looking at when they hit publish"
        )

    def test_the_resolved_value_is_written_back(self, src: str):
        # Recorded, not recomputed: tomorrow's suggestion reads today's row, and
        # "where was this truck sent" has an answer after the fact.
        assert "assignment.dock_zone = inherited" in src, (
            "the inherited bay is used but never persisted, so it vanishes from "
            "history and cannot seed the next day"
        )


class TestLookupIsScoped:
    @pytest.fixture(scope="class")
    def src(self) -> str:
        return _fn(DISPATCH, "_last_known_dock")

    def test_company_and_truck_scoped(self, src: str):
        assert "TruckAssignment.company_id == company_id" in src, "cross-tenant read"
        assert "TruckAssignment.truck_id == truck_id" in src, (
            "bays are not interchangeable between trucks — another truck's "
            "history is not evidence for this one"
        )

    def test_looks_strictly_backwards(self, src: str):
        # `<` not `<=`: including the current date would return the row being
        # resolved, so a null would 'inherit' itself and never fall through.
        assert "TruckAssignment.date < before_date" in src, (
            "must look strictly before the target date"
        )

    def test_skips_days_with_no_bay_recorded(self, src: str):
        assert "TruckAssignment.dock_zone.isnot(None)" in src, (
            "a single dockless day would shadow the real last known bay"
        )

    def test_takes_the_most_recent(self, src: str):
        assert "TruckAssignment.date.desc()" in src


class TestPublishAppliesIt:
    def test_regular_publish_resolves_every_truck(self):
        src = _fn(DISPATCH, "publish_dispatch")
        assert "_resolve_dock_zone(db, caller.company_id, _a)" in src, (
            "publish_dispatch does not settle bays, so the bot — which fetches "
            "the payload itself — sends DMs with no dock line"
        )
        assert "db.commit()" in src

    def test_resolution_happens_before_the_bot_is_called(self):
        src = _fn(DISPATCH, "publish_dispatch")
        resolve = src.index("_resolve_dock_zone")
        bot = src.index("bot_url")
        assert resolve < bot, (
            "bays are settled AFTER the bot webhook fires — the bot would read "
            "the payload before the values exist"
        )

    def test_hub_publish_resolves_too(self):
        src = _fn(DISPATCH, "publish_hub")
        assert "_resolve_dock_zone(db, caller.company_id, assignment)" in src


class TestSeedsDeferToIt:
    def test_persist_zones_prefers_the_set_bay(self):
        src = PERSIST.read_text(encoding="utf-8")
        assert "label = set_dock or dock_label_by_truck.get(truck_id)" in src, (
            "re-running the sort would overwrite the bay dispatch set with the "
            "truck name"
        )
        assert "_TA.dock_zone" in src, "the driver query no longer reads the set bay"


class TestDriverActuallySeesIt:
    def test_dock_travels_on_the_dispatch_payload(self):
        src = DISPATCH.read_text(encoding="utf-8")
        assert '"dock_zone": a.dock_zone,' in src, (
            "GET /dispatch/{date} omits the bay, and the bot reads that endpoint "
            "for its own data — so the DM can never show one"
        )

    def test_bot_reads_it_and_renders_a_line(self):
        src = BOT.read_text(encoding="utf-8")
        assert "dock_by_truck" in src, "the bot never picks the bay out of the payload"
        assert 'dock_line = f"**Dock:** {dock_zone}\\n" if dock_zone else ""' in src, (
            "the driver DM does not render the bay"
        )

    def test_no_dock_line_when_there_is_no_bay(self):
        # A truck with no history at all: omit the line rather than print
        # "Dock: None", which reads as a system fault to the driver.
        src = BOT.read_text(encoding="utf-8")
        assert 'if dock_zone else ""' in src
