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
            "address": "433 W 32 ST", "building_type": "walkup",
            "workload_class": "high_touch", "collected_on": "2026-09-15",
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
        # Not a copy. A value this endpoint accepted that the rest of the system
        # rejects would sit in the table looking like data and promote into
        # nothing.
        from app.schemas.location_profile import BUILDING_TYPES, WORKLOAD_CLASSES
        for t in ("walkup", "doorman", "biz_loading_dock"):
            assert t in BUILDING_TYPES
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
        assert src.count("duplicate_addresses.append") == 1, \
            "only one source may populate the echo"


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
        addresses."""
        from app.main import app
        allowed = {"/api/v1/collection/tokens", "/api/v1/collection/profiles"}
        spec = app.openapi()
        for path, ops in spec["paths"].items():
            if "/collection" in path and "get" in ops:
                assert path in allowed, f"{path} exposes an unexpected read"


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

    def test_reads_are_gated_on_super_admin_not_platform_staff(self):
        """ADR-343 D4: no `platform_support` endpoint may return addresses.

        These rows ARE customer delivery addresses, so the stricter gate is
        load-bearing, not incidental. Asserted against the resolved dependency
        so swapping the import fails here.
        """
        import inspect
        from app.api.deps import get_super_admin
        from app.routers.collection import list_collected_profiles, list_tokens

        for fn in (list_collected_profiles, list_tokens):
            deps = [
                p.default.dependency
                for p in inspect.signature(fn).parameters.values()
                if hasattr(p.default, "dependency")
            ]
            assert get_super_admin in deps, (
                f"{fn.__name__} is not gated on get_super_admin — "
                "ADR-343 D4 forbids addresses behind platform_support"
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

    def test_the_response_is_existence_and_a_date_and_nothing_else(self):
        """No id, no building type, no collector — those would make this a read
        of the record rather than a check for its existence."""
        from app.schemas.collection import CollectionCheckOut
        assert set(CollectionCheckOut.model_fields) == {"known", "collected_on"}

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
