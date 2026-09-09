"""ADR-403 — a tote's block stops depending on typing order.

`max()` over a dict returns the first key at the maximum, and dict order is
insertion order. With 1-3 captain-entered addresses on distinct blocks every
count is 1, so the "majority vote" was really "whichever address was typed
first" — three different answers for the same tote.
"""
import itertools

import pytest

from app.services.route_sort import _Package, _Tote, resolve_dominant_blocks


def _pkg(bag: str, block: str | None, i: int = 0) -> _Package:
    return _Package(tba_number=f"{bag}-{block}-{i}", bag_id=bag,
                    block_key=block, lat=None, lng=None)


def _tote(bag: str, blocks: list[str | None]) -> _Tote:
    return _Tote(bag_id=bag, packages=[_pkg(bag, b, i) for i, b in enumerate(blocks)])


class TestOrderIndependence:
    def test_a_three_way_tie_resolves_identically_whatever_the_entry_order(self):
        """The bug, directly. Before ADR-403 these six orderings gave three
        different blocks for the same tote."""
        answers = set()
        for order in itertools.permutations(["W_36_St_400", "Broadway_1200", "W_37_St_400"]):
            totes = {"A": _tote("A", list(order))}
            # context: two other totes clearly on Broadway
            totes["c1"] = _tote("c1", ["Broadway_1200"])
            totes["c2"] = _tote("c2", ["Broadway_1200"])
            resolve_dominant_blocks(totes)
            answers.add(totes["A"].dominant_block_key)

        assert len(answers) == 1, (
            f"the same tote resolved to {len(answers)} different blocks depending "
            f"on typing order: {sorted(answers)}"
        )

    def test_the_tie_goes_to_the_block_the_rest_of_the_truck_works(self):
        """D3. A tied tote rides with the route already going there.

        The candidates are deliberately chosen so the popular one sorts LAST
        alphabetically ("W_36" > "Broadway"). Picking the first candidate would
        also pass a test where the popular block happened to sort first, which
        is how a mutation that ignores popularity entirely survived the first
        run of this suite.
        """
        totes = {"A": _tote("A", ["Broadway_1200", "W_36_St_400"])}
        for i in range(3):
            totes[f"c{i}"] = _tote(f"c{i}", ["W_36_St_400"])
        resolve_dominant_blocks(totes)
        assert totes["A"].dominant_block_key == "W_36_St_400", (
            "the tie ignored truck context and fell back to ordering"
        )

    def test_popularity_counts_only_DECIDED_totes(self):
        """Pass 2 must measure over totes that already have an unambiguous
        winner. Counting undecided ones would break a tie using other ties, and
        the answer would depend on iteration order again.

        Here `B` is itself tied between the same two blocks. If B's candidates
        counted toward popularity, the two blocks would stay level and the
        result would come from ordering rather than from `c1`.
        """
        totes = {
            "A": _tote("A", ["Broadway_1200", "W_36_St_400"]),
            "B": _tote("B", ["Broadway_1200", "W_36_St_400"]),
            "c1": _tote("c1", ["W_36_St_400"]),
        }
        resolve_dominant_blocks(totes)
        assert totes["A"].dominant_block_key == "W_36_St_400"
        assert totes["B"].dominant_block_key == "W_36_St_400"


class TestMajorityStillWins:
    def test_a_real_majority_beats_truck_context(self):
        """Context breaks TIES; it does not overrule evidence. A tote with two
        packages on W 36th belongs on W 36th even if the truck lives on
        Broadway."""
        totes = {"A": _tote("A", ["W_36_St_400", "W_36_St_400", "Broadway_1200"])}
        for i in range(5):
            totes[f"c{i}"] = _tote(f"c{i}", ["Broadway_1200"])
        resolve_dominant_blocks(totes)
        assert totes["A"].dominant_block_key == "W_36_St_400"

    def test_a_drop_outvotes_a_single_package(self):
        """D1a. The adapter emits one package per package_count, so eight
        packages to one door become eight votes — the case that used to tie."""
        totes = {"A": _tote("A", ["W_36_St_400"] * 8 + ["Broadway_1200"])}
        resolve_dominant_blocks(totes)
        assert totes["A"].dominant_block_key == "W_36_St_400"


class TestDegenerateInput:
    def test_unparseable_addresses_are_excluded_not_bucketed(self):
        """A null block_key must not become a `None` bucket that can WIN — the
        tote would then vanish from every block grouping in the sort."""
        totes = {"A": _tote("A", [None, None, "W_36_St_400"])}
        resolve_dominant_blocks(totes)
        assert totes["A"].dominant_block_key == "W_36_St_400"

    def test_a_tote_with_no_parseable_address_stays_none(self):
        totes = {"A": _tote("A", [None, None])}
        resolve_dominant_blocks(totes)
        assert totes["A"].dominant_block_key is None

    def test_an_empty_tote_stays_none(self):
        totes = {"A": _Tote(bag_id="A", packages=[])}
        resolve_dominant_blocks(totes)
        assert totes["A"].dominant_block_key is None


class TestStaleState:
    def test_a_tote_that_loses_its_addresses_loses_its_block(self):
        """The case the pass-1 reset actually protects.

        A tote with no parseable block is `continue`d in pass 1 and never
        reaches `decided`, so nothing reassigns it — it keeps whatever it had.
        Deleting a mistyped address and re-sorting must not leave the tote
        reporting the block that address gave it.
        """
        totes = {"A": _tote("A", ["W_36_St_400"])}
        resolve_dominant_blocks(totes)
        assert totes["A"].dominant_block_key == "W_36_St_400"

        # the captain deletes the mistyped address; nothing parseable remains
        totes["A"].packages = [_pkg("A", None)]
        resolve_dominant_blocks(totes)
        assert totes["A"].dominant_block_key is None, (
            "the tote still reports a block from an address that no longer "
            "exists — pass 1 did not clear _resolved_block"
        )


class TestPopularityBasis:
    def test_popularity_ignores_undecided_totes(self):
        """Pass 2 counts only totes with an unambiguous winner.

        Three totes tied between the same two blocks, plus one decided tote on
        Broadway. If tied candidates counted, W_36 would score 3 against
        Broadway's 4 — close enough that a change in either direction flips the
        result. Counting only decided totes gives Broadway 1 and W_36 0, and
        every tied tote follows the one real signal.
        """
        totes = {
            "A": _tote("A", ["Broadway_1200", "W_36_St_400"]),
            "B": _tote("B", ["Broadway_1200", "W_36_St_400"]),
            "C": _tote("C", ["Broadway_1200", "W_36_St_400"]),
            "d1": _tote("d1", ["Broadway_1200"]),
        }
        resolve_dominant_blocks(totes)
        for bag in ("A", "B", "C"):
            assert totes[bag].dominant_block_key == "Broadway_1200", (
                f"{bag} did not follow the only decided tote on the truck"
            )


    def test_a_tied_totes_candidates_do_not_vote(self):
        """The discriminating case: ASYMMETRIC candidate sets.

        When every tied tote is tied between the SAME two blocks, counting their
        candidates adds +1 to each and the difference is unchanged — so a
        symmetric test cannot tell the two bases apart, and one written that way
        let this mutation survive.

        Here A is tied X/Y and B is tied Y/Z, with one decided tote on X:
          decided-only  -> X=1, Y=0        -> A follows the real evidence, X
          all-candidates-> X=1+1, Y=0+1+1  -> level, and X wins only by spelling
        """
        totes = {
            "A": _tote("A", ["X_1", "Y_1"]),
            "B": _tote("B", ["Y_1", "Z_1"]),
            "d1": _tote("d1", ["X_1"]),
        }
        resolve_dominant_blocks(totes)
        assert totes["A"].dominant_block_key == "X_1", (
            "A's tie was decided by B's candidates rather than by the one "
            "decided tote on the truck"
        )

        # B has no evidence either way — neither Y nor Z is worked by a decided
        # tote — so it falls through to the deterministic spelling tie-break.
        # Asserted for STABILITY, not because Z is meaningful: the guarantee is
        # that the same input always gives the same answer.
        assert totes["B"].dominant_block_key == "Z_1"
        for _ in range(3):
            fresh = {
                "A": _tote("A", ["X_1", "Y_1"]),
                "B": _tote("B", ["Y_1", "Z_1"]),
                "d1": _tote("d1", ["X_1"]),
            }
            resolve_dominant_blocks(fresh)
            assert fresh["B"].dominant_block_key == "Z_1"


class TestIdempotence:
    def test_re_running_does_not_drift(self):
        """A re-sort runs this again on the same totes. If pass 1 read
        `_resolved_block` instead of recomputing, each run would feed on the
        last and a tie could migrate."""
        def build():
            t = {"A": _tote("A", ["W_36_St_400", "Broadway_1200"])}
            t["c1"] = _tote("c1", ["Broadway_1200"])
            return t

        totes = build()
        resolve_dominant_blocks(totes)
        first = totes["A"].dominant_block_key

        # Mutating the truck between runs is what exposes a pass 1 that trusts
        # `_resolved_block`: without the reset, A's stale answer would feed pass
        # 2 as though it were decided evidence and the new context would be
        # ignored.
        totes["c2"] = _tote("c2", ["W_36_St_400"])
        totes["c3"] = _tote("c3", ["W_36_St_400"])
        resolve_dominant_blocks(totes)
        assert totes["A"].dominant_block_key == "W_36_St_400", (
            "a re-sort ignored the changed truck: pass 1 did not reset "
            "_resolved_block, so the previous answer was treated as evidence"
        )

        # And stable when nothing changes.
        again = totes["A"].dominant_block_key
        for _ in range(3):
            resolve_dominant_blocks(totes)
        assert totes["A"].dominant_block_key == again
        assert first == "Broadway_1200"
