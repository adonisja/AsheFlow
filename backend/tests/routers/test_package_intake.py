"""Unregistered package intake endpoints (ADR-246).

The service layer's decisions are tested in tests/services/test_package_intake.py.
This covers what the HTTP edge adds: who may call what, that a walker cannot
write to someone else's route, and that the oversight feed is readable by the
role that actually needs it.

The gate split is the point. A walker self-adding to their own route is a field
action; placing a package on *someone else's* route is a dispatch decision.
Conflating them would let any walker write to any route.
"""
from app.api.deps import RoleChecker
import app.routers.package_intake as pi


FIELD = {"walker", "trainer", "trainee", "driver", "dispatch", "management", "admin"}
DISPATCH = {"dispatch", "management", "admin"}


class TestAccess:
    def test_self_add_is_open_to_field_roles(self):
        """Any field role can be the one who opens the tote — a trainer
        covering a route finds packages exactly as a walker does."""
        assert set(pi._allow_field.allowed_roles) == FIELD

    def test_assign_is_dispatch_only(self):
        assert set(pi._allow_dispatch.allowed_roles) == DISPATCH

    def test_no_field_role_can_assign_to_another_route(self):
        for r in ("walker", "trainer", "trainee", "driver"):
            assert r not in pi._allow_dispatch.allowed_roles

    def test_every_route_is_gated(self):
        for route in pi.router.routes:
            gates = [d.call for d in route.dependant.dependencies
                     if isinstance(d.call, RoleChecker)]
            assert gates, f"{route.path} is ungated"

    def test_the_right_gate_is_on_the_right_route(self):
        """Dimension 2: the gate must match who operationally initiates the
        action, not merely who has authority."""
        expected = {
            "/packages/intake": FIELD,
            "/packages/intake/preview": FIELD,
            "/packages/intake/read-label": FIELD,
            "/packages/intake/assign": DISPATCH,
            # Dry run of /assign. Same gate as the write it previews: a preview
            # that showed a wider audience which routes exist would leak the
            # roster to field roles.
            "/packages/intake/assign/preview": DISPATCH,
            "/packages/intake/field-added": DISPATCH,
        }
        for route in pi.router.routes:
            gate = next(d.call for d in route.dependant.dependencies
                        if isinstance(d.call, RoleChecker))
            assert set(gate.allowed_roles) == expected[route.path], route.path

    def test_dispatch_can_read_the_oversight_feed(self):
        """THE point of the endpoint existing (ADR-246).

        write_audit already records every intake, but GET /audit is gated
        ["management", "admin"] — dispatch cannot read it. Pointing oversight
        there would satisfy the requirement on paper and not in practice.
        """
        feed = next(r for r in pi.router.routes
                    if r.path == "/packages/intake/field-added")
        gate = next(d.call for d in feed.dependant.dependencies
                    if isinstance(d.call, RoleChecker))
        assert "dispatch" in gate.allowed_roles

        import app.routers.audit as audit_router
        audit_gates = [
            d.call for r in audit_router.router.routes
            for d in r.dependant.dependencies if isinstance(d.call, RoleChecker)
        ]
        assert audit_gates, "audit router has no RoleChecker — re-check this test"
        assert all("dispatch" not in g.allowed_roles for g in audit_gates), (
            "dispatch can now read GET /audit — if that is intentional, this "
            "feed's justification changes and ADR-246 should be revisited"
        )


class TestAssignPreview:
    """The dry run must not be able to write, and must agree with the write."""

    def test_preview_never_commits(self):
        """`commit=False` plus a rollback in `finally`.

        Asserted on the SOURCE rather than by calling it, because the failure
        this guards against is someone later copying /assign's body into the
        preview and losing the flag — which a happy-path call would not catch.
        """
        import inspect
        src = inspect.getsource(pi.dispatch_assign_preview)
        assert "commit=False" in src, "preview must not commit"
        assert "db.rollback()" in src, "preview must roll back"
        assert "finally:" in src, "rollback must be in finally, not the happy path"

    def test_preview_is_not_201(self):
        """A request that writes nothing must not share a status code with one
        that does. /assign is 201 CREATED; the preview is a plain 200."""
        preview = next(r for r in pi.router.routes
                       if r.path == "/packages/intake/assign/preview")
        assign = next(r for r in pi.router.routes
                      if r.path == "/packages/intake/assign")
        assert assign.status_code == 201
        assert preview.status_code in (None, 200)

    def test_preview_runs_the_same_resolver_as_assign(self):
        """A preview that could disagree with the commit is worse than none."""
        import inspect
        assert "_resolve(" in inspect.getsource(pi.dispatch_assign_preview)
        assert "_resolve(" in inspect.getsource(pi.dispatch_assign)

    def test_preview_is_not_restricted_to_own_route(self):
        """The reason this endpoint exists: /preview passes
        `restrict_to_own_route=True`, and a dispatcher has no route of their
        own, so it can never return the candidates a dispatcher chooses from.

        Checks the CALL, not the whole source — the docstring names the flag to
        explain why this endpoint exists, and a substring match on the file
        would fail on its own explanation.
        """
        import inspect, re
        src = inspect.getsource(pi.dispatch_assign_preview)
        call = re.search(r"_resolve\((.*?)\)", src, re.S)
        assert call, "preview must call _resolve"
        assert "restrict_to_own_route" not in call.group(1)


class TestRouteShadowing:
    """A catch-all declared before a literal shadows it (ADR-242 cost us this
    twice: /{week} swallowed /company/current)."""

    def test_literal_paths_are_reachable(self):
        paths = [r.path for r in pi.router.routes]
        assert "/packages/intake/preview" in paths
        assert "/packages/intake/assign" in paths
        assert "/packages/intake/field-added" in paths

    def test_no_path_parameter_precedes_a_literal(self):
        seen_param = None
        for route in pi.router.routes:
            if seen_param and "{" not in route.path:
                raise AssertionError(
                    f"{route.path} is declared after the catch-all "
                    f"{seen_param} and may be shadowed"
                )
            if "{" in route.path:
                seen_param = route.path


class TestAuditContract:
    def test_action_type_is_stable(self):
        """The oversight feed filters on this exact string, and ADR-246 names
        it. Changing it silently empties the feed."""
        assert pi._ACTION == "package.field_added"

    def test_feed_reads_the_snapshot_not_a_nested_detail_key(self):
        """write_audit maps `detail=` onto `after`, so after_snapshot IS the
        detail dict. Reading row.after_snapshot["detail"] finds nothing and the
        feed silently returns empty."""
        import inspect
        src = inspect.getsource(pi.field_added_packages)
        assert 'after_snapshot or {}' in src
        assert '.get("detail")' not in src


class TestLabelRead:
    """OCR is an assist, never a gate (ADR-246)."""

    def test_the_walker_who_holds_the_package_can_scan_it(self):
        route = next(r for r in pi.router.routes
                     if r.path == "/packages/intake/read-label")
        gate = next(d.call for d in route.dependant.dependencies
                    if isinstance(d.call, RoleChecker))
        assert set(gate.allowed_roles) == FIELD

    def test_a_failed_read_is_200_not_an_error(self):
        """The client must treat 'could not read it' as a normal outcome that
        falls back to typing. Returning 4xx/5xx would surface an error banner
        for something the walker resolves by using the form that is already
        on screen."""
        import inspect
        src = inspect.getsource(pi.read_label)
        # The except branch returns a response rather than re-raising.
        assert "needs_manual_entry=True" in src
        assert "ocr_unavailable" in src
        assert "raise" not in src.split("except Exception:")[1]

    def test_ocr_failure_does_not_leak_the_exception(self):
        """Dimension 6 — no str(e) reaching the client."""
        import inspect
        src = inspect.getsource(pi.read_label)
        assert "str(e)" not in src
        assert "str(exc)" not in src

    def test_upload_is_bounded(self):
        """Textract bills per page, and this accepts uploads from the field."""
        assert pi._MAX_LABEL_BYTES == 10 * 1024 * 1024
        assert "application/pdf" in pi._ALLOWED_LABEL_TYPES
        assert "image/jpeg" in pi._ALLOWED_LABEL_TYPES


class TestOutOfZoneIsTerminal:
    """A dry run must not build a custody record (ADR-259).

    `_resolve` calls `create_foreign_removal` AND `write_audit` on the
    out-of-zone branch. Both previews pass `commit=False` and roll back in
    `finally`, so nothing persisted — but the rows were being constructed and
    an audit row emitted, undone only by the rollback.

    This branch had never executed in production: no client ever sent
    coordinates, so `check_zone` answered `no_coords` every time and ownership
    was never decidable. Geocoding server-side makes it reachable for the first
    time, which is exactly when an unexercised write path needs a test.

    Reuses the service suite's in-memory harness rather than duplicating its
    SQLite ARRAY/JSONB shims — importing it applies the compiler hooks.
    """
    import uuid as _uuid
    from datetime import date as _date

    @staticmethod
    def _payload(tba="TBA999", **kw):
        from app.schemas.package_intake import DispatchAssignRequest
        # Coordinates well north of the test square: decidably outside.
        base = dict(tba=tba, lat=40.90, lng=-73.90)
        base.update(kw)
        return DispatchAssignRequest(**base)

    def _caller(self, db, company):
        from app.models.employee import Employee
        e = Employee(id=self._uuid.uuid4(), company_id=company, name="Dispatcher",
                     role="dispatch", is_active=True,
                     hr_system_id_adp=self._uuid.uuid4())
        db.add(e)
        db.commit()
        return e

    def test_preview_reports_removal_without_creating_one(self):
        from tests.services.test_package_intake import COMPANY, _SQUARE
        from app.models.company import Company, CompanyZone
        from app.models.base import Base
        from app.models.tote_ops import PackageRemoval
        from app.models.audit_log import AuditLog
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        eng = create_engine("sqlite:///:memory:",
                            connect_args={"check_same_thread": False})
        Base.metadata.create_all(eng)
        db = sessionmaker(bind=eng)()
        db.add(Company(id=COMPANY, name="Test Co", slug="t", is_active=True))
        db.add(CompanyZone(id=self._uuid.uuid4(), company_id=COMPANY, name="Z",
                           bounds=_SQUARE, is_active=True))
        db.commit()
        caller = self._caller(db, COMPANY)

        res = pi._resolve(db, caller, self._payload(), commit=False)

        # The verdict is still reported — out-of-zone is a real answer.
        assert res.outcome == "removal"
        assert res.reason == "out_of_zone"
        # ...but with no id, because nothing was created to have one.
        assert res.removal_id is None

        # Nothing constructed, not even pending in the session.
        db.rollback()
        assert db.query(PackageRemoval).count() == 0
        assert db.query(AuditLog).count() == 0
        db.close()
        eng.dispose()

    def test_the_committing_path_does_create_one(self):
        """The guard must not have disabled the real behaviour — a genuine
        out-of-zone assign still opens the custody chain (ADR-176)."""
        from tests.services.test_package_intake import COMPANY, _SQUARE
        from app.models.company import Company, CompanyZone
        from app.models.base import Base
        from app.models.tote_ops import PackageRemoval
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        eng = create_engine("sqlite:///:memory:",
                            connect_args={"check_same_thread": False})
        Base.metadata.create_all(eng)
        db = sessionmaker(bind=eng)()
        db.add(Company(id=COMPANY, name="Test Co", slug="t", is_active=True))
        db.add(CompanyZone(id=self._uuid.uuid4(), company_id=COMPANY, name="Z",
                           bounds=_SQUARE, is_active=True))
        db.commit()
        caller = self._caller(db, COMPANY)

        res = pi._resolve(db, caller, self._payload(), commit=True)

        assert res.outcome == "removal"
        assert res.removal_id is not None
        assert db.query(PackageRemoval).count() == 1
        db.close()
        eng.dispose()

    def test_no_candidates_are_offered_when_the_package_is_not_ours(self):
        """Out-of-zone is terminal: the package is not ours, so no route is
        offered. Showing a picker would invite dispatch to deliver a package
        that belongs to another carrier."""
        from tests.services.test_package_intake import COMPANY, _SQUARE
        from app.models.company import Company, CompanyZone
        from app.models.base import Base
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        eng = create_engine("sqlite:///:memory:",
                            connect_args={"check_same_thread": False})
        Base.metadata.create_all(eng)
        db = sessionmaker(bind=eng)()
        db.add(Company(id=COMPANY, name="Test Co", slug="t", is_active=True))
        db.add(CompanyZone(id=self._uuid.uuid4(), company_id=COMPANY, name="Z",
                           bounds=_SQUARE, is_active=True))
        db.commit()
        caller = self._caller(db, COMPANY)

        res = pi._resolve(db, caller, self._payload(), commit=False)
        assert res.assessment is None
        db.close()
        eng.dispose()
