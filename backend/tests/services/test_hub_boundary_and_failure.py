"""A hub is not bounded by the company zone, and its failures are visible (ADR-274 D11).

TWO FIXES, ONE FILE — they share a root cause: the hub path inherited a company
default that is wrong for a hub, or failed to inherit one that was right.

F1 — THE HUB DELETED ITS OWN DELIVERIES
`commit_sort` passed the company boundary into route_sort unconditionally.
ADR-214 turns any package outside that boundary with no covering route into a
PackageRemoval, adds it to `not_a_stop_tbas`, and drops it from the route. A hub
delivers OUTSIDE the company zone — that is the entire point — so the rule fired
on exactly the packages the hub existed to carry. Confirmed live on staging: the
hub company HAS a 10-vertex boundary, and a hub-style delivery point sits outside
it.

F3 — A DEAD WORKER LOOKED LIKE A SLOW ONE
The company upload pre-writes a `manifest_failed` sentinel so an unreachable
Celery worker surfaces as an error. The hub branch skipped it, so a failed
enrichment left the commit gate reporting "waiting on the hub manifest" forever —
byte-identical to a healthy upload still in flight.

Source-reading, and comment-stripped: this exact area already produced a test
that passed against a planted bug because the token under test appeared in an
explanatory comment.
"""
from pathlib import Path

import pytest


BACKEND = Path(__file__).resolve().parents[2]
SORT_ROUTER = BACKEND / "app" / "routers" / "sort.py"
WALKER_ROUTER = BACKEND / "app" / "routers" / "walker_routes.py"


def _code_only(text: str) -> str:
    """Strip comments and blank lines; keep code lines intact.

    Trailing comments are removed ONLY on lines with no quotes — the hub scope
    is an f-string containing '#', and a naive split truncates the very line
    most of these assertions test.
    """
    out = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "#" in stripped and '"' not in stripped and "'" not in stripped:
            stripped = stripped.split("#")[0].strip()
        if stripped:
            out.append(stripped)
    return "\n".join(out)


def _function(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    start = text.index(f"def {name}(")
    nxt = text.find("\n@router.", start)
    return _code_only(text[start:nxt if nxt != -1 else len(text)])


@pytest.fixture(scope="module")
def commit_src() -> str:
    return _function(WALKER_ROUTER, "commit_sort")


@pytest.fixture(scope="module")
def upload_src() -> str:
    return _function(SORT_ROUTER, "upload_manifest")


@pytest.fixture(scope="module")
def zonestatus_src() -> str:
    return _function(SORT_ROUTER, "get_zone_status")


class TestStrippingWorks:
    """Guards the guard — every assertion below is vacuous if this breaks."""

    def test_comments_gone_code_kept(self, commit_src: str):
        assert "company_boundary" in commit_src, "function body not captured"
        assert "A HUB HAS NO BOUNDARY" not in commit_src, (
            "comments survived stripping — assertions could match prose"
        )

    def test_hub_scope_fstring_survived(self, upload_src: str):
        assert '#hub:' in upload_src, (
            "the hub scope f-string was truncated by comment-stripping"
        )


class TestHubHasNoBoundary:
    """F1 — the fix, and the two ways it silently regresses."""

    def test_boundary_is_conditional_on_is_hub(self, commit_src: str):
        assert "None if is_hub else _get_company_boundary(db, cid)" in commit_src, (
            "the company boundary is passed unconditionally: every hub package "
            "outside the company zone becomes a PackageRemoval instead of a "
            "stop, so the hub deletes exactly the deliveries it exists to make"
        )

    def test_boundary_still_resolved_for_normal_trucks(self, commit_src: str):
        # The fix must not disable ADR-214 for everyone.
        assert "_get_company_boundary(db, cid)" in commit_src, (
            "out-of-zone detection was removed for NORMAL trucks too"
        )

    def test_is_hub_is_bound_before_the_boundary_is_chosen(self):
        # An ordering regression would raise UnboundLocalError at runtime on
        # EVERY commit_sort, hub or not — a source test catches it at import.
        text = WALKER_ROUTER.read_text(encoding="utf-8")
        body = text[text.index("def commit_sort("):]
        assign = body.index("is_hub = bool(truck and truck.is_hub)")
        use = body.index("None if is_hub else _get_company_boundary")
        assert assign < use, (
            "is_hub is used before it is assigned — commit_sort would raise "
            "UnboundLocalError for every truck"
        )

    def test_single_boundary_source(self, commit_src: str):
        # Telemetry reads `company_boundary` too (boundary_present). Fixing only
        # the sort call would leave the telemetry claiming a hub ran bounded.
        assert commit_src.count("_get_company_boundary(") == 1, (
            "the boundary must be resolved ONCE so every consumer — the sort "
            "call and the ADR-273 telemetry — agrees a hub ran unbounded"
        )


class TestHubFailureIsVisible:
    """F3 — a dead worker must not look like a slow one."""

    def test_hub_upload_writes_the_failure_sentinel(self, upload_src: str):
        assert 'f"manifest_failed:{cid_str}:{hub_scope}"' in upload_src, (
            "no worker_unreachable sentinel on the hub branch: a dead Celery "
            "worker leaves the gate saying 'waiting on the hub manifest' "
            "forever, identical to a healthy upload still enriching"
        )

    def test_sentinel_is_namespaced_to_the_hub(self, upload_src: str):
        # An un-namespaced key would collide with the COMPANY manifest's
        # sentinel: a hub upload would mark the company manifest failed.
        assert 'f"manifest_failed:{cid_str}:{date_str}"' in upload_src, (
            "company sentinel missing — regression on the normal path"
        )
        assert upload_src.count("manifest_failed:") == 2, (
            "expected exactly two sentinel writes (company + hub); a shared key "
            "would let one upload mark the other's manifest failed"
        )

    def test_sentinel_ttl_matches_the_company_path(self, upload_src: str):
        for line in upload_src.splitlines():
            if "manifest_failed:{cid_str}:{hub_scope}" in line:
                assert "_REDIS_TTL_SECONDS" in line, (
                    "the hub sentinel must share the company TTL — a short TTL "
                    "would expire the failure and revert to a silent wait"
                )
                return
        pytest.fail("hub sentinel write not found")


class TestZoneStatusReportsWhy:
    """The sentinel is only worth writing if something reads it."""

    def test_state_is_on_the_schema(self):
        text = SORT_ROUTER.read_text(encoding="utf-8")
        i = text.index("class ZoneStatusOut")
        assert "hub_manifest_state: Optional[str] = None" in text[i:i + 1400], (
            "without this field all three not-ready states render identically"
        )

    def test_enriching_wins_while_both_keys_exist(self, zonestatus_src: str):
        # CORRECTED after a staging run disproved the first version of this test.
        # I originally asserted failed-beats-enriching. But the upload writes the
        # enriching sentinel AND worker_unreachable in the same breath, and the
        # Celery task clears the failure key only once it starts — so "both
        # present" is the normal first seconds of EVERY upload. Ordering failure
        # first reported a healthy in-flight upload as failed, telling the
        # dispatcher to re-upload a manifest that was fine.
        #
        # worker_unreachable is a DEFERRED signal, meaningful only after the
        # 5-minute enriching key expires. A genuine task failure still surfaces
        # immediately because the task deletes the enriching key on its way out.
        src = zonestatus_src
        e = src.index('hub_states[tid] = "enriching"')
        f = src.index('hub_states[tid] = "failed"')
        assert e < f, (
            "failure is checked before enriching — every healthy upload would "
            "report 'failed' until the worker picked it up"
        )
        assert "elif" in src[e:f], "the states must be exclusive branches"

    def test_state_only_resolved_when_not_ready(self, zonestatus_src: str):
        # A loaded manifest needs no explanation, and this keeps two Redis reads
        # per hub off the steady-state poll.
        assert "if not hub_counts.get(tid):" in zonestatus_src, (
            "state is resolved even when the hub is ready — needless Redis reads "
            "on every poll from every driver"
        )

    def test_state_is_company_scoped(self, zonestatus_src: str):
        # Redis has no row-level tenancy; the key is the boundary.
        for line in zonestatus_src.splitlines():
            if "manifest_failed:" in line:
                assert "{cid_str}" in line, "sentinel read is not company-scoped"
                assert "{hub_scope}" in line, "sentinel read is not hub-scoped"
                return
        pytest.fail("no sentinel read in zone-status")

    def test_state_is_none_for_normal_trucks(self, zonestatus_src: str):
        assert "hub_manifest_state=hub_states.get(tid) if is_hub else None" in zonestatus_src, (
            "a normal truck must never carry a hub manifest state"
        )
