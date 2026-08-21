"""ADR-277 D3 — the truck-scoped building page.

Three groups: what you owe a decision on, what the crew can rely on, and what
nobody has profiled yet. The third is the feature — it turns a review queue
into a collection prompt.

building_profiles.py is proprietary; CI copies it in from AsheFlow-private
before pytest, so there is deliberately NO skip guard.
"""
import inspect

from app.main import app


def _src():
    from app.routers import building_profiles
    return inspect.getsource(building_profiles.buildings_for_truck)


class TestRouteExists:
    def test_endpoint_is_registered(self):
        assert "/api/v1/building-profiles/for-truck/{route_date}" in app.openapi()["paths"]

    def test_it_does_not_shadow_the_id_route(self):
        """`/for-truck/{date}` and `/{profile_id}` are both one segment deep, so
        a mis-ordered declaration makes FastAPI parse "for-truck" as a UUID and
        422 before the handler ever runs.

        Asserted by DISPATCHING a real request, not by reading the schema. The
        schema lists the path either way; only routing says which handler wins.
        401 (auth rejected) proves the route resolved — 422 would mean the
        {profile_id} route swallowed it, 404 that nothing matched.
        """
        from fastapi.testclient import TestClient

        client = TestClient(app, raise_server_exceptions=False)
        r = client.get("/api/v1/building-profiles/for-truck/2026-08-20")
        assert r.status_code == 401, (
            f"expected 401 (route resolved, auth rejected), got {r.status_code}"
        )


class TestTenancyAndScope:
    def test_every_query_is_company_scoped(self):
        """ADR-115 dim 1. This endpoint runs FOUR queries — assignment, truck,
        stops, profiles — plus the verification set. A missing company_id on
        any inner one is a cross-tenant leak, and the inner ones are where it
        hides."""
        src = _src()
        # Per-MODEL, not a total count. A `>= 5` total passes even when one
        # query loses its filter, because another query carries two — which is
        # exactly how a planted cross-tenant leak on DeliveryStop survived the
        # first version of this test.
        for model in (
            "TruckAssignment",
            "Truck",
            "DeliveryStop",
            "BuildingProfile",
            "BuildingProfileVerification",
        ):
            assert f"{model}.company_id == caller.company_id" in src, (
                f"{model} query is not company-scoped — cross-tenant read"
            )
        # And the count is pinned so a NEW query cannot be added without
        # revisiting this list.
        assert src.count("db.query(") == 5, (
            "query count changed — add the new model to the scoping list above"
        )

    def test_stops_are_scoped_to_the_callers_own_assignment(self):
        """The stop query must filter on the assignment resolved from the
        caller's crew membership, not on a client-supplied id."""
        src = _src()
        assert "DeliveryStop.truck_assignment_id == assignment.id" in src
        assert "AssignmentMember.employee_id == caller.id" in src

    def test_no_truck_is_a_state_not_an_error(self):
        """A dispatcher not crewed on a truck gets an empty page that SAYS so.
        Returning three empty lists would render as a fully-profiled day."""
        src = _src()
        assert "no_truck_assigned=True" in src
        assert "if assignment is None:" in src


class TestGrouping:
    def test_rejected_profiles_are_excluded(self):
        """ADR-277 D1's rule, at the one read that could surface them. A
        rejected address matches no stop, so showing it under "Known" puts a
        building in front of the crew that they can never find."""
        src = _src()
        assert 'BuildingProfile.address_status != "rejected"' in src

    def test_signoff_group_is_empty_for_non_signers(self):
        """A walker cannot sign off (ADR-276 D1), so surfacing a "needs your
        sign-off" pile to them is a queue they can never clear."""
        src = _src()
        assert "can_sign" in src
        assert "_SIGNOFF_ROLES" in src
        assert 'building_type_status == "review" and can_sign' in src

    def test_unprofiled_addresses_are_their_own_group(self):
        src = _src()
        assert "no_profile.append(stop)" in src
        assert "if bp is None:" in src

    def test_profiles_are_bulk_loaded_not_per_address(self):
        """A truck's day is ~100 addresses. One query per address is 100
        round-trips on a page a captain opens mid-shift."""
        src = _src()
        assert "normalised_address.in_(addresses)" in src

    def test_duplicate_visits_collapse_to_one_building(self):
        """One truck hits the same building on several routes. The page is
        about buildings, not visits — but the visit count is kept, because it
        is what makes one building worth profiling before another."""
        src = _src()
        assert "by_addr" in src
        assert 'entry["count"] += 1' in src
        assert "stop_count" in src

    def test_ordering_puts_the_most_visited_first(self):
        src = _src()
        assert "-s.stop_count" in src


class TestPurgeInteraction:
    def test_a_purged_stop_still_lands_in_a_group(self):
        """ADR-219 nulls normalised_address at 48h; block_key and segment_id
        (ADR-279) survive. A stop whose address is gone must still appear —
        keyed on block — rather than vanishing or crashing the grouping."""
        src = _src()
        assert 'f"__block__{st.block_key}"' in src, (
            "a purged stop needs a synthetic key, or None collapses every "
            "purged stop into one row"
        )

    def test_segment_id_survives_a_null_first_write(self):
        """A stop resolved later in the day can carry topology an earlier one
        lacked. Last-write-wins would discard it."""
        src = _src()
        assert 'if entry["segment_id"] is None:' in src


class TestPII:
    def test_raw_note_is_not_what_the_page_shows(self):
        """D3: operational_note is the captain-structured version; raw_note is
        unreviewed walker free text and the one field that might carry a
        person's name. Both ride in BuildingProfileResponse, so this asserts
        the page does not ADD a raw_note surface of its own."""
        src = _src()
        assert "raw_note" not in src

    def test_no_address_is_logged(self):
        src = _src()
        assert "logger" not in src
