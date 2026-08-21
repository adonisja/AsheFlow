"""The Building Library boundary holds (ADR-237 D1).

ADR-237 names this as the verification for D1: *"No AsheFlow module outside the
client imports BuildingProfileLibrary or StreetSegment."*

That property is the whole point of the refactor. It is what makes the eventual
physical split (D3) a change to ONE implementation rather than a rewrite of five
call sites — and it degrades silently: a new feature importing the model
directly still works, still passes review, and quietly re-couples two products
that are meant to separate.

Source-reading rather than behavioural, deliberately: the thing being guarded is
an IMPORT, and an import is exactly what an import test should look at. It is
also the shape that catches a NEW file, which no behavioural test would.
"""
from pathlib import Path

import pytest


BACKEND = Path(__file__).resolve().parents[2]
APP = BACKEND / "app"

# The modules allowed to name the platform models directly, and why.
_BUILDING_LIBRARY_ALLOWED = {
    # The boundary itself.
    "app/library/client.py",
    # SQLAlchemy model registry — Alembic autogenerate needs every model
    # imported somewhere.
    "app/models/__init__.py",
    # The model's own definition.
    "app/models/building_profile_library.py",
    # The WRITE surface: promotion, conflict resolution, deprecate. This is the
    # file that transfers to the Library owner (ADR-237), so it is expected to
    # touch the model until that transfer happens.
    "app/routers/building_profile_library.py",
}

_STREET_SEGMENT_ALLOWED = {
    # Topology's own client — owns every read and write of the table (ADR-237 D2).
    "app/services/segment_map.py",
    "app/models/__init__.py",
    "app/models/street_segment.py",
}


def _python_files() -> list[Path]:
    return [p for p in APP.rglob("*.py") if "__pycache__" not in p.parts]


def _importers(symbol: str, module_path: str) -> set[str]:
    """Files with a real `from ... import <symbol>` — not a mention in prose.

    Comments and docstrings name these models constantly (they are how the
    tiering is explained), so a substring search would be all false positives.
    """
    hits: set[str] = set()
    for path in _python_files():
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if f"import {symbol}" in stripped and module_path in stripped:
                hits.add(str(path.relative_to(BACKEND)))
    return hits


class TestLibraryBoundary:
    def test_only_the_client_imports_building_profile_library(self):
        importers = _importers("BuildingProfileLibrary", "building_profile_library")
        unexpected = importers - _BUILDING_LIBRARY_ALLOWED
        assert not unexpected, (
            "these modules import BuildingProfileLibrary directly instead of "
            f"going through app.library.client (ADR-237 D1): {sorted(unexpected)}"
        )

    def test_only_segment_map_imports_street_segment(self):
        importers = _importers("StreetSegment", "street_segment")
        unexpected = importers - _STREET_SEGMENT_ALLOWED
        assert not unexpected, (
            "these modules import StreetSegment directly instead of going "
            f"through services.segment_map (ADR-237 D2): {sorted(unexpected)}"
        )

    def test_the_scan_actually_finds_the_known_importers(self):
        # Guards the guard. If the detection breaks, both tests above pass
        # vacuously and the boundary is unprotected while looking protected —
        # the failure mode that let a "#hub:" test pass against a planted bug.
        importers = _importers("BuildingProfileLibrary", "building_profile_library")
        assert "app/library/client.py" in importers, (
            "the scan found no importers at all — detection is broken, so the "
            "boundary tests are passing for the wrong reason"
        )


class TestClientContract:
    """The client must not reintroduce what the boundary exists to prevent."""

    def _client_source(self) -> str:
        return (APP / "library" / "client.py").read_text(encoding="utf-8")

    def test_client_never_takes_a_company_id(self):
        # ADR-237 audit note, dimension 1: the Library is deliberately
        # un-scoped. A company_id parameter would imply tenancy and invite a
        # caller to expect tenant filtering the Library cannot provide.
        src = self._client_source()
        code = [
            ln for ln in src.splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        offending = [ln for ln in code if "company_id" in ln and "def " in ln]
        assert not offending, (
            f"the Library client must not accept a company_id: {offending}"
        )

    def test_every_read_filters_on_active(self):
        # The invariant the client centralises. Deprecated and conflicted rows
        # exist in the table; serving them into routing produces worse routes
        # with no error.
        src = self._client_source()
        queries = src.count("db.query(BuildingProfileLibrary)")
        actives = src.count("library_status == _ACTIVE")
        assert queries > 0, "no queries found — has the client moved?"
        assert actives == queries, (
            f"{queries} queries but only {actives} filter on active status"
        )

    def test_client_does_not_touch_tenant_models(self):
        # BuildingProfile is tenant-owned and stays in AsheFlow. If the client
        # started reading it, the boundary would be meaningless.
        src = self._client_source()
        code = [
            ln for ln in src.splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        for banned in ("BuildingProfile.", "import BuildingProfile\n", "Employee"):
            assert not any(banned in ln for ln in code), (
                f"the Library client must not reference tenant model {banned!r}"
            )
