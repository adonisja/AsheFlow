"""ADR-281 — Phase 0, the ORE day.

Three things these guard, in order of how badly they fail:

  * a forged Content-Type getting an arbitrary file into the bucket
  * the attestation dying with the file, so a trainee's March completion
    evaporates on the third day
  * left_early leaking into anything that reads like a performance signal
"""
import inspect
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.main import app
from app.models.training import TrainingRecord
from app.routers import training as tr
from app.services import ore_certificates as oc


def _code_only(obj) -> str:
    """Source with comments stripped.

    Well-documented code names the thing it avoids. A scanner asserting a name
    is ABSENT will otherwise read its own explanation as the offence — this bit
    ADR-280's seed guard and ADR-277's bulk path before it.
    """
    src = inspect.getsource(obj)
    lines = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
    return "\n".join(ln.split("#")[0] for ln in lines)


class TestRoutes:
    def test_endpoints_registered(self):
        paths = app.openapi()["paths"]
        assert "/api/v1/training/record/{record_id}/ore-certificate" in paths
        assert "/api/v1/training/record/{record_id}/left-early" in paths

    def test_viewing_is_narrower_than_uploading(self):
        """Many people submit evidence; few should read someone else's
        training document."""
        upload = set(tr._allow_ore_upload.allowed_roles)
        view = set(tr._allow_ore_view.allowed_roles)
        assert "trainee" in upload and "trainer" in upload
        assert view == {"management", "admin"}
        assert "trainee" not in view and "trainer" not in view


class TestContentSniffing:
    def test_real_types_are_recognised(self):
        assert oc.sniff_content_type(b"%PDF-1.7") == "application/pdf"
        assert oc.sniff_content_type(b"\xff\xd8\xff\xe0") == "image/jpeg"
        assert oc.sniff_content_type(b"\x89PNG\r\n\x1a\n") == "image/png"

    def test_a_forged_header_cannot_smuggle_a_file_in(self):
        """THE security case. A client sets Content-Type: image/png on an HTML
        page or a script; only the bytes tell the truth."""
        for payload in (b"<!DOCTYPE html>", b"#!/bin/sh\n", b"PK\x03\x04", b"MZ\x90\x00"):
            assert oc.sniff_content_type(payload) is None

    def test_the_endpoint_sniffs_rather_than_trusting_the_header(self):
        src = inspect.getsource(tr.upload_ore_certificate)
        assert "sniff_content_type" in src
        assert "file.content_type" not in src, (
            "the client's Content-Type header must not decide what is stored"
        )


class TestKeyLayout:
    def test_key_carries_no_pii(self):
        """Not the trainee's name, not their email — UUIDs and an extension."""
        key = oc.build_key(uuid4(), uuid4(), "pdf")
        assert key.startswith("ore-certificates/")
        assert key.count("/") == 2
        assert key.endswith(".pdf")

    def test_key_is_company_prefixed(self):
        """So a bucket policy CAN be scoped per tenant later without migrating
        existing objects."""
        cid = uuid4()
        assert oc.build_key(cid, uuid4(), "png").startswith(f"ore-certificates/{cid}/")


class TestAttestationOutlivesTheFile:
    def test_model_separates_attestation_from_pointer(self):
        cols = TrainingRecord.__table__.columns
        for name in (
            "ore_completed_at",
            "ore_certificate_uploaded_by",
            "ore_certificate_key",
            "ore_certificate_expires_at",
            "left_early",
            "left_early_at",
        ):
            assert cols.get(name) is not None, f"ADR-281: {name} missing"

    def test_purge_nulls_the_pointer_but_not_the_attestation(self):
        """The whole point of D2. If the sweep cleared ore_completed_at, a
        trainee who finished ORE in March would lose that fact on day three."""
        from app.tasks.cleanup import purge_expired_ore_certificates

        src = inspect.getsource(purge_expired_ore_certificates)
        assert "record.ore_certificate_key = None" in src
        assert "ore_completed_at = None" not in src, (
            "the attestation must survive the file"
        )

    def test_purge_only_nulls_after_a_confirmed_delete(self):
        """Nulling after a failed delete orphans the object: nothing points at
        it, so nothing retries, and it outlives its retention window."""
        from app.tasks.cleanup import purge_expired_ore_certificates

        src = _code_only(purge_expired_ore_certificates)
        assert "if ore_certificates.delete(" in src
        i = src.index("if ore_certificates.delete(")
        # The null must be INSIDE the success branch. With comments stripped it
        # is the next statement; with them it was 400+ chars away.
        assert "record.ore_certificate_key = None" in src[i : i + 200]

    def test_reupload_does_not_restart_the_completion_clock(self):
        src = inspect.getsource(tr.upload_ore_certificate)
        assert "if record.ore_completed_at is None:" in src

    def test_expired_is_a_distinct_answer_from_never_uploaded(self):
        """404 and 410 mean different things to a manager."""
        src = inspect.getsource(tr.get_ore_certificate)
        assert "HTTP_404_NOT_FOUND" in src
        assert "HTTP_410_GONE" in src
        i = src.index("HTTP_410_GONE")
        assert "ore_completed_at" in src[i : i + 400], (
            "the 410 should still tell the manager when ORE was completed"
        )


class TestLeftEarlyIsNotAMark:
    def test_it_is_scoped_to_phase_zero(self):
        src = inspect.getsource(tr._load_phase_zero_record)
        assert "_PHASE_ZERO" in src
        assert tr._PHASE_ZERO == 0

    def test_it_never_touches_the_scorecard(self):
        """ADR-281 D5: a permitted choice must not become a performance signal."""
        # Code only — the docstring explains D5 by NAMING the scorecard.
        src = _code_only(tr.mark_left_early)
        body = src[src.index('"""', src.index('"""') + 3) + 3:]  # past the docstring
        for forbidden in ("Scorecard", "scorecard", "appeal", "penalty", "infraction"):
            assert forbidden not in body

    def test_no_programme_wide_counter_exists(self):
        """A tally is a judgement waiting for a threshold. Each phase-0 day
        carries its own pay implication; they do not accumulate."""
        cols = set(TrainingRecord.__table__.columns.keys())
        for banned in ("left_early_count", "early_departures", "left_early_total"):
            assert banned not in cols

    def test_it_is_a_one_way_stamp(self):
        """A second call must not fire a second notification."""
        src = inspect.getsource(tr.mark_left_early)
        assert "if record.left_early:" in src
        assert "HTTP_409_CONFLICT" in src

    def test_dispatch_learns_twice(self):
        """D6: the notification is the alert, the field is the truth. A
        notification that fired while nobody was looking must not be the only
        record that someone left."""
        src = inspect.getsource(tr.mark_left_early)
        assert "trainee_left_early" in src
        assert "record.left_early = True" in src


class TestErrorExposure:
    def test_aws_detail_never_reaches_the_client(self):
        """An S3 error names the bucket and the key; an HTTP body is the wrong
        place for either (ADR-115 dim 6)."""
        src = inspect.getsource(oc)
        assert "raise OreCertificateError" in src
        assert "str(exc)" not in src
        assert "detail=str(" not in inspect.getsource(tr.upload_ore_certificate)

    def test_unconfigured_storage_degrades_rather_than_crashing(self):
        """A deploy without the bucket should 503 with a clear message, not
        throw a boto3 error at a trainee mid-upload."""
        src = inspect.getsource(tr.upload_ore_certificate)
        assert "is_enabled()" in src
        assert "HTTP_503_SERVICE_UNAVAILABLE" in src


class TestTenancy:
    def test_record_lookup_is_company_scoped(self):
        src = inspect.getsource(tr._load_phase_zero_record)
        assert "company_id == caller.company_id" in src

    def test_a_trainee_can_only_upload_their_own(self):
        src = inspect.getsource(tr.upload_ore_certificate)
        assert 'caller.role == "trainee"' in src
        assert "record.trainee_id != caller.id" in src

    def test_dispatch_notification_is_company_scoped(self):
        src = inspect.getsource(tr.mark_left_early)
        assert "Employee.company_id == caller.company_id" in src


class TestInjector:
    def test_a_trainees_first_day_is_phase_zero(self):
        """The one line ADR-281 D1 changes. Everything downstream then works
        untouched — the existing phase_closed branch advances 0 -> 1 exactly as
        it advances 1 -> 2."""
        from app.services import training_injection

        # Assert on the BRANCH, not a byte window — the explanatory comment
        # between the condition and the assignment is exactly the kind of thing
        # that grows, and a fixed offset silently stops covering the statement.
        src = _code_only(training_injection)
        i = src.index("if not prev_records:")
        branch = src[i : src.index("else:", i)]
        # Conditional by design: phase 0 only when its curriculum is seeded.
        # Without that, the record would carry no mandatory tasks and auto-close
        # as complete — an ORE day that trained nothing. Adopting ADR-281 is
        # therefore seeding the curriculum, not deploying this code.
        assert "current_phase = 0 if curriculum_by_phase.get(0) else 1" in branch, (
            "a trainee's first record must be phase 0 when phase-0 curriculum exists"
        )

    def test_phase_four_does_not_mirror_phase_zero(self):
        """'Installed the app' is not a Phase 4 demonstration task. The
        allowlist at training_injection.py already excludes 0 — this pins it."""
        from app.services import training_injection

        src = inspect.getsource(training_injection)
        assert "day_number in (1, 2, 3)" in src
