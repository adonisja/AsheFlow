"""Public collection endpoint (ADR-415).

The security properties are the point here, not the happy path. Every test below
pins something that, if it regressed, would turn a research tool into a way for
anyone with a URL to write into a tenant's data.
"""
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.routers.collection import _resolve_token
from app.schemas.collection import CollectedProfileIn, CollectionSubmitIn
from fastapi import HTTPException


class _FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *a, **k):
        return self

    def first(self):
        return self._result


class _FakeDB:
    def __init__(self, result=None):
        self._result = result

    def query(self, *a, **k):
        return _FakeQuery(self._result)


class _Tok:
    def __init__(self, revoked_at=None, expires_at=None):
        self.revoked_at = revoked_at
        self.expires_at = expires_at


class TestTheBodyCannotChooseATenant:
    """ADR-415 D2. company_id comes from the token, and the request may not
    supply one — a public endpoint that trusted a body-supplied tenant id is a
    cross-tenant write with extra steps."""

    def test_company_id_in_the_body_is_rejected(self):
        with pytest.raises(ValidationError):
            CollectionSubmitIn(token="x" * 20, profiles=[{
                "address": "433 W 32 ST", "building_type": "walkup",
                "workload_class": "high_touch", "collected_on": "2026-09-15",
                "company_id": "11111111-1111-1111-1111-111111111111",
            }])

    def test_the_submit_schema_has_no_company_field_at_all(self):
        assert "company_id" not in CollectionSubmitIn.model_fields
        assert "company_id" not in CollectedProfileIn.model_fields


class TestAnInactiveTokenIsIndistinguishableFromAMissingOne:
    """A response that separated "revoked" from "no such token" would confirm a
    guessed token exists, turning the endpoint into an oracle. All three paths
    must give the same 404."""

    @pytest.mark.parametrize("tok", [
        None,
        _Tok(revoked_at=datetime.now(timezone.utc)),
        _Tok(expires_at=datetime.now(timezone.utc) - timedelta(days=1)),
    ], ids=["missing", "revoked", "expired"])
    def test_all_inactive_states_give_the_same_404(self, tok):
        with pytest.raises(HTTPException) as e:
            _resolve_token(_FakeDB(tok), "whatever")
        assert e.value.status_code == 404
        assert e.value.detail == "Collection link is not active."

    def test_a_live_token_resolves(self):
        live = _Tok(expires_at=datetime.now(timezone.utc) + timedelta(days=1))
        assert _resolve_token(_FakeDB(live), "whatever") is live

    def test_a_token_with_no_expiry_is_live(self):
        live = _Tok()
        assert _resolve_token(_FakeDB(live), "whatever") is live


class TestTheTrustBoundaryIsTyped:
    """CLAUDE.md Dimension 9. Every other request schema is filled in by someone
    who authenticated first; this one is filled in by anybody with the URL."""

    def _ok(self, **over):
        base = {
            # ADR-418 shape: a leaf type, and workloads as a non-empty SET.
            # `building_category` is absent on purpose — the server derives it,
            # and the schema forbids extras, so sending it is a 422.
            "address": "433 W 32 ST", "building_type": "walkup",
            "workloads": ["door_to_door"], "collected_on": "2026-09-15",
        }
        base.update(over)
        return base

    def test_a_valid_submission_is_accepted(self):
        got = CollectionSubmitIn(token="x" * 20, profiles=[self._ok()])
        assert got.profiles[0].address == "433 W 32 ST"

    @pytest.mark.parametrize("over,why", [
        ({"building_type": "castle"},        "building_type not in the real enum"),
        ({"workload_class": "very_hard"},    "workload_class not in the real enum"),
        ({"address": "x"},                   "address under min_length"),
        ({"address": "y" * 201},             "address over max_length"),
        ({"note": "z" * 2001},               "note over max_length"),
        ({"extra_field": "surprise"},        "unrecognised key"),
    ])
    def test_malformed_fields_are_refused(self, over, why):
        with pytest.raises(ValidationError):
            CollectedProfileIn(**self._ok(**over))

    def test_the_enums_are_the_SAME_objects_the_sort_pipeline_reads(self):
        """Identity, not overlap.

        This used to name three literals — and two of them (`doorman`,
        `biz_loading_dock`) were values ADR-418 removed, so the test kept
        passing against a SECOND frozenset in location_profile.py that the
        production router still validated against. Every stored row read
        `unknown`, which that router would have rejected (ADR-422).

        Asserting the objects are identical is the property the docstring
        always claimed: a literal list can drift from the definition while
        still passing, an identity check cannot.
        """
        from app.schemas import building_taxonomy
        from app.schemas.location_profile import BUILDING_TYPES, WORKLOAD_CLASSES
        assert BUILDING_TYPES is building_taxonomy.BUILDING_TYPES, (
            "location_profile must re-export the taxonomy, not redefine it"
        )
        for w in ("high_touch", "bulk_drop", "high_wait", "standard"):
            assert w in WORKLOAD_CLASSES

    def test_batch_size_is_bounded(self):
        # A batch exists because collectors work offline and submit later; it is
        # not a bulk-write primitive.
        one = self._ok()
        CollectionSubmitIn(token="x" * 20, profiles=[one] * 100)
        with pytest.raises(ValidationError):
            CollectionSubmitIn(token="x" * 20, profiles=[one] * 101)
        with pytest.raises(ValidationError):
            CollectionSubmitIn(token="x" * 20, profiles=[])

    def test_a_short_token_is_refused_before_any_lookup(self):
        with pytest.raises(ValidationError):
            CollectionSubmitIn(token="short", profiles=[self._ok()])


class TestTheResponseSaysNothingUseful:
    """ADR-415 D4. The submitter gets a receipt, not a window into the table."""

    def test_the_output_carries_counts_and_nothing_from_the_table(self):
        """The receipt may echo THIS request; it may never describe the table.

        `duplicate_addresses` was added by ADR-417: the addresses in this batch
        the campaign already had. That is an echo of data the submitter just
        supplied, not a read — it supports no enumeration, and learning one bit
        costs a complete profile and a row against the daily cap.

        The set is pinned exactly so a field that DOES describe the table (an
        id, a count of everything, a neighbouring address) fails here.
        """
        from app.schemas.collection import CollectionSubmitOut
        assert set(CollectionSubmitOut.model_fields) == {
            "accepted", "duplicate", "duplicate_addresses",
        }

    def test_duplicate_addresses_only_ever_echoes_the_request(self):
        """Every echoed address must have been in the submitted batch.

        Pins the property that makes the echo safe. A future change that
        populated this from a query — "addresses near yours", "others today" —
        would turn the receipt into the read path D4 forbids, and fails here.
        """
        import inspect
        from app.routers import collection as C
        src = inspect.getsource(C.submit_profiles)
        # The list is appended to exactly once, from the loop variable `p`
        # (the request body), never from a query result.
        assert "duplicate_addresses.append(p.address)" in src, \
            "the echo must come from the request, not from a lookup"
        # Two appends now, both from the loop variable `p`: one when the unique
        # constraint rejects a same-day repeat, one when the door is already at
        # the verification limit (ADR-420). Neither reads another row's address,
        # which is the property that matters.
        assert src.count("duplicate_addresses.append(p.address)") == \
            src.count("duplicate_addresses.append"), \
            "every echoed address must come from the request body"


class TestThePublicPathIsWriteOnly:
    """ADR-415 D4 constrains the PUBLIC path, not the router.

    Super-admin reads were added later (see TestThePlatformOwnerCanReadWhatArrived),
    so the property is "nothing ungated returns collected data" — not "this file
    contains no GET". Stated narrowly here so the test keeps protecting the real
    boundary instead of failing every time an authenticated read is added.
    """

    def test_the_public_submit_path_accepts_no_GET(self):
        from app.routers.collection import router
        for r in router.routes:
            if r.path.endswith("/submit"):
                assert "GET" not in getattr(r, "methods", set()), \
                    "the public path exposes a read"

    def test_the_public_path_is_the_only_ungated_one(self):
        # Token management must stay behind RoleChecker; only /submit is public.
        from app.routers.collection import router
        public = [r.path for r in router.routes if r.path.endswith("/submit")]
        assert public == ["/collection/submit"]


class TestTheRouterIsActuallyMounted:
    """A router that is written but never included is a feature nobody can
    reach. Asserted against the app's own OpenAPI schema rather than by reading
    main.py, so a lost include_router line fails here."""

    def test_submit_is_reachable_and_public(self):
        from app.main import app
        spec = app.openapi()
        assert "/api/v1/collection/submit" in spec["paths"], \
            "collection router is not mounted on the app"
        ops = spec["paths"]["/api/v1/collection/submit"]
        assert set(ops) == {"post"}, f"submit exposes more than POST: {set(ops)}"

    def test_token_management_is_mounted(self):
        from app.main import app
        spec = app.openapi()
        for p in ("/api/v1/collection/tokens",
                  "/api/v1/collection/tokens/{token_id}/revoke"):
            assert p in spec["paths"], f"{p} is not mounted"

    def test_the_only_reads_are_the_super_admin_ones(self):
        """A GET on a collection path is allowed only where a super-admin gate
        stands in front of it. Any other one is a public read of customer
        addresses.

        Checks the GATE, not a hardcoded list of paths. An allowlist has to be
        edited every time a read is added, and the edit is the moment the
        question stops being asked — the reviewer updates the set and moves on.
        Resolving the dependency means a new read passes only if it is actually
        gated, and a read that loses its gate fails even though its path is
        unchanged.
        """
        import inspect
        from app.api.deps import get_super_admin
        from app.routers.collection import router

        from app.api.deps import get_platform_staff

        for r in router.routes:
            if "GET" not in getattr(r, "methods", set()):
                continue
            src = inspect.getsource(r.endpoint)
            gates = [
                p.default.dependency
                for p in inspect.signature(r.endpoint).parameters.values()
                if getattr(p.default, "dependency", None) is not None
            ]
            # ADR-423 widened these from "super admin only" to "super admin OR
            # the owning company's admin", so the gate is no longer a single
            # dependency — it is _scope_reads, which 403s anyone else and
            # filters a company admin to their own company_id.
            assert "_scope_reads(" in src, (
                f"{r.path} is a read on the collection router that does not go "
                f"through _scope_reads"
            )
            # The invariant ADR-423 must not erode: a cross-tenant support
            # login may never reach addresses or names (ADR-343 D4).
            assert get_platform_staff not in gates, (
                f"{r.path} exposes collected PII to platform_support"
            )


class TestThePlatformOwnerCanReadWhatArrived:
    """The read side (ADR-415 addendum). Two endpoints, both super-admin only."""

    def test_both_reads_are_mounted(self):
        from app.main import app
        spec = app.openapi()
        assert "get" in spec["paths"]["/api/v1/collection/tokens"]
        assert "get" in spec["paths"]["/api/v1/collection/profiles"]

    def test_the_public_submit_path_still_exposes_no_read(self):
        # Adding reads elsewhere must not have loosened the public path.
        from app.main import app
        spec = app.openapi()
        assert set(spec["paths"]["/api/v1/collection/submit"]) == {"post"}

    def test_reads_never_admit_platform_staff(self):
        """ADR-343 D4: no `platform_support` endpoint may return addresses.

        These rows ARE customer delivery addresses, so the stricter gate is
        load-bearing, not incidental. Asserted against the resolved dependency
        so swapping the import fails here.
        """
        import inspect
        from app.api.deps import get_platform_staff
        from app.routers.collection import (
            get_collected_day, list_collected_days, list_collected_profiles, list_tokens,
        )

        for fn in (list_collected_profiles, list_tokens,
                   list_collected_days, get_collected_day):
            deps = [
                p.default.dependency
                for p in inspect.signature(fn).parameters.values()
                if hasattr(p.default, "dependency")
            ]
            assert get_platform_staff not in deps, (
                f"{fn.__name__} admits platform_support — ADR-343 D4 forbids "
                "addresses and names behind that cross-tenant login"
            )
            # ADR-423: the gate is _scope_reads, not one dependency. It 403s
            # anyone who is neither a super admin nor the owning company's
            # management/admin, and filters the latter to their own company_id.
            assert "_scope_reads(" in inspect.getsource(fn), (
                f"{fn.__name__} does not scope its read"
            )

    def test_the_token_value_is_never_listed(self):
        """The secret is returned once at creation. A listing that echoed live
        tokens would turn one compromised admin session into every campaign."""
        from app.schemas.collection import CollectionTokenSummary
        assert "token" not in CollectionTokenSummary.model_fields

    def test_profile_reads_are_paged(self):
        """This table grows one row per building per collector per day; an
        accidental full-table response is its own kind of outage."""
        import inspect
        from app.routers.collection import list_collected_profiles
        params = inspect.signature(list_collected_profiles).parameters
        assert "limit" in params and "offset" in params
        assert params["limit"].default.default == 200


class TestTheDuplicateCheckIsNotAnOracle:
    """ADR-417 D7. A read on the public path, narrowed so it cannot enumerate."""

    def test_the_request_takes_one_address_never_a_list(self):
        """A list parameter would make this a bulk oracle: paste a thousand
        addresses, learn the campaign's coverage in one call."""
        from app.schemas.collection import CollectionCheckIn
        assert CollectionCheckIn.model_fields["address"].annotation is str
        with pytest.raises(ValidationError):
            CollectionCheckIn(token="k" * 32, address=["a", "b"])

    def test_the_response_is_existence_a_date_and_a_count_and_nothing_else(self):
        """No id, no building type, no collector — those would make this a read
        of the RECORD rather than a check for its existence.

        `count` and `locked` were added by ADR-420 and are a real widening: the
        caller learns how many observations a door has, not just that it has
        one. Accepted because it is still only about an address the caller
        named and already knows is collected, and because the alternative is
        worse — without it a collector is turned away from a door that still
        needs verifying, or walks to one that is closed.

        The set is pinned exactly so the NEXT field has to argue for itself.
        """
        from app.schemas.collection import CollectionCheckOut
        assert set(CollectionCheckOut.model_fields) == {
            "known", "collected_on", "count", "locked",
        }

    def test_the_check_is_scoped_to_the_callers_own_campaign(self):
        """A token must reveal only what that campaign collected. Without the
        token_id filter, one token would answer for the whole table."""
        import inspect
        from app.routers import collection as C
        src = inspect.getsource(C.check_address)
        assert "CollectedAddressProfile.token_id == tok.id" in src, \
            "the check must be scoped to the token's own campaign"

    def test_an_inactive_token_is_rejected_before_any_lookup(self):
        """_resolve_token raises 404 for missing/revoked/expired, so /check
        cannot be used to probe token liveness more cheaply than /submit."""
        import inspect
        from app.routers import collection as C
        src = inspect.getsource(C.check_address)
        assert src.index("_resolve_token") < src.index("door_key(body.address)"), \
            "the token must be resolved before the address is folded or queried"

    def test_the_fold_matches_the_client(self):
        """doorKey() in addressProfile.ts and door_key() here implement one
        rule in two languages. These vectors are the contract between them —
        add a case to BOTH when either moves."""
        from app.services.door_key import door_key
        same = [
            ("380 W 33 ST", "380 West 33rd Street"),
            ("380 w 33 st", "  380 W. 33 St.  "),
            ("12 Fifth Ave", "12 Fifth Avenue"),
            ("500 E 14TH ST APT 3B", "500 East 14th Street"),
            ("45 Park Pl", "45 Park Place"),
        ]
        differ = [
            ("380 W 33 ST", "380 E 33 ST"),
            ("380 W 33 ST", "381 W 33 ST"),
            ("380 W 33 ST", "380 W 34 ST"),
            ("12 Fifth Ave", "12 Fifth St"),
            ("100 Main St", "200 Main St"),
        ]
        for a, b in same:
            assert door_key(a) == door_key(b), f"{a!r} and {b!r} are one door"
        for a, b in differ:
            assert door_key(a) != door_key(b), f"{a!r} and {b!r} are different doors"


class TestTheBuildingTaxonomy:
    """ADR-418. Category is derived, security is a flag, workload is a set."""

    def _ok(self, **over):
        base = {
            "address": "433 W 32 ST", "building_type": "walkup",
            "workloads": ["door_to_door"], "collected_on": "2026-09-15",
        }
        base.update(over)
        return base

    def test_the_category_cannot_be_supplied_by_the_client(self):
        """Two independently supplied fields drift. A row claiming
        residential/loading_dock is worse than a lookup."""
        from app.schemas.collection import CollectedProfileIn
        with pytest.raises(ValidationError, match="[Ee]xtra"):
            CollectedProfileIn(**self._ok(building_category="commercial"))

    def test_every_type_derives_exactly_one_category(self):
        from app.schemas.building_taxonomy import BUILDING_TYPES, category_for
        for t in BUILDING_TYPES:
            assert category_for(t) in {"residential", "commercial", "unknown"}

    def test_the_unknown_sentinel_survives(self):
        """address_inventory.py and place_geometry.py write "unknown" for a
        building nobody has visited. If a taxonomy change dropped it, every
        un-observed building would silently become a real type."""
        from app.schemas.building_taxonomy import (
            BUILDING_TYPES, LEGACY_TYPE_MAP, UNKNOWN_TYPE,
        )
        assert UNKNOWN_TYPE in BUILDING_TYPES
        assert LEGACY_TYPE_MAP[UNKNOWN_TYPE] == UNKNOWN_TYPE

    def test_workloads_must_say_something(self):
        """An empty list was indistinguishable from "not filled in"."""
        from app.schemas.collection import CollectedProfileIn
        with pytest.raises(ValidationError):
            CollectedProfileIn(**self._ok(workloads=[]))

    def test_other_must_come_with_its_text(self):
        """ADR-419. "The four tags do not fit" records that they were wrong
        without recording what is right."""
        from app.schemas.collection import CollectedProfileIn
        with pytest.raises(ValidationError, match="say what it is"):
            CollectedProfileIn(**self._ok(workloads=["other"]))
        ok = CollectedProfileIn(**self._ok(
            workloads=["other"], workload_other="rooftop drone pad"))
        assert ok.workload_other == "rooftop drone pad"

    def test_text_without_the_other_tag_is_rejected(self):
        """Orphaned text is a value nothing would ever read."""
        from app.schemas.collection import CollectedProfileIn
        with pytest.raises(ValidationError, match="only meaningful"):
            CollectedProfileIn(**self._ok(workload_other="stray"))

    @pytest.mark.parametrize("tag", ["high_rise", "bulk_drop"])
    def test_a_walkup_cannot_be_a_highrise_or_a_bulk_drop(self, tag):
        """ADR-419. A walk-up has no elevator, which caps the floors and forces
        every package up the stairs one at a time. Enforced server-side because
        /collection/submit is public — the disabled checkbox is the
        explanation, this is the guarantee."""
        from app.schemas.collection import CollectedProfileIn
        with pytest.raises(ValidationError, match="cannot also be"):
            CollectedProfileIn(**self._ok(building_type="walkup", workloads=[tag]))

    @pytest.mark.parametrize("tag", ["door_to_door", "high_wait"])
    def test_a_walkup_can_still_be_the_compatible_ones(self, tag):
        from app.schemas.collection import CollectedProfileIn
        got = CollectedProfileIn(**self._ok(building_type="walkup", workloads=[tag]))
        assert got.workloads == [tag]

    def test_an_elevator_building_may_be_a_highrise(self):
        """The rule is about walk-ups specifically, not about high_rise."""
        from app.schemas.collection import CollectedProfileIn
        got = CollectedProfileIn(**self._ok(building_type="elevator", workloads=["high_rise"]))
        assert got.workloads == ["high_rise"]

    def test_public_housing_is_a_residential_type(self):
        from app.schemas.building_taxonomy import BUILDING_TYPES, category_for
        assert "public_housing" in BUILDING_TYPES
        assert category_for("public_housing") == "residential"

    def test_multiple_workloads_are_kept_in_order(self):
        """The doorman high-rise: genuinely two things, which the old single
        workload_class could not represent."""
        from app.schemas.collection import CollectedProfileIn
        # `elevator`, not the default `walkup`: a walk-up is neither of these
        # (ADR-419), so the default type would fail for the wrong reason.
        got = CollectedProfileIn(**self._ok(
            building_type="elevator", workloads=["bulk_drop", "high_rise"]))
        assert got.workloads == ["bulk_drop", "high_rise"]

    def test_duplicate_tags_collapse_without_reordering(self):
        from app.schemas.collection import CollectedProfileIn
        got = CollectedProfileIn(**self._ok(
            building_type="elevator", workloads=["high_rise", "bulk_drop", "high_rise"]))
        assert got.workloads == ["high_rise", "bulk_drop"]

    def test_the_security_desk_is_a_flag_not_a_type(self):
        """biz_security forced a false choice: a loading dock WITH a security
        desk had to be filed as one or the other."""
        from app.schemas.building_taxonomy import BUILDING_TYPES, LEGACY_TYPE_MAP
        from app.schemas.collection import CollectedProfileIn
        assert "biz_security" not in BUILDING_TYPES
        assert LEGACY_TYPE_MAP["biz_security"] == "storefront_front_door"
        got = CollectedProfileIn(**self._ok(
            building_type="loading_dock", has_security_desk=True))
        assert got.has_security_desk is True

    def test_every_legacy_value_maps_onto_the_new_taxonomy(self):
        """The migration reads this map. A legacy value with no target would
        leave a row holding a type the schema now rejects."""
        from app.schemas.building_taxonomy import BUILDING_TYPES, LEGACY_TYPE_MAP
        for old, new in LEGACY_TYPE_MAP.items():
            assert new in BUILDING_TYPES, f"{old!r} maps to unknown type {new!r}"

    def test_every_type_has_a_protocol(self):
        """The protocol is what the walker is told to do at the door. A type
        without one shows a blank where the instruction should be."""
        from app.schemas.building_taxonomy import BUILDING_TYPE_PROTOCOL, BUILDING_TYPES
        assert set(BUILDING_TYPES) == set(BUILDING_TYPE_PROTOCOL)


class TestTheVerificationLimit:
    """ADR-420. Two observations verify a door; a third adds cost, not
    information."""

    def test_the_limit_is_two(self):
        from app.schemas.collection import VERIFICATION_LIMIT
        assert VERIFICATION_LIMIT == 2

    def test_the_submit_path_enforces_the_lock_itself(self):
        """The UI refuses a locked door on blur. That is the explanation; this
        is the guarantee — /submit is public, so anything holding a token can
        post a batch the form would never have produced."""
        import inspect
        from app.routers import collection as C
        src = inspect.getsource(C.submit_profiles)
        assert "locked_keys" in src, "submit must check the limit, not trust the client"
        assert "VERIFICATION_LIMIT" in src

    def test_the_lock_is_counted_in_one_grouped_query(self):
        """A batch of a hundred profiles must not become a hundred counts."""
        import inspect
        from app.routers import collection as C
        src = inspect.getsource(C.submit_profiles)
        assert ".group_by(" in src and ".in_(keys)" in src, (
            "the locked-door count must be one grouped query over the batch"
        )

    def test_the_check_reads_a_bounded_number_of_rows(self):
        """The answer only distinguishes 0, 1 and at-the-limit, so there is no
        reason to read an unbounded set to count it."""
        import inspect
        from app.routers import collection as C
        src = inspect.getsource(C.check_address)
        assert "VERIFICATION_LIMIT + 1" in src


class TestCampaignScope:
    """ADR-423. Two campaign kinds, two auth models."""

    def test_the_body_cannot_choose_its_own_scope(self):
        """Scope follows WHO is calling. If the body could set it, a company
        admin could mint an open campaign — the exact boundary this draws."""
        from app.schemas.collection import CollectionTokenCreate
        fields = set(CollectionTokenCreate.model_fields)
        assert "scope" not in fields and "company_id" not in fields
        with pytest.raises(ValidationError):
            CollectionTokenCreate(label="x", scope="open")

    def test_an_open_campaign_carries_no_company(self):
        """NULL is the literal truth — no tenant owns it — and it is what keeps
        open rows out of a company admin's reads: `company_id == <uuid>` never
        matches NULL."""
        from app.models.collection import (
            CollectedAddressProfile, CollectedWalkerDay, CollectionToken,
        )
        for m in (CollectionToken, CollectedAddressProfile, CollectedWalkerDay):
            assert m.__table__.columns["company_id"].nullable, (
                f"{m.__tablename__}.company_id must be nullable to hold an "
                f"open campaign's rows"
            )

    def test_a_company_campaign_requires_an_authenticated_employee(self):
        """The link alone is not enough: it can be forwarded, and a company
        survey is scoped to a staff pool the way Driver Survey is."""
        import inspect
        from app.routers import collection as C
        src = inspect.getsource(C._authorise_scope)
        assert "status_code=401" in src, "unauthenticated must be told to sign in"
        assert "status_code=403" in src, "the wrong tenant must be refused"
        assert "caller.company_id != tok.company_id" in src, (
            "an employee of another company holding this link must not write here"
        )

    @pytest.mark.parametrize("fn_name", [
        "submit_profiles", "check_address", "submit_walker_days",
    ])
    def test_every_public_path_enforces_the_scope(self, fn_name):
        """All three, not just submit. A company campaign's duplicate check
        leaks which doors it holds, so it is gated too."""
        import inspect
        from app.routers import collection as C
        src = inspect.getsource(getattr(C, fn_name))
        assert "_authorise_scope(tok, caller)" in src

    def test_super_admin_creation_needs_no_employee_row(self):
        """The bug this ADR opened on: the page built for the platform owner
        403'd them with "No employee record found for your account", because
        create_token took get_caller_employee unconditionally and a super admin
        has no Employee row by design."""
        import inspect
        from app.api.deps import get_caller_employee
        from app.routers.collection import create_token
        deps = [
            p.default.dependency
            for p in inspect.signature(create_token).parameters.values()
            if hasattr(p.default, "dependency")
        ]
        assert get_caller_employee not in deps, (
            "create_token must not require an Employee row — a super admin has none"
        )
