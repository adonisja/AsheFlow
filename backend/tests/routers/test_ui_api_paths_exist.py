"""Every API path a UI calls exists on the server (ADR-274 D21).

THE BUG THIS CATCHES
--------------------
`mobile/src/screens/LocationProfiles/` called `/location-profiles/` — a router
ADR-135 DELETED when building intelligence went address-first. Both its calls
404'd, so the screen a walker used to submit building details had been dead
since that rename, silently.

It was invisible from three directions at once:
  - the frontend compiles fine; a URL is just a string
  - the backend has no reference to the caller, so nothing there breaks
  - ADR-100 still reads `accepted` and documents `/location-profiles/` as live,
    with no forward link to ADR-135 which replaced it

WHAT THIS CHECKS
----------------
Extract literal API paths from both UIs, normalise their `${...}` segments to
`{param}`, and require each to match a route registered on the FastAPI app.

Deliberately conservative: only paths in `apiClient.<verb>('...')` or
`axiosClient.<verb>('...')` calls, and only ones that look like API routes. A
false positive here costs more than a missed path — a guard people distrust is
one they switch off.
"""
import re
import sys
from pathlib import Path

import pytest

from app.main import app
import app.main as _m
from app.routers import employees as _employees


ROOT = Path(__file__).resolve().parents[3]
SURFACES = [ROOT / "frontend" / "src", ROOT / "mobile" / "src"]

# Template-literal segments and :params both become {x} for comparison.
_SEG = re.compile(r"\$\{[^}]*\}")
_CALL = re.compile(
    r"""(?:api|axios)Client\.(?:get|post|patch|put|delete)\s*<?[^>(]*>?\s*\(\s*[`'"]([^`'"]+)[`'"]""",
)


# UI shipped ahead of its backend. Listed rather than ignored so the gap is
# visible and dated, and so removing the entry is what proves the feature
# landed.
#
#   /walker-routes/routes/{}/cover-remaining
#     ADR-229 (status: in-progress). The mobile "Cover remaining stops" button
#     in RouteSortScreen calls it; `cover_remaining` does not exist in
#     walker_routes.py on local OR staging, and tests/routers/
#     test_cover_remaining.py skips itself on the failed import — so nothing
#     was failing to say so. Tapping the button errors at runtime.
_KNOWN_UNBUILT = {
    "/walker-routes/routes/{}/cover-remaining",
}


def _registered() -> set[str]:
    """Server routes, stripped of the /api/v1 prefix and param-normalised."""
    out = set()
    for r in app.routes:
        p = getattr(r, "path", "")
        if not p.startswith("/api/v1/"):
            continue
        p = p[len("/api/v1"):]
        out.add(re.sub(r"\{[^}]*\}", "{}", p).rstrip("/") or "/")
    return out


def _ui_paths() -> dict[str, list[str]]:
    """path -> the files that call it."""
    found: dict[str, list[str]] = {}
    for root in SURFACES:
        if not root.exists():
            continue
        for f in root.rglob("*.ts*"):
            if "node_modules" in f.parts:
                continue
            text = f.read_text(encoding="utf-8", errors="ignore")
            for raw in _CALL.findall(text):
                if not raw.startswith("/"):
                    continue                      # relative/asset URL
                path = _SEG.sub("{}", raw.split("?")[0])
                path = re.sub(r"\{[^}]*\}", "{}", path).rstrip("/") or "/"
                found.setdefault(path, []).append(f.name)
    return found


class TestDetectorIsSound:
    """Guards the guard — a parser that finds nothing passes vacuously."""

    def test_it_finds_routes_and_calls(self):
        # Self-diagnosing: when this fires in an environment you cannot attach a
        # debugger to (CI), the message has to carry enough to identify WHICH
        # assumption broke — the app object, the prefix, or the checkout.
        reg = _registered()
        if len(reg) <= 100:
            paths = [getattr(r, "path", "") for r in app.routes]
            prefixes = sorted({"/".join(p.split("/")[:3]) for p in paths})[:12]
            raise AssertionError(
                "route extraction is broken.\n"
                f"  app object:      {app!r}\n"
                f"  app module:      {type(app).__module__}\n"
                f"  total routes:    {len(paths)}\n"
                f"  /api/v1 matches: {len(reg)}\n"
                f"  prefixes seen:   {prefixes}\n"
                f"  sample paths:    {sorted(paths)[:6]}\n"
                f"  main module:     {_m.__file__}\n"
                f"  main.app is app: {_m.app is app}\n"
                f"  v1 router routes:{len(_m.api_v1_router.routes)}\n"
                f"  sample sub-router (employees): "
                f"{len(_employees.router.routes)} routes\n"
                f"  duplicate main loads: "
                f"{[k for k in sys.modules if k.endswith('main') and 'app' in k]}\n"
                f"  v1 PREFIXES PRESENT: "
                f"{sorted({getattr(r,'path','').split('/')[1] for r in _m.api_v1_router.routes if getattr(r,'path','')})}\n"
                f"  router module ids:   "
                f"{[(n, id(sys.modules[n])) for n in sorted(sys.modules) if n.startswith('app.routers.')][:4]}\n"
                f"  employees id here:   {id(_employees)}\n"
                f"  employees in main:   {id(_m.employees)}\n"
                "The prefixes present name WHICH routers made it in; the ones "
                "missing are the ones whose include contributed nothing."
            )
        assert len(_ui_paths()) > 40, "UI call extraction is broken"

    def test_a_known_good_path_resolves(self):
        # If this stops matching, the normalisation has drifted and every
        # assertion below is comparing shapes that can never line up.
        assert "/building-profiles" in _registered()


class TestNoUiCallsAMissingRoute:
    def test_every_ui_path_exists_on_the_server(self):
        """A UI path with no matching server route 404s at runtime.

        Paths whose FINAL segment is a template variable are skipped: the
        client is choosing the verb or sub-resource at runtime
        (`/employees/${id}/${action}`), so no single literal route can match
        and the check would be a guaranteed false positive. Those are exactly
        the calls a static check cannot resolve — flagging them would train
        people to ignore this test.
        """
        registered = _registered()
        # Sanity-gate the BASELINE before comparing against it. Without this,
        # an empty/degenerate `registered` makes EVERY UI path look missing,
        # and the failure reads as "200 broken endpoints" when the truth is
        # "one broken assumption". That is what this test did on its first CI
        # run: it printed a 200-line wall of healthy endpoints, burying the
        # real signal (its own detector had returned nothing).
        #
        # A comparison is only meaningful when both sides loaded.
        assert len(registered) > 100, (
            f"refusing to report missing paths: only {len(registered)} server "
            "routes were extracted, so the comparison baseline is broken, not "
            "the UI. See TestDetectorIsSound for the diagnosis."
        )
        missing = {
            p: sorted(set(files))
            for p, files in _ui_paths().items()
            if p not in registered
            # A trailing template segment is a runtime-chosen verb or an
            # appended query string (`${qs}`): no literal route can match, so
            # flagging it is a guaranteed false positive.
            and not p.endswith("/{}")
            and not p.endswith("{}{}")
            and not re.search(r"[a-z]\{\}$", p)
            and p not in _KNOWN_UNBUILT
        }
        assert not missing, (
            "these UI calls hit paths with no server route — they 404 at "
            "runtime while compiling cleanly:\n  "
            + "\n  ".join(f"{p}  ← {', '.join(f)}" for p, f in sorted(missing.items()))
        )

    def test_the_deleted_router_is_not_referenced(self):
        # The specific corpse: ADR-135 removed location_profiles.py and dropped
        # its tables. Named explicitly so a revival is loud rather than a
        # generic 404 in the sweep above.
        callers = [
            f.name
            for root in SURFACES if root.exists()
            for f in root.rglob("*.ts*")
            if "node_modules" not in f.parts
            # A call, not a mention: the removal comment in roles.ts names the
            # dead path on purpose, and matching prose would make this test
            # fail on its own documentation.
            and re.search(r"""(?:api|axios)Client\.\w+[^(]*\(\s*[`'"]/location-profiles""",
                          f.read_text(encoding="utf-8", errors="ignore"))
        ]
        assert not callers, (
            f"/location-profiles/ was deleted by ADR-135; still called by {callers}"
        )


class TestKnownUnbuiltStaysHonest:
    def test_entries_are_still_actually_missing(self):
        """An entry that now EXISTS must be removed from the allowlist.

        Otherwise the list becomes a place things go to be forgotten — the
        failure mode of every suppression list.
        """
        stale = sorted(_KNOWN_UNBUILT & _registered())
        assert not stale, (
            f"these are now built and must leave _KNOWN_UNBUILT: {stale}"
        )
