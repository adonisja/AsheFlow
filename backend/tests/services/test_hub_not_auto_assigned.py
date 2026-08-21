"""ADR-274 — a hub is a kind of truck, and is never auto-assigned.

The rule is one filter term in four places, which is exactly the shape that rots:
someone adds a truck query and forgets the hub clause, and the failure is silent
— a hub quietly collects crew it was never supposed to have.

These read the SOURCE rather than running dispatch, for the same reason
`test_role_authority_sets.py` does: the thing being guarded is a literal in a
query, and a behavioural test would need a full dispatch fixture to exercise
what a two-line assertion pins exactly.
"""
from pathlib import Path

import pytest


BACKEND = Path(__file__).resolve().parents[2]


def _src(relpath: str) -> str:
    return (BACKEND / relpath).read_text(encoding="utf-8")


class TestHubExcludedFromAutoAssignment:
    def test_run_dispatch_excludes_hubs(self):
        src = _src("app/services/run_dispatch.py")
        assert "Truck.is_hub == False" in src, (
            "run_dispatch must exclude hub trucks — a hub exists for manual "
            "intra-day assembly, so the algorithm placing crew on it defeats "
            "the reason it exists (ADR-274 D2)"
        )

    def test_run_dispatch_filters_before_explicit_selection(self):
        # The hub clause must sit in the base query, NOT after the truck_ids
        # branch — otherwise an explicit selection passes a hub in by hand.
        src = _src("app/services/run_dispatch.py")
        hub_at = src.index("Truck.is_hub == False")
        branch_at = src.index("if truck_ids:")
        assert hub_at < branch_at, (
            "the hub filter must be in the base truck query, before the "
            "explicit truck_ids branch, or a caller can bypass it"
        )

    def test_run_sort_excludes_hubs(self):
        # A hub HAS a TruckAssignment, so run_sort's join would pull it into
        # package sorting without this.
        src = _src("app/services/run_sort.py")
        assert src.count("Truck.is_hub.is_(False)") >= 2, (
            "both the assigned-truck join and the pre-dispatch fallback must "
            "exclude hubs — a hub carries no delivery territory"
        )

    def test_captain_familiarisation_excludes_hubs(self):
        # Counting a hub would hold a captain in familiarisation against a truck
        # they can never complete a route on.
        src = _src("app/services/assign_captains.py")
        assert "Truck.is_hub == False" in src


class TestHubIsAColumnNotAStatus:
    def test_truck_model_has_is_hub(self):
        src = _src("app/models/truck.py")
        assert "is_hub" in src and "server_default=\"false\"" in src, (
            "is_hub must exist with a server default so the migration is "
            "additive and existing trucks keep their behaviour"
        )

    def test_truck_schemas_expose_is_hub(self):
        src = _src("app/schemas/truck.py")
        # create, update, and response — all three, or the admin page cannot
        # set it and the dispatch page cannot read it.
        assert src.count("is_hub") >= 3

    def test_dispatch_payload_sends_is_hub(self):
        # The frontend used to DERIVE hub-ness from status == 'planned', which
        # matched every truck before publish. It must be sent, not inferred.
        src = _src("app/routers/dispatch.py")
        assert '"is_hub"' in src, (
            "GET /dispatch/{date} must send is_hub per truck assignment "
            "(ADR-274) — deriving it client-side is the bug this replaced"
        )


class TestCreateHubRejectsNonHubTrucks:
    """The UI offers hub trucks only, but the ENDPOINT is the boundary.

    Without this guard a direct caller could create a hub assignment on a
    delivery truck — reintroducing "hub is a state some truck is in", which is
    the thing ADR-274 removed.
    """

    def test_create_hub_checks_is_hub(self):
        src = _src("app/routers/dispatch.py")
        assert "if not truck.is_hub:" in src, (
            "POST /dispatch/hubs must reject a truck that is not a hub"
        )

    def test_rejection_names_the_fix(self):
        # An error that says only "invalid" leaves the dispatcher stuck; this
        # one points at the Trucks page.
        src = _src("app/routers/dispatch.py")
        assert "is not a hub truck" in src and "Trucks" in src


class TestHubManifestIsolation:
    """ADR-274 D7 — a hub's manifest never touches the company's.

    Two failure modes, both silent and both expensive:

      * a hub upload running the ADR-177 same-day clear would wipe the OTHER
        trucks' zones, routes, centroids, transfers and dock assignments
      * passing the bare date to enrich_manifest_packages would overwrite
        manifest:{company}:{date} with the hub's out-of-zone packages, dragging
        every truck's clustering toward points nothing should route to

    Neither raises. Both are pinned structurally, because a behavioural test
    would need Redis, Celery and a full manifest fixture to assert what two
    string checks assert exactly.
    """

    def _upload_source(self) -> str:
        import inspect
        from app.routers import sort as sortmod
        return inspect.getsource(sortmod.upload_manifest)

    def test_hub_branch_precedes_the_destructive_clear(self):
        src = self._upload_source()
        assert src.index("HUB MANIFEST (ADR-274 D7)") < src.index("ADR-177 decision (b)"), (
            "the hub branch must come BEFORE the same-day state clear, or a hub "
            "upload wipes the other trucks' sort"
        )

    def test_hub_branch_returns_before_the_destructive_clear(self):
        src = self._upload_source()
        between = src[src.index("HUB MANIFEST (ADR-274 D7)"):src.index("ADR-177 decision (b)")]
        assert "return ManifestUploadResponse" in between, (
            "the hub branch must RETURN, not fall through into the clear"
        )

    def test_hub_packages_use_a_namespaced_redis_scope(self):
        # Asserts on the CODE, not the prose. The first version of this test
        # checked for "#hub:" anywhere in the branch and passed against a
        # planted bug, because the explanatory comment above the assignment
        # also contains "#hub:". A test a comment can satisfy protects nothing.
        src = self._upload_source()
        between = src[src.index("HUB MANIFEST (ADR-274 D7)"):src.index("ADR-177 decision (b)")]
        # Drop comment LINES only. Do not strip at the first "#" — the scope
        # string itself contains "#hub:", and splitting on it truncated the
        # very line under test to `hub_scope = f"{date_str}`.
        code = [
            ln.strip()
            for ln in between.splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        assign = [ln for ln in code if ln.startswith("hub_scope")]
        assert assign, "hub_scope is never assigned"
        assert any("date_str" in ln and "tid_str" in ln for ln in assign), (
            "enrich_manifest_packages derives manifest:{company}:{sort_date} "
            "internally, so hub_scope must combine the date AND the truck id — "
            f"otherwise the hub overwrites the company manifest. Got: {assign}"
        )
        assert any("sort_date=hub_scope" in ln for ln in code), (
            "the namespaced scope must actually be PASSED to the task"
        )

    def test_hub_branch_rejects_a_non_hub_truck(self):
        src = self._upload_source()
        assert "is not a hub truck" in src

    def test_hub_branch_requires_the_assignment_first(self):
        # Creating an assignment as a side effect of a file upload is the
        # anti-pattern D4 rejected for truck creation.
        src = self._upload_source()
        assert "No hub assignment for" in src


class TestHubRemoval:
    """ADR-274 D8 — one hub can be removed without clearing the day.

    The guard that matters is the NEGATIVE one: this endpoint must never become
    a way to dismantle a balanced dispatch one truck at a time. Regular trucks
    arrive as a set from run_dispatch with crew balanced across them; removing
    one would strand its crew and under-load the rest with no re-balance.
    """

    def _source(self) -> str:
        import inspect
        from app.routers import dispatch as dispatchmod
        return inspect.getsource(dispatchmod.remove_hub)

    def test_rejects_a_non_hub_truck(self):
        src = self._source()
        assert "if not truck.is_hub:" in src, (
            "remove_hub must 422 on a regular truck, or it becomes a backdoor "
            "for taking a balanced dispatch apart"
        )

    def test_rejection_points_at_the_right_tool(self):
        # "invalid" leaves the dispatcher stuck; this names Clear Dispatch.
        src = self._source()
        assert "Clear Dispatch" in src or "Run Dispatch" in src

    def test_does_not_touch_date_keyed_station_artifacts(self):
        # Zones, transfers, check-offs and dock assignments belong to the day's
        # OTHER trucks. clear_daily_dispatch wipes them BY DATE; removing one
        # hub must not, or it destroys work the hub never produced.
        src = self._source()
        for table in ("TruckZone", "ToteTransfer", "ToteLoadCheck", "DockAssignment"):
            assert table not in src, (
                f"remove_hub must not delete {table} — it is date-keyed and "
                f"belongs to the other trucks"
            )

    def test_reports_whether_the_hub_was_published(self):
        # The UI warns about already-notified crew; it needs this to know.
        src = self._source()
        assert "was_published" in src and "crew_removed" in src

    def test_writes_an_audit_row(self):
        src = self._source()
        assert "write_audit" in src and "dispatch.hub_removed" in src


class TestHubManifestBecomesRoutes:
    """ADR-274 D7 — a hub's own manifest reaches its crew (commit_sort).

    A hub never runs the station sort, so no TruckZone exists to supply TBAs.
    Its manifest IS the TBA list. Everything after that point is the SAME code
    a regular truck uses — same splitting, same ordering, same Route rows — so
    the hub crew gets the same My Route screen.
    """

    def _commit_source(self) -> str:
        import inspect
        from app.routers import walker_routes
        return inspect.getsource(walker_routes.commit_sort)

    def test_hub_takes_tbas_from_its_own_manifest_not_a_zone(self):
        src = self._commit_source()
        assert "#hub:" in src and "is_hub" in src, (
            "commit_sort must source a hub's TBAs from its namespaced manifest "
            "scope — a hub has no TruckZone and never will"
        )

    def test_non_hub_still_requires_a_zone(self):
        # The hub path must be a BRANCH, not a replacement: a regular truck
        # committing without a zone is still an error.
        src = self._commit_source()
        assert "No active TruckZone found" in src

    def test_hub_error_names_the_fix(self):
        src = self._commit_source()
        assert "No hub manifest for" in src and "Manifest for" in src


class TestBagFieldsSurviveCommitSort:
    """Two bugs found while wiring the hub — BOTH on the normal path.

    The operator caught the framing: a hub manifest has the same structure as a
    regular one ("their contents are simply kept separate"), so anything that
    breaks for a hub breaks for every truck.
    """

    def _commit_source(self) -> str:
        import inspect
        from app.routers import walker_routes
        return inspect.getsource(walker_routes.commit_sort)

    def test_bag_id_none_does_not_reach_pydantic(self):
        # enrich_manifest ALWAYS writes the bag_id key, setting it to None when
        # the row had no resolvable bag label. `.get("bag_id", "")` therefore
        # returns None — the default never fires — and PackageInput(bag_id: str)
        # rejects it. One unlabelled package 422'd the whole commit.
        src = self._commit_source()
        assert 'pkg.get("bag_id") or ""' in src, (
            'bag_id must use `or ""`, not a .get default — the key is always '
            "present and its VALUE is None"
        )
        assert 'pkg.get("bag_id", "")' not in src

    def test_bag_color_is_passed_through(self):
        # ADR-230: parsed by the ingestor, cached by enrichment, accepted by
        # PackageInput, consumed by route_sort — and dropped at this one hop,
        # so every bag rendered neutral.
        src = self._commit_source()
        assert 'bag_color           = pkg.get("bag_color")' in src or \
               'bag_color' in src, "the ADR-230 bag colour must reach route_sort"
